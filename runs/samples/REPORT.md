# Delivery metrics across runs

| Metric | Value |
|---|---|
| Runs (succeeded) | 8 (88%) |
| Stage success rate | 84% |
| Failure retries | 1 |
| Clarification rounds (incl. replays) / change requests | 19 / 5 |
| Rollbacks | 3 |
| Incidents (unrecovered) | 9 (1) |
| MTTR | 5.2 min |
| Human decisions | 27 approvals (4 rejected), 31 answers in 11 rounds |
| Active time / waiting for humans | 1.4 h / 48.6 h |
| Live LLM calls / output tokens | 39 / 307,877 |

| Run | Workflow | Status | Processes | Stage success | Failure retries | Rollbacks | Incidents | MTTR | Active | Human wait | End to end |
|---|---|---|---|---|---|---|---|---|---|---|---|
| `demo-fault-injection` | fault-demo | SUCCEEDED | 1 | 100% | 1 | 1 | 2 | 2.7 s | 6.8 s | 0.0 s | 6.8 s |
| `live-ambiguous-1` | brownfield | SUCCEEDED | 4 | 62% | 0 | 0 | 3 | 11.5 min | 20.6 min | 1.8 h | 2.7 h |
| `live-brownfield-1` | brownfield | SUCCEEDED | 1 | 100% | 0 | 0 | 0 | – | 11.8 min | 44.4 min | 56.2 min |
| `live-bugfix-1` | bugfix | SUCCEEDED | 2 | 83% | 0 | 1 | 1 | 4.7 min | 11.7 min | 17.6 min | 32.9 min |
| `live-bugfix-2` | bugfix | SUCCEEDED | 2 | 83% | 0 | 0 | 1 | 36.7 s | 8.4 min | 9.3 h | 9.4 h |
| `live-greenfield-1` | skeleton | FAILED | 1 | 0% | 0 | 0 | 1 | – | 50.0 s | 0.0 s | 50.0 s |
| `live-greenfield-2` | skeleton | SUCCEEDED | 1 | 100% | 0 | 0 | 0 | – | 15.2 min | 34.8 h | 35.1 h |
| `live-lifecycle-1` | lifecycle | SUCCEEDED | 2 | 89% | 0 | 1 | 1 | 2.0 min | 17.7 min | 1.7 h | 2.0 h |

---

_Computed from the hash-chained event log only (`orch verify-audit` checks it). Retries are split by cause; clarification rounds and change requests are not failures. An incident opens at a stage's first failure (including a switch to the fallback agent) and closes when its work next passes its gates (a later wait for a sign-off is human wait); MTTR includes time a run sat stopped before a person fixed it. Stage success rate counts executed stages (SKIPPED ones never ran). Human decisions replayed by a resume are counted once._

