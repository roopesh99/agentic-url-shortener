# The three scenarios

Each scenario ran live through the orchestrator (analyst, impact analyst and test planner on OpenAI
`gpt-6-luna`; coder and tester served by a Claude Code session; every human decision by the product
owner). Each one replays offline and reproduces its committed code exactly
(`scripts/replay-scenarios.sh`). Full reports: `runs/samples/<run>/report.md`.

| | Greenfield | Brownfield | Ambiguous |
|---|---|---|---|
| Input | `scenarios/greenfield.md` | `scenarios/brownfield-analytics.md` | `scenarios/ambiguous-reliability.md` (3 sentences) |
| Run | `live-greenfield-2` | `live-brownfield-1` | `live-ambiguous-1` |
| Workflow | `skeleton` (4 stages) | `brownfield` (5 stages) | `brownfield` (5 stages) |
| Human decisions | 7 answers, 2 approvals | 4 answers, 4 approvals | 16 answers, 4 approvals incl. 1 change request |
| Outcome | service v1, 77 tests | click analytics, 95 tests | hardening and observability, 120 tests |
| Active time / waiting for humans | 15.2 min / 34.8 h | 11.8 min / 44.4 min | 20.6 min / 1.8 h (+32.8 min stopped) |
| Live LLM calls, output tokens | 3, 32,140 | 5, 35,336 | 8, 88,089 |
| Commits produced | `cbb7946` | `1a9a262` `a3b4aed` `94d3336` | `014bce6` `f688d03` `c225b82` |

---

## 1. Greenfield: build the service from a requirement

**Decomposition.** `requirements` (analyst) → `implement` (coder) ∥ `test_plan` (test planner) → `test`
(tester, joins both). Gates: output structure and ambiguity resolution; `mvn compile`; `mvn test`.

**Orchestration, as it happened.**
1. The analyst normalized the requirement into 6 functional and 5 non-functional requirements and
   found 15 ambiguities: it resolved 9 with stated assumptions and **refused to guess 6** (alias rules,
   rate limit, who may delete, persistence, blocked destinations, how p99 is measured).
2. The pipeline stopped. (The first attempt, `live-greenfield-1`, ended here: there was no way yet for a
   person to answer, which is why clarification checkpoints exist.) The owner answered 6, then 1
   follow-up the answers raised (may deleted codes be reused? no).
3. The owner approved the spec (v3, 18 acceptance criteria). `implement` and `test_plan` ran in parallel.
4. Policy flagged the coder's database migration (high risk); the owner approved it before it was
   written. `mvn compile` passed. The tester implemented the 33-case plan; `mvn test` passed: 77 tests.

**Validation.** Gates: 2 Maven builds; policy: 5 low-risk, 1 high-risk evaluation; human: 2 approvals,
7 answers. Run metrics: 100% stage success, 0 failure retries, 0 incidents.

## 2. Brownfield: add click analytics to existing code

**Decomposition.** Adds an `impact` stage between requirements and implementation: the impact analyst
reads the existing code and its plan is approved before any change. Guards: `mvn test` must run at
least 78 tests (the suite had 77), and modifying an existing test requires approval.

**Orchestration, as it happened.**
1. Analyst: 3 product questions (history window, public or private stats, retention on delete), then 1
   follow-up (unique visitors). Owner: 30 days, **private**, erase on delete, no unique visitors. The
   analyst also turned "no visitor profiles" into a testable criterion.
2. Owner approved the spec and explicitly accepted a trade-off: a click may be lost if recording fails,
   because the redirect must never fail.
3. The impact analyst read 22 files and produced a plan: 3 new files, 5 modified, a V2 migration, and
   **a race between recording a click and deleting the link** that the change would introduce. Owner
   approved the plan.
4. Coder: V2 migration (policy: owner approved), best-effort click recording, private stats, erase on
   delete under a row lock. Verified first against a copy of a real v1 database.
5. Tester: 18 new tests in new classes and 2 one-line edits to existing tests (a constructor argument,
   the expected migration list). Policy flagged both edits; the owner approved them after seeing the
   diffs. `mvn test`: 95 tests (77 existing unchanged + 18).
6. The run worked on branch `orch/live-brownfield-1`; the owner merged it.

**Validation.** Existing behaviour: all 77 previous tests pass against the new code. Race: both
interleavings tested, and removing the locks makes both tests fail. Privacy: a redirect carrying IP,
user agent, cookie and referrer stores none of them. Latency: p99 1.1 ms with recording.

## 3. Ambiguous: "make it more reliable and secure"

**Decomposition.** Same `brownfield` workflow; the point is how the system handles an under-specified,
mixed request with an implicit "whatever you think matters most".

**Orchestration, as it happened.**
1. From three sentences the analyst derived **one** firm requirement (do not break existing links)
   and asked **8** scoping questions (reliability targets, observed failures, threat model, controls,
   boundaries, error behaviour, release gate).
2. Round 2: 6 follow-ups, including a **contradiction in the owner's own answers** ("never a 5xx" vs
   "503 when the database is down"). Round 3: the Retry-After value, a question the analyst had first
   resolved itself and then re-opened.
3. The stage hit its round limit and stopped. The fix was a reviewed workflow change (3 rounds), and
   `orch resume` replayed every recorded call and answer at no cost.
4. The spec was complete, but two of the analyst's assumptions would have **broken the existing API**
   (wrong-token 403 → 401, renamed error codes). The owner **rejected it with a change request**;
   the orchestrator gained change requests, resumed, and the revision applied the instruction verbatim.
   The revision raised one new question (round 4: do missing tokens count toward the throttle? no).
5. Approved spec: 23 requirements. The impact analyst planned 6 new and 6 modified production files,
   noticing that the new 503 path must not override the existing best-effort click recording.
6. Coder: standard error schema, 503 + `Retry-After: 5` on store outage, failed-token throttle (10 per
   rolling minute, wrong tokens only), 16 KiB body limit, security headers, loopback-only Actuator with
   a `shortener.redirects` metric. Policy flagged the `application.yml` change; owner approved.
7. Tester: 25 new tests in 5 new classes and **no existing test modified** (one new test properties file
   instead of the plan's 4 edits). `mvn test`: 120 tests. Merged.

**Validation.** All 95 previous tests pass unchanged. Real-socket tests: the management port answers
on 127.0.0.1 and is unreachable from the machine's LAN address. Disabling the throttle, or dropping one
header, fails 3 tests each. Run metrics: 1 incident (`requirements`, 3 failures, recovered after 54 min,
including the time spent fixing the orchestrator), 4 processes, 10 recorded decisions reused by resumes.

---

## Supporting runs

| Run | Purpose |
|---|---|
| `live-greenfield-1` | the first greenfield attempt, failed at the ambiguity gate before clarification existed; kept so the success rate is honest (4 of 5 runs) |
| `demo-fault-injection` | stub agents with two injected faults: a compile failure (rolled back and retried) and a refusal (fallback agent), so retries, rollback and MTTR appear in a real run |
