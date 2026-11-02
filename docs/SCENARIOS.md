# The scenarios

The three the assignment asks for (greenfield, brownfield, ambiguous), plus a fourth that runs the
full lifecycle: requirements, impact, **design, implementation, testing, documentation and release
readiness**, a fifth that fixes a real bug, **reproducing it with a failing test before any fix**, and two runs
whose workflow was **chosen by `orch run auto`** (§6, §7). Each scenario ran live through the orchestrator (analyst, impact analyst and test planner on OpenAI
`gpt-6-luna`; coder and tester served by a Claude Code session; every human decision by the product
owner). Each one replays offline and reproduces its committed code exactly
(`scripts/replay-scenarios.sh`). Full reports: `runs/samples/<run>/report.md`.

| | Greenfield | Brownfield | Ambiguous | Full lifecycle | Bug fix |
|---|---|---|---|---|---|
| Input | `scenarios/greenfield.md` | `scenarios/brownfield-analytics.md` | `scenarios/ambiguous-reliability.md` (3 sentences) | `scenarios/lifecycle-expiry.md` | `scenarios/bugfix-idn.md` (a user bug report) |
| Run | `live-greenfield-2` | `live-brownfield-1` | `live-ambiguous-1` | `live-lifecycle-1` | `live-bugfix-1` |
| Workflow | `skeleton` (4 stages) | `brownfield` (5 stages) | `brownfield` (5 stages) | `lifecycle` (8 stages) | `bugfix` (5 stages) |
| Human decisions | 7 answers, 2 approvals | 4 answers, 4 approvals | 16 answers, 4 approvals incl. 1 change request | 3 answers, 7 approval decisions incl. 2 change requests and the release sign-off | 1 answer, 5 approvals incl. a new dependency and the release sign-off |
| Outcome | service v1, 77 tests | click analytics, 95 tests | hardening and observability, 120 tests | expiry changes, OpenAPI definition, README and API reference, changelog and release 1.1.0 record, 138 tests | internationalized and underscore hosts accepted, release 1.2.0, 150 tests |
| Active time / waiting for humans | 15.2 min / 34.8 h | 11.8 min / 44.4 min | 20.6 min / 1.8 h (+32.8 min stopped) | 17.7 min / 1.7 h (+59 s stopped) | 11.7 min / 17.6 min |
| Live LLM calls, output tokens | 3, 32,140 | 5, 35,336 | 8, 88,089 | 11, 76,712 | 6, 43,237 |
| Commits produced | `ca25c18` | `a3163a6` `2016785` `b5c4980` | `6883101` `624a5d7` `e7efb93` | `295128a` `737ff7f` `9d95cf7` `7331904` `523b2fa` `0e47485` | `bd2852d` `092f844` `5bc359a` |

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

## 4. Full lifecycle: let owners change a link's expiry

**Decomposition.** `workflows/lifecycle.yaml`, 8 stages, 4 of them human-approved:

```
requirements ─► impact ─► design ─┬─► implement ─┬─► test ─────┐
  (approve)    (approve)  (approve)│ [entry gate] │              ├─► release  [entry gate] (approve)
                                   └─► test_plan ─┘ └─► docs ────┘
```

| Stage | Agent produces | Gates the orchestrator runs |
|---|---|---|
| `design` | `url-shortener/openapi.yaml` (the whole API) and `docs/design.md` | exit: a real OpenAPI validator; human approval |
| `implement` | the code | **entry:** the approved definition is still valid; exit: `mvn compile` and **two-way conformance** (every documented operation is implemented, no implemented endpoint is undocumented) |
| `docs` | `README.md`, `docs/api.md` | exit: every path in the definition is documented |
| `release` | `CHANGELOG.md`, `docs/releases/<version>.md` (checklist, risks, rollback plan) | **entry: the full test suite is re-run**; exit: no failing checklist item; the human release sign-off |

**Orchestration, as it happened.**
1. The analyst resolved 8 points itself (PATCH, `null` removes the expiry, existing error contracts)
   and asked the 2 product questions. The owner: **an expired link is never revived** (410
   `expired`); no maximum expiry. The analyst then noticed that this answer made an accidental past
   expiry irreversible and asked a follow-up; the owner: reject it with 400 `invalid_expiry`, as at
   creation. Spec v3 approved: 10 requirements, 11 acceptance criteria.
2. **Two change requests on the impact plan.** v1 was technically sound but named documentation files
   the workflow never produces (the analyst could not see where later stages write; fixed since, see
   `downstream_context`). v2 fixed the locations but, despite "keep the technical plan unchanged",
   dropped the PATCH throttle test and the click-recording race test. v3 restored both; approved.
