# Testing approach

Three layers, plus checks on the tests themselves.

| Layer | What | Count | Run |
|---|---|---|---|
| Orchestrator | unit and integration tests of the engine, governance and observability | 204 | `.venv/bin/pytest` |
| Generated service | unit, MockMvc integration, real-listener, concurrency and restart tests | 150 (23 classes) | `cd url-shortener && mvn test` |
| End to end | the five scenarios replayed offline through the real CLI, gates and Maven | 5 runs | `scripts/replay-scenarios.sh` |

## Principles

- **Agents propose, gates verify.** No test or gate trusts an agent's claim: the orchestrator runs Maven
  itself, the test-count floor checks how many tests ran, and policy inspects the actual change set.
- **Tests are checked too (mutation checks).** For every safety-critical mechanism, the mechanism was
  deliberately broken and the tests were confirmed to fail, so a green test is evidence, not luck.
- **Deterministic by construction.** Controllable clocks (`MutableClock`), stubbed DNS
  (`StubHostResolver`), scripted LLMs and approvers, isolated in-memory databases, per-test client IPs
  for shared rate limiters, ephemeral ports.
- **Real where it matters.** Real Maven builds as gates, real sockets for network bindings, a real V1
  database upgraded in place, a real application restart.

## Orchestrator (204 tests)

| File | Covers |
|---|---|
| `test_dag_and_state.py` (11) | workflow validation (cycles, unknown/duplicate stages), retry bounds, legal and illegal transitions |
| `test_events.py` (5) | hash chain: verification, edit and deletion detection, continuation, state replay |
| `test_scheduler.py` (13) | fork runs in parallel, join waits, `max_parallel`, retries with feedback, exhaustion skips downstream, approvals after gates, scope breaches not retried, entry gates, preflight, lineage |
| `test_policy.py` (31) | every rule positive and negative, only added lines scanned, strictest action wins, configuration, policy hash |
| `test_governance.py` (9) | policy inside the engine: rejected change never written, approval before apply, all-or-nothing change sets, symlink escape |
| `test_llm.py` (12) | Anthropic request shape, refusal / truncation / auth handling, cost, cassettes, strict schemas |
| `test_providers.py` (14) | OpenAI adapter, cached-token normalization, registry and per-agent routing, config, pluggability |
| `test_llm_agents.py` (15) | agents through the real engine: feedback loop, read scope, oversized context, telemetry, impact plan reaching coder and planner, approved design reaching every downstream agent, opt-in downstream write scopes, regression tests reaching only the bug-fix coder, opt-in gate results for release |
| `test_hybrid.py` (7) | session backend, routing, file approvals, cost safe-stop, hybrid run with a real build |
| `test_clarification.py` (10) | pause and readable answers file, incomplete answers refused, non-human never answers, bounded rounds, seeding recorded decisions |
| `test_resilience.py` (22) | rollback, conflict-safe revert, fallback, stop and time budget, resume, tamper refusal, git ownership, content-bound approvals, change requests, extra round per revision, workflow hash |
| `test_replan.py` (11) | lineage reuse vs re-run, branch precision, approvals on reuse vs new content, requirement change detection, re-planning a failed stage is recorded with its reason |
| `test_selection.py` (9) | catalog and codebase eligibility, rule proposal without a model call, schema limited to eligible names, rejection with a comment followed, rejection without one starts nothing, selection in `RUN_STARTED` and the report, the recorded eval replayed (9 of 9), `orch run auto` end to end |
| `test_bugfix.py` (6) | real Maven: a new failing test reproduces; a passing one does not; a failing existing test is not a reproduction; a test that does not compile is not one even with stale failing reports; the fix cannot write tests |
| `test_lifecycle.py` (10) | OpenAPI validation, two-way conformance against real Spring mappings (class prefixes, regex path variables, the error controller), docs coverage, release checklist, an entry gate blocking implementation without a valid design, the 8-stage lifecycle end to end with real Maven |
| `test_metrics.py` (10) | every metric against runs with known faults; human-wait overlap; resume de-duplication; tampered-log refusal |
| `test_envfile.py` (4) · `test_skeleton_e2e.py` (5) | credentials never printed; skeleton through real gates; Maven gate fails a failing test and enforces the test-count floor |

