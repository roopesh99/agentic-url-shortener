# Final engineering summary

## What was built

1. **A governed agentic SDLC orchestrator** (`orchestrator/`, Python, ~5.4k lines, 212 tests). It takes
   a requirement through an explicit dependency graph of stages covering the full lifecycle
   (requirements, impact analysis, API design, implementation, test planning, testing, documentation,
   release readiness) and a reproduce-then-fix path for bugs, with entry/exit gates, parallel paths and joins, a policy engine, human
   approvals, clarifications and change requests, bounded retries, rollback, fallback, safe-stop,
   resume, lineage-based re-planning, a hash-chained audit log and reliability metrics.
2. **A URL shortener** (`url-shortener/`, Java 17 / Spring Boot 3.4, 158 tests), produced by the
   orchestrator in seven runs: built from a requirement, extended with click analytics, hardened from a
   deliberately vague request, given owner-editable expiry through the full lifecycle (which also
   produced its OpenAPI definition, README, API reference, changelog and release records), fixed for
   two real bugs, each reproduced by a failing test before the fix, and given race tests that prove
   their race. The last two runs' workflows were chosen by `orch run auto`.

Everything is reproducible offline: `scripts/replay-scenarios.sh` replays all seven scenarios from their
recorded LLM exchanges and human decisions and checks that the generated code matches the committed
code exactly (it does).

## Plan and rationale

The work followed a walking skeleton, then layers, each committed separately (`git log --reverse`):

| Step | Added | Why in this order |
|---|---|---|
| 1 | Engine: DAG, state machine, event log, real Maven gate, approvals | prove the pipeline end to end on day one |
| 1.5 | Policy engine, propose-then-apply change sets | guardrails before giving LLMs autonomy |
| 2 | LLM agents, providers, cassettes, hybrid session backend | retire the biggest risk (real model output through the gates) early |
| Greenfield | clarification checkpoints (gap found by the first live run) | the run exposed it |
| 3 | rollback, fallback, safe-stop, resume, git checkpoints, content-bound decisions | reliability before more scope |
| Brownfield | impact analysis stage, regression guards | codebase reasoning |
| Ambiguous | change requests, extra round per revision, workflow hash (gaps found by the run) | the run exposed them |
| 5 | lineage-based re-planning | the last orchestration capability |
| 6 | metrics and reports from the log | measure what was built |
| 7 | documentation, offline replay of the scenarios | deliverables |
| Release gates | JaCoCo coverage (overall and per changed file), a real-server smoke test of the packaged jar; then two `orch run auto` runs, and fixes they exposed | the original plan's coverage gate had never been built; tests ran only in-process |
| Selection | `orch run auto`: rule-based eligibility, selector agent, human confirmation; `orch eval-selector` | the audit found the workflow was always named by a person |
| Bug fix | reproduce-then-fix workflow, `regression_reproduces` gate, reproducer agent; release sees gate results | the audit found bug fixes in scope but undemonstrated |
| Lifecycle | design, documentation and release stages; OpenAPI, conformance, docs-coverage and checklist gates; entry gates in use; fixes the run exposed | an audit against the assignment found the lifecycle stages missing |

## How the core requirements are met

| Requirement | Where it is met | Evidence |
|---|---|---|
| 1. Requirement understanding | analyst agent; ambiguity gate; clarification checkpoints | 27 human answers across the runs; a contradiction caught; "make it more reliable" → 23 requirements |
| 2. Task decomposition | `orch run auto` proposes the workflow (stage graph) from the requirement and the codebase, a person confirms; declarative stage DAGs with dependencies, scopes, gates (`workflows/`); work broken down further inside stages (impact plan: files, risks, tests; test plan: cases traced to requirements) | 4-, 5-, 5- and 8-stage workflows, two fork/join points in the lifecycle; selection eval 9 of 9 |
| 3. Codebase reasoning (brownfield) | impact-analyst stage reading the code; plan approved before changes; bug fixes reproduced before they are fixed | impacted files, API/data changes, races and risks named before coding; a real bug's root cause found from a user report |
| 4. Workflow orchestration | engine with explicit DAG, entry/exit gates, parallel paths, context and lineage, approvals, retries, fallback, rollback, safe-stop, policy, audit, metrics, re-planning; the lifecycle workflow covers requirements → design → implementation → testing → documentation → release readiness | [ARCHITECTURE.md](ARCHITECTURE.md); `test_scheduler`, `test_resilience`, `test_replan`, `test_lifecycle`; `live-lifecycle-1` |
| 5. Engineering output | layered service; Flyway migrations; an OpenAPI 3.0.3 definition of every endpoint, checked against the code both ways; README and API reference; changelog; 158 tests | `url-shortener/`, `url-shortener/openapi.yaml`, `url-shortener/docs/` |
| 6. Validation and risk control | gates the orchestrator runs, policy tiers, test-count floor, protected tests, a failing regression test required before a fix, coverage of changed files, a smoke test of the packaged service, mutation checks | [TESTING.md](TESTING.md), [RISKS.md](RISKS.md) |
| 7. Controlled autonomy | read/write scopes, propose-only agents, bounded rounds/retries/revisions, budgets, human checkpoints | every live run: 30 approval decisions, 31 answers, all recorded under the person's identity |
| 8. Final summary | this document | |

## Results (from `orch report --all`, `runs/samples/REPORT.md`)