3. The architect wrote a 679-line OpenAPI 3.0.3 definition of all 7 operations (6 existing, checked
   against the code status by status, plus PATCH) and a design note; validator passed; approved.
4. `implement` ∥ `test_plan`. The entry gate re-validated the definition; the conformance gate then
   confirmed **7 operations documented and implemented, none undocumented**.
5. `test` ∥ `docs`. Tester: 18 new tests (13 in a new class; a PATCH case added to the throttle test and
   4 expiry races added to the race test, as the approved plan required). Policy flagged the two edited
   existing test files; the owner approved after seeing that only class comments changed and every
   existing test method was untouched. `mvn test`: 138. Docs gate: 7 of 7 operations covered.
6. **Release failed once, and the guardrail held.** The entry gate re-ran all 138 tests; the release
   agent passed 11 checklist items but marked "readiness review recorded complete" as failing, since
   the record it was writing *is* that review and the human sign-off comes after it. A prompt bug: the
   checklist gate blocked the release and the stage was rolled back (2 files reverted). After a
   prompt fix, `orch replan --from release` re-ran only that stage (7 stages reused by lineage).
   Release 1.1.0: 10 items, none failing; the owner signed off.

**Validation.** All 120 previous tests pass unchanged. Four mutations (reviving an expired link,
reading a missing field as "remove", PATCH bypassing the throttle, updating without the row lock)
each fail a new test. Run metrics: 89% stage success (the rolled-back release attempt), 1 incident,
MTTR 3.0 min.

**Found by this run and fixed afterwards** (`cf2556a`): the re-plan of a *failed* stage was logged as a
plain resume, so its reason is missing from this run's log (it is in the evidence commit message);
the release prompt bug; the impact analyst's missing view of downstream write scopes. The replay
uses the workflow file as the run started, and the fixed release prompt, so its release passes first
time; the delivered code is identical.

## 5. Bug fix: links to international host names were rejected

**The bug is real.** While auditing the service for a bug-fix scenario, a probe of the running service
showed `https://müller.de/…`, `https://例え.jp/` and `https://my_site.example.com/…` rejected with
`400 invalid_url: "url must include a host"`, while the same domain in ASCII form
(`xn--mller-kva.de`) worked: `java.net.URI.getHost()` is null for such hosts. The scenario is written
as a user bug report (symptoms only); diagnosing it was left to the agents.

**Decomposition.** `workflows/bugfix.yaml` enforces **reproduce first, then fix**:

```
requirements ─► impact ─► reproduce ─► fix ─► release
  (approve)    (approve)  [new tests    [full suite,   [entry: full suite]
                           fail, rest    tests          (approve)
                           pass]         untouchable]
```

The `reproduce` stage (a reproducer agent, test files only) must pass `regression_reproduces`: the
orchestrator clears old reports, runs the suite, and requires the tests to compile and run, at least
one new test to fail, and no other test to fail. The `fix` stage cannot write tests and must make the
whole suite pass.

