# Risks, trade-offs and limitations

## Failure scenarios and how the system responds

| Scenario | Response | Evidence |
|---|---|---|
| Agent output fails to compile or tests fail | Change reverted, retried with the gate evidence (bounded), then the fallback agent, then `FAILED`/`ROLLED_BACK` | `test_resilience.py`, `demo-fault-injection` |
| Agent writes a secret, unsafe code, logs personal data | Policy `reject`: change never written, retried with the violation | `test_governance.py` |
| Agent adds a dependency, a migration, edits config or an existing test | Policy `require_approval`: a person approves before it is applied | brownfield and ambiguous runs |
| Agent writes outside its scope or escapes the workspace | Stage fails immediately, no retry | `test_scheduler.py`, `test_governance.py` |
| Requirement is vague or contradictory | Ambiguity gate stops the stage; clarification rounds; bounded | ambiguous run (16 answers, a contradiction caught) |
| Reviewer disagrees with the result | Reject, or reject with a change request (bounded revisions) | ambiguous run |
| Model refuses | Fallback agent, if declared; otherwise the stage fails without spending retries | `test_llm.py`, `demo-fault-injection` |
| LLM API down, rate-limited, slow | SDK retries; then a retryable agent error, bounded | `test_llm.py`, `test_providers.py` |
| Cost or time runs away | `--max-cost-usd` / `--max-minutes` safe-stop; `orch stop` | `test_hybrid.py`, `test_resilience.py` |
| Process crashes or is stopped mid-run | `orch resume` from the log; interrupted stage's uncommitted files discarded; recorded calls and decisions reused | ambiguous run (resumed twice) |
| Audit log or artifact edited | Resume, report and verify refuse it | `test_events.py`, `test_resilience.py`, `test_metrics.py` |
| Upstream output changes after downstream finished | `orch replan` / automatic on resume; lineage decides reuse or re-run | `test_replan.py` |
| Code drifts from the approved API definition | Conformance gate fails the implementation (documented but not built, or built but not documented) | `test_lifecycle.py`, `live-lifecycle-1` |
| Release prepared from a stale or broken build | Release entry gate re-runs the full suite; a failing checklist item blocks the release | `live-lifecycle-1` (blocked once, rolled back) |

## Trade-offs

| Chose | Over | Because | Cost |
|---|---|---|---|
| A custom engine | LangGraph, Airflow, Temporal | governance must be visible and owned | single node; no distributed scheduling |
| One structured call per agent turn | agent loops with tools | every step governed and replayable | agents can't explore; context is pre-selected |
| Pattern-based policy | SAST, dependency scanners | fast, explainable, testable | misses semantic vulnerabilities |
| Bounded clarification rounds | unbounded dialogue | runs always terminate | a run can stop at the limit (it did twice) |
| File-based H2 | a server database | runs with one command | single node; not a production datastore |
| Synchronous click insert | async queue | durable, immediately visible, simple | a lock per link on redirects; lost clicks on failure (accepted) |
| Hybrid backends for cost | all agents on an API | about $0.20 vs ~$2 per run | coder/tester stages served by an assistant, not an API model |

## Known limitations

**Orchestrator**
- Single process and node; the event log is a local file; no external anchor for the hash chain.
- `orch stop` does not interrupt a model call or Maven build already in progress.
- Re-planning happens between processes, not while stages are in flight; a re-run does not delete files that only the previous version created.
- Policy rules are regex and allowlist based; no SAST, secret-scanning service or CVE scan.
- Gates verify what tests check: weak tests pass weak code (mitigated by the test-count floor, the protected-test rule and human review of the test plan).
- LLM nondeterminism: the analyst re-opened a question it had resolved earlier (handled, but it costs a round); output quality is not measured by an eval set.
- Prompt injection: requirement text and code reach prompts. Agents cannot write outside their scope or skip policy and gates, which contains the damage, but a malicious requirement could still steer what an agent proposes within its scope.
- The conformance gate compares methods and paths found by a static scan of Spring annotations, not request or response schemas; it would miss a route built some other way (e.g. functional routing).
- The release stage cannot bump the build version (`pom.xml` is outside its write scope); release 1.1.0 is recorded while the build says `1.0.0-SNAPSHOT`.
- `live-lifecycle-1`'s log records its release re-plan as a plain resume, without the reason (the bug was fixed afterwards; the log is append-only). The reason is in commit `5db4b29`.
- Costs for the OpenAI model are unknown in the reports (no pricing configured); token counts are exact.
- Runs started before resume support (`live-greenfield-1`, `-2`) cannot be resumed; `live-greenfield-2` predates content-bound decision ids and replays through its answers file.

**URL shortener**
- Single node: in-memory rate limiters and the management port are per instance.
- DNS re-pointing after creation is not re-checked (the service never fetches destinations).
- No authentication beyond management tokens; link-code probing is not rate-limited (accepted; observable via the 404 metric).
- The latency check is in-process (MockMvc), not a load test; a database outage is tested by injection.
- Lost clicks are possible when recording fails (owner decision: redirect reliability first).

## Lessons from building it (things that went wrong and were fixed)

- **Unanswerable questions had no path forward.** The first greenfield run stopped at the ambiguity gate with no way for a person to answer: added clarification checkpoints.
- **Rejection was only a veto.** A reviewer could not ask for a fix: added change requests.
- **Revisions could exhaust clarification rounds.** A change request raised a legitimate new question: one extra round per revision.
- **Mid-run workflow changes were invisible.** Added the workflow hash and `workflow_changed` on resume.
- **Metric definitions misled at first:** skipped stages dragged the success rate down (25% instead of 62.5%), replayed decisions were double-counted, fallbacks were not incidents. All fixed and tested.
- **Tests that could not fail.** One assertion ended in `or True`; another test's docstring contradicted its assertion; `*IT` test classes would have been skipped by Surefire. Each caught in review and fixed, and mutation checks were added for every safety mechanism.
- **The model drifted from an explicit instruction.** In the lifecycle run, asked to "keep the technical plan unchanged" and only move files, the impact analyst dropped two tests; a second change request restored them. Human review of plan revisions is not optional.
- **A prompt bug blocked a release.** The release prompt let the agent list its own review and the pending sign-off as failing items. The checklist gate did its job; the fix was the prompt.
- **A record is off by one.** The brownfield evidence commit message (`0f4090f`) says five approvals; the metrics show four (spec, impact plan, V2 migration, edits to two existing tests).