| Metric | Value |
|---|---|
| Runs succeeded | 8 of 9 (89%) — the failure is the first greenfield attempt, before clarification existed |
| Stage success rate (executed stages) | 85% |
| Failure retries / rollbacks | 1 / 3 (the fault-injection demo; the lifecycle and bug-fix runs' release stages, each blocked once by its checklist gate and rolled back) |
| Incidents (unrecovered) / MTTR | 9 (1) / 5.2 min (an incident closes when the work next passes its gates) |
| Human decisions | 30 approval decisions (4 rejected, all with a comment), 31 answers in 11 rounds |
| Active work vs waiting for humans | 1.6 h vs 48.8 h |
| Live LLM calls / output tokens | 42 / 324,336 (cost not computed: no pricing configured for the OpenAI model) |

Per scenario: [SCENARIOS.md](SCENARIOS.md).

## Artifacts

| What | Where |
|---|---|
| Architecture, decisions, risks, setup, testing, scenarios | `docs/` |
| Orchestrator and its tests | `orchestrator/` |
| Workflows, policy, LLM backend configs | `workflows/`, `policies/`, `config/` |
| Scenario inputs and the reviewed human answers | `scenarios/*.md`, `scenarios/*.answers.yaml` |
| Recorded LLM exchanges (offline replay) | `scenarios/cassettes/` |
| Run evidence: audit logs, artifacts, approvals, reports | `runs/samples/<run>/`, `runs/samples/REPORT.md` |
| The generated service | `url-shortener/` |
| One-command reproduction | `scripts/replay-scenarios.sh` |

## Assumptions

- A single node and a local event log are acceptable for a prototype; the event-sourced design is the
  path to a distributed version.
- The product owner is available for decisions; the system waits for them rather than guessing
  (39 hours of the runs' wall-clock time was waiting for a person, by design).
- Maven tests are the definition of "works"; humans review what tests cannot judge.
- No compliance regime applies; privacy rules were set by the product owner per scenario.

## Limitations and honest notes

- **Scope not run live: a refactor.** The assignment's brownfield scope lists enhancements, refactors and
  bug fixes. Enhancements (3 runs) and bug fixes (2 runs) ran live; a behaviour-preserving refactor was
  only shown in workflow selection (`scenarios/selection/refactor-link-service.md`, routed to brownfield
  in the eval). The brownfield workflow would govern it with the full existing suite as its guard, but
  no refactor run is recorded.
- **Who produced what.** The analyst, impact analyst and test planner ran on OpenAI (`gpt-6-luna`); the
  coder and tester stages were served by a Claude Code session through the same prompts, context,
  schemas, policy and gates, recorded as `claude-code-session`. That assistant verified its code before
  answering, so the coder and tester stages never failed a gate. The architect, writer and release
  agents ran on OpenAI; the release agent failed once in each of the last two runs, both times
  through a design gap of mine (a prompt bug; no view of gate results), and those are the live runs'
  only rollbacks. The bug-fix run's regression tests were written by OpenAI. Retries and fallback are demonstrated by tests and by `demo-fault-injection`.
- **Gaps the runs exposed were fixed mid-run** (clarification, change requests, revision rounds), each as
  a reviewed, tested commit, and recorded in the audit log (`workflow_changed`). The ambiguous run was
  resumed twice for this; its MTTR of 54 minutes includes that work.
- **The lifecycle run exposed three more gaps**, fixed after the run (`cf2556a`): a re-plan of a failed
  stage was logged as a plain resume, so that run's log lacks the re-plan reason; the release prompt
  bug; and the impact analyst could not see where later stages write. Two change requests were needed
  on its impact plan, one because the model dropped tests it was told to keep.
- **The bug-fix run exposed one more gap**, fixed mid-run (`1084e53`): the release agent judged
  readiness from agents' summaries, not the orchestrator's gate results, and its checklist assumed
  the full lifecycle. Two of its judgements were accepted at sign-off though weak: version 1.2.0
  (1.1.1 is arguably right) and "documentation updated" (no docs needed changing, but it did not know).
- **The last two runs exposed five more gaps, all fixed:** a bug-fix spec rule copied from the lifecycle;
  MTTR counting approval waits as repair time; `orch run auto` blocked by its own recording; the Maven
  gate counting stale test reports (a deleted test class still met the floor); a compile step reporting
  test counts it never ran. The coverage gate's first run also flagged its own false positive (a
  bootstrap `main` class), now an explicit exclude.
- **Mistakes caught along the way** are listed in [RISKS.md](RISKS.md#lessons-from-building-it-things-that-went-wrong-and-were-fixed),
  including a commit message that says five approvals where the metrics show four.
- Further limitations: [RISKS.md](RISKS.md#known-limitations).

## What I would do next

1. A web approval UI (the `Approver` interface is the seam) and notifications when a run waits.
2. Real security tooling as gates: SAST, dependency CVE scanning, secret scanning.
3. Evals for every agent's output quality (today only the selector has one, 9 cases written by me), and per-agent model choice tuned against them.
4. Event log in a database with an external anchor for the hash chain; a queue-backed scheduler.
5. Production datastore and shared rate-limit state for the service.
6. Let the release stage bump the build version (today `pom.xml` stays `1.0.0-SNAPSHOT`), and compose
   workflows from stage fragments instead of choosing among fixed ones.