**Orchestration, as it happened.**
1. The analyst turned the report into 8 requirements, including "Unicode and Punycode forms must not
   bypass the destination rules", and asked the open point: redirect as entered, or normalized? The
   owner: the redirect uses the ASCII host (a `Location` header must be ASCII), nothing else changes,
   and metadata keeps the URL exactly as entered. It also dropped its own first assumption ("whatever
   a browser accepts") in favour of fixing only the reported forms.
2. The impact analyst found the root cause and named the key risk: if the security check and the
   redirect interpreted a host differently, a spelling could bypass the rules. Plan: one conversion
   (UTS #46, as browsers do) feeding both. Approved.
3. The reproducer (OpenAI) added 12 tests to 3 existing classes. Policy paused on the edits to existing
   tests; the owner approved after seeing that one line changed (whitespace) and nothing was removed.
   **The gate confirmed 10 fail with the reported error** and all 138 existing tests pass; 2 guard
   tests (Punycode form, path encoding) already pass, so the fix cannot over-correct.
4. Fix (Claude Code session): a `DestinationUrls` helper reads the host from the authority, converts a
   non-ASCII host with ICU4J and returns that one form to both the destination check and the redirect;
   ASCII hosts take exactly the old path. Policy paused on the new dependency (ICU4J 77.1; Java's
   built-in IDNA2003 converter would send `faß.de` to `fass.de`, a different domain); the owner
   approved. 150 tests pass; conformance holds.
5. **Release failed once:** the agent failed "API definition valid" although the conformance gate had
   passed, and failed design and documentation items this workflow has no stages for. It could not
   see gate results. After a fix (`gate_context`), a re-plan recorded with its reason re-ran release
   only; 10 items, none failing; the owner signed off.

**Validation.** Full-width `ｌｏｃａｌｈｏｓｔ` and `１２７.０.０.１` are refused as prohibited (the check runs
on the converted host). Checking the host as written, or redirecting to the URL as entered, each fail
3 regression tests. Run metrics: 83% stage success, 1 incident, MTTR 8.8 min, 1 re-plan.

**Accepted at sign-off, recorded as release-agent weaknesses:** version 1.2.0 where 1.1.1 is arguably
right (its first attempt chose 1.1.1); "documentation updated: pass" on weak grounds (the docs never
described host rules, so none went stale).

## 6. Auto-selected bug fix: some errors were HTML, not JSON

**Found by a gate, routed by the selector.** The new release smoke gate starts the packaged jar and
calls it over HTTP; its first probe found that a malformed percent-escape (`GET /api/links/%ZZ`) got
Tomcat's HTML error page instead of the JSON error schema: the server rejects such a request before
the application sees it, so no in-process test could. `scenarios/bugfix-html-error.md` reports it.

**Orchestration, as it happened** (`live-bugfix-2`).
1. `orch run auto`: rules excluded `skeleton` (the codebase exists); the selector proposed **bugfix**
   (high confidence, runner-up brownfield); the owner confirmed. The selection is in `RUN_STARTED`.
2. The analyst's spec (3 functional requirements, none non-functional) **failed the bug-fix workflow's
   first gate**, which required non-functional requirements: a rule copied from the lifecycle. The rule
   was corrected (`6ce4920`) and the run re-planned from requirements, the reason recorded.
3. Impact: the right mechanism (Tomcat's error-report valve), limited to `/api/**` by inspecting the
   path, which it named as its own top risk. The owner's **change request** removed the path check:
   every route is documented API, so `/%ZZ` must be JSON too. Revision approved.
4. Reproduce (OpenAI): the model worked out that the bug needs **raw HTTP to a real socket** (clients
   refuse to send `%ZZ`); policy paused on the edit to `ManagementServerTest`; 4 new tests failed with
   `text/html` where JSON was expected, every other test passed.
5. Fix: the host's error-report valve replaced with one writing `ErrorBodies` JSON, status and headers
   kept (405 still has `Allow`). The **coverage** gate (91.7%; the valve 83.3%) and, at release, the
   **real-server smoke** gate passed in a live run for the first time. Release 1.2.1 passed its
   checklist first time (it now sees gate results) and was signed off.

**Found and fixed after it:** MTTR counted the wait for an approval as repair time (8.7 h reported,
37 s real); `orch run auto` on a repository refused to start because its own recording made the tree
dirty; the smoke steps now include the malformed escapes. Replay reproduces the failure and re-plan too.

## 7. Auto-selected test improvement: race tests that prove their race

**The weakness.** `ClickDeletionRaceTest` held a lock and slept 300 ms, trusting that the second
operation started meanwhile; on a slow machine it could pass without exercising the race.
`scenarios/harden-race-tests.md` asks that every race prove its interleaving, test code only.

**Orchestration, as it happened** (`live-brownfield-2`).
1. `orch run auto`: the selector proposed **brownfield** (runner-up bugfix, since a test that cannot fail
   is arguably a test defect); confirmed. It started despite its recording being untracked (the fix).
2. The analyst made it strict: "observing that it has not completed is not sufficient proof"; failures
   must fail within a bound, never hang or pass. The impact analyst chose H2's own lock view
   (`INFORMATION_SCHEMA.SESSIONS.BLOCKER_ID`) and rollback of any unproven interleaving.
3. Implement proposed **no change** (test-only), and the compile gate confirmed production unchanged.
4. Tester (Claude Code session): a probe showed H2 reports the blocked statement **with its bound
   parameter**, so each race now proves the second operation is BLOCKED by the first one's session on
   **that link's row**. The first attempt's diagnostic exposed a matcher bug (H2 prints `BIGINT` ids as
   `CAST(n AS BIGINT)`), fixed before submitting. 3 guard tests show the proof can fail. All 6 methods
   and all 11 outcome assertions kept (checked mechanically); 6 fixed sleeps removed.

**Validation.** 9/9 race tests pass on three consecutive runs; mutation checks: releasing without
proof fails 3 tests, accepting any blocked session fails 1, committing an unproven interleaving fails
2. 158 tests in all.

---

## Supporting runs

| Run | Purpose |
|---|---|
| `live-greenfield-1` | the first greenfield attempt, failed at the ambiguity gate before clarification existed; kept so the success rate is honest (8 of 9 runs) |
| `demo-fault-injection` | stub agents with two injected faults: a compile failure (rolled back and retried) and a refusal (fallback agent), so retries, rollback and MTTR appear in a real run |
