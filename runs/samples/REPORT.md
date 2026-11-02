# Delivery metrics across runs

| Metric | Value |
|---|---|
| Runs (succeeded) | 6 (83%) |
| Stage success rate | 84% |
| Failure retries | 1 |
| Clarification rounds (incl. replays) / change requests | 18 / 4 |
| Rollbacks | 2 |
| Incidents (unrecovered) | 5 (1) |
| MTTR | 14.3 min |
| Human decisions | 17 approvals (3 rejected), 30 answers in 10 rounds |
| Active time / waiting for humans | 1.1 h / 39.0 h |
| Live LLM calls / output tokens | 28 / 239,026 |

| Run | Workflow | Status | Processes | Stage success | Failure retries | Rollbacks | Incidents | MTTR | Active | Human wait | End to end |
|---|---|---|---|---|---|---|---|---|---|---|---|
| `demo-fault-injection` | fault-demo | SUCCEEDED | 1 | 100% | 1 | 1 | 2 | 2.7 s | 6.8 s | 0.0 s | 6.8 s |
| `live-ambiguous-1` | brownfield | SUCCEEDED | 4 | 62% | 0 | 0 | 1 | 54.0 min | 20.6 min | 1.8 h | 2.7 h |
| `live-brownfield-1` | brownfield | SUCCEEDED | 1 | 100% | 0 | 0 | 0 | – | 11.8 min | 44.4 min | 56.2 min |
| `live-greenfield-1` | skeleton | FAILED | 1 | 0% | 0 | 0 | 1 | – | 50.0 s | 0.0 s | 50.0 s |
| `live-greenfield-2` | skeleton | SUCCEEDED | 1 | 100% | 0 | 0 | 0 | – | 15.2 min | 34.8 h | 35.1 h |
| `live-lifecycle-1` | lifecycle | SUCCEEDED | 2 | 89% | 0 | 1 | 1 | 3.0 min | 17.7 min | 1.7 h | 2.0 h |

---

_Computed from the hash-chained event log only (`orch verify-audit` checks it). Retries are split by cause; clarification rounds and change requests are not failures. An incident opens at a stage's first failure (including a switch to the fallback agent) and closes at its next success; MTTR includes time a run sat stopped before a person fixed it. Stage success rate counts executed stages (SKIPPED ones never ran). Human decisions replayed by a resume are counted once._

