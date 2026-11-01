# Final engineering summary

## What was built

1. **A governed agentic SDLC orchestrator** (`orchestrator/`, Python, ~4.3k lines, 171 tests). It takes
   a requirement through an explicit dependency graph of stages (requirements, impact analysis,
   implementation, test planning, testing), with entry/exit gates, parallel paths and joins, a policy
   engine, human approvals, clarifications and change requests, bounded retries, rollback, fallback,
   safe-stop, resume, lineage-based re-planning, a hash-chained audit log and reliability metrics.
2. **A URL shortener** (`url-shortener/`, Java 17 / Spring Boot 3.4, 120 tests), produced by the
   orchestrator in three runs: built from a requirement, extended with click analytics, then hardened
   from a deliberately vague request.

Everything is reproducible offline: `scripts/replay-scenarios.sh` replays all three scenarios from their
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

## How the core requirements are met

| Requirement | Where it is met | Evidence |
|---|---|---|
| 1. Requirement understanding | analyst agent; ambiguity gate; clarification checkpoints | 27 human answers across the runs; a contradiction caught; "make it more reliable" → 23 requirements |
| 2. Task decomposition | declarative stage DAGs with dependencies, scopes, gates (`workflows/`) | 4-, 5- and 5-stage workflows, parallel branches with a join |
| 3. Codebase reasoning (brownfield) | impact-analyst stage reading the code; plan approved before changes | impacted files, API/data changes, races and risks named before coding |
| 4. Workflow orchestration | engine with explicit DAG, entry/exit gates, parallel paths, context and lineage, approvals, retries, fallback, rollback, safe-stop, policy, audit, metrics, re-planning | [ARCHITECTURE.md](ARCHITECTURE.md); `test_scheduler`, `test_resilience`, `test_replan` |
| 5. Engineering output | layered service, Flyway migrations, API contracts defined in the approved specs and impact analyses, 120 tests | `url-shortener/`, `runs/samples/*/artifacts/` |
| 6. Validation and risk control | gates the orchestrator runs, policy tiers, test-count floor, protected tests, mutation checks | [TESTING.md](TESTING.md), [RISKS.md](RISKS.md) |
| 7. Controlled autonomy | read/write scopes, propose-only agents, bounded rounds/retries/revisions, budgets, human checkpoints | every live run: 10 approvals, 27 answers, all recorded under the person's identity |
| 8. Final summary | this document | |

## Results (from `orch report --all`, `runs/samples/REPORT.md`)

| Metric | Value |
|---|---|
| Runs succeeded | 4 of 5 (80%) — the failure is the first greenfield attempt, before clarification existed |
| Stage success rate (executed stages) | 82% |
| Failure retries / rollbacks | 1 / 1 (the fault-injection demo; the live runs had none) |
| Incidents (unrecovered) / MTTR | 4 (1) / 18 min |
| Human decisions | 10 approvals (1 rejected with a change request), 27 answers in 8 rounds |
| Active work vs waiting for humans | 48.5 min vs 37.4 h |
| Live LLM calls / output tokens | 17 / 162,314 (cost not computed: no pricing configured for the OpenAI model) |

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
  (37 hours of the runs' wall-clock time was waiting for a person, by design).
- Maven tests are the definition of "works"; humans review what tests cannot judge.
- No compliance regime applies; privacy rules were set by the product owner per scenario.

## Limitations and honest notes

- **Who produced what.** The analyst, impact analyst and test planner ran on OpenAI (`gpt-6-luna`); the
  coder and tester stages were served by a Claude Code session through the same prompts, context,
  schemas, policy and gates, recorded as `claude-code-session`. That assistant verified its code before
  answering, so the live runs never failed a gate; retries and rollback are demonstrated by tests and
  by `demo-fault-injection`.
- **Gaps the runs exposed were fixed mid-run** (clarification, change requests, revision rounds), each as
  a reviewed, tested commit, and recorded in the audit log (`workflow_changed`). The ambiguous run was
  resumed twice for this; its MTTR of 54 minutes includes that work.
- **Mistakes caught along the way** are listed in [RISKS.md](RISKS.md#lessons-from-building-it-things-that-went-wrong-and-were-fixed),
  including a commit message that says five approvals where the metrics show four.
- Further limitations: [RISKS.md](RISKS.md#known-limitations).

## What I would do next

1. A web approval UI (the `Approver` interface is the seam) and notifications when a run waits.
2. Real security tooling as gates: SAST, dependency CVE scanning, secret scanning.
3. An eval set for agent output quality, and per-agent model choice tuned against it.
4. Event log in a database with an external anchor for the hash chain; a queue-backed scheduler.
5. Production datastore and shared rate-limit state for the service.