## Generated service (150 tests)

| Area | Classes |
|---|---|
| Create, aliases, validation | `LinkCreationTest`, `DestinationPolicyTest` (25 prohibited/allowed destinations incl. IPv6, DNS fail-closed; internationalized and underscore hosts, checked in ASCII form), `LinkServiceTest` |
| Redirect, expiry, metadata, deletion | `LinkLifecycleTest` (UTC expiry boundaries on a controlled clock, tombstones, token hashing) |
| Expiry changes | `LinkExpiryUpdateTest` (set, remove, missing vs `null`, malformed, token, never revive, non-future, deleted, far future, the OpenAPI contract); PATCH in `ManagementTokenRateLimitTest`; expiry change vs click recording and vs deletion in `ClickDeletionRaceTest` |
| Analytics | `LinkStatsTest` (30-day UTC window, privacy probe), `ClickDeletionRaceTest`, `ClickFailureIsolationTest` |
| Hardening | `ErrorContractAndHeadersTest`, `ManagementTokenRateLimitTest`, `BodyLimitTest`, `RateLimitTest` |
| Reliability and operations | `RedirectOutageAndMetricsTest`, `ManagementServerTest` (real sockets; unreachable from a non-loopback address), `HealthTest`, `RedirectLatencyTest` (p99 ~2.5 ms against < 50 ms) |
| Persistence | `PersistenceRestartTest`, `ClickPersistenceAndUpgradeTest` (a real V1 database upgraded in place) |
| No outbound fetch | `NoOutboundFetchTest` |

Each test method carries its test-plan id (`TC_FR1_01_…`), so results trace back to requirements and
the plan the test planner produced (`runs/samples/<run>/artifacts/test_plan.v1.json`).

## Mutation checks performed

| Mechanism broken on purpose | Result |
|---|---|
| Policy engine allows everything | 22 policy/governance tests fail |
| Per-attempt rollback disabled | resilience tests fail |
| Approvals not bound to content | resilience tests fail |
| Resume integrity checks skipped | resilience tests fail |
| Fallback disabled | resilience tests fail |
| Change requests dropped from feedback | change-request tests fail |
| Re-planning ignores lineage | re-plan tests fail |
| Clarifications counted as failures; parallel human waits summed | metrics tests fail |
| Service: row locks removed (click vs delete) | both race tests fail |
| Service: failed-token throttle disabled; one security header dropped | 3 tests fail each |
| Service: expired links revivable; missing `expiresAt` read as remove; PATCH outside the token throttle; expiry change without the row lock | a new test fails for each |
| Service: destination check on the host as written; redirect to the URL as entered | 3 regression tests fail each |
| Orchestrator: entry gates ignored | the entry-gate tests fail |
| Orchestrator: old Surefire reports not cleared before a reproduction | the stale-report test fails |
| Orchestrator: codebase eligibility ignored; reviewer's comment dropped | 5 and 1 selection tests fail |
| Orchestrator: re-plans of failed stages not recorded (the bug found in the lifecycle run) | the new re-plan test fails |

## End-to-end evidence

- Live runs: `runs/samples/live-greenfield-2`, `live-brownfield-1`, `live-ambiguous-1`, `live-lifecycle-1`, `live-bugfix-1` (plus the failed
  first attempt `live-greenfield-1` and `demo-fault-injection`), each with a verifying event log and a
  report.
- Offline replays reproduce the committed code exactly: `scripts/replay-scenarios.sh`.
- Real-server smoke tests during development (recorded in the conversation, not automated): upgrade
  of a copy of a real v1 database, every HTTP flow with curl, the management port probed from the LAN
  address.

## Not covered

- No load or soak testing; the latency figure is an indicative in-process check.
- No real database outage: the 503 path is tested with injected store failures.
- The policy rules are pattern-based; there is no SAST or dependency vulnerability scanner in the loop.
- LLM output quality is measured beyond the gates only for the workflow selector: `orch eval-selector`
  (`scenarios/selection/eval.yaml`, 9 cases with every defensible answer accepted; recorded live 9 of 9,
  replayed as a test). The cases and the workflows' `use_when` texts have the same author, so this is a
  regression check, not a benchmark.
