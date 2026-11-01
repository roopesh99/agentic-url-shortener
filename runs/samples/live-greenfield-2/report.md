# Run report: `live-greenfield-2`

Workflow `skeleton` · **SUCCEEDED** · 1 process(es) · 2026-10-30 07:41 → 2026-10-31 18:47 UTC

## Reliability

| Metric | Value |
|---|---|
| Stage success rate | 100% (4 succeeded) |
| Failure retries | 0 |
| Clarification rounds / change requests / fallbacks | 2 / 0 / 0 |
| Rollbacks (reverted change sets / stages ended ROLLED_BACK) | 0 / 0 |
| Incidents (unrecovered) | 0 (0) |
| MTTR | – |
| Gate checks passed / failed | 8 / 2 |
| Policy evaluations by risk tier | low 5, high 1 |
| Re-plans | 0 |

## Latency

| | Time |
|---|---|
| End to end (wall clock) | 35.1 h |
| Active (agents, gates, orchestration) | 15.2 min |
| Waiting for humans | 34.8 h |
| Stopped between processes | 0.0 s |

| Stage | Attempts | Active | of which agent | of which gates | Waiting for humans | Outcomes |
|---|---|---|---|---|---|---|
| `requirements` | 3 | 4.0 min | 4.0 min | 0.0 s | 34.5 h | SUCCEEDED |
| `implement` | 1 | 5.4 min | 5.4 min | 2.1 s | 23.0 min | SUCCEEDED |
| `test_plan` | 1 | 33.3 s | 33.3 s | 0.0 s | 0.0 s | SUCCEEDED |
| `test` | 1 | 5.8 min | 5.6 min | 8.6 s | 0.0 s | SUCCEEDED |

## Human oversight

2 approval decision(s) (2 approved, 0 rejected, 0 with a change request), 2 clarification round(s) answering 7 question(s); 0 recorded decision(s) reused by resumes.

| Kind | Stage | Decision | By | Waited |
|---|---|---|---|---|
| workflow approval | `requirements` | approved | roopeshkotte | 11.3 min |
| policy approval | `implement` | approved | roopeshkotte | 23.0 min |
| clarification round 1 | `requirements` | 6 answer(s) | roopeshkotte | 3.6 min |
| clarification round 2 | `requirements` | 1 answer(s) | roopeshkotte | 34.2 h |

## LLM usage

6 call(s): 1 cassette, 3 live, 2 session. Live: 8,021 input / 32,140 output tokens, 4.5 min in calls, cost $0.00 (3 call(s) on an unpriced backend).

## Timeline

```mermaid
gantt
    title live-greenfield-2
    dateFormat YYYY-MM-DDTHH:mm:ss
    axisFormat %H:%M
    section requirements
    active :2026-10-30T07:41:45, 2026-10-30T07:41:46
    waiting for human :crit, 2026-10-30T07:41:45, 2026-10-30T07:45:24
    active :2026-10-30T07:45:23, 2026-10-30T07:47:34
    waiting for human :crit, 2026-10-30T07:47:33, 2026-10-31T17:59:44
    active :2026-10-31T17:59:43, 2026-10-31T18:01:33
    waiting for human :crit, 2026-10-31T18:01:32, 2026-10-31T18:12:53
    section implement
    active :2026-10-31T18:12:52, 2026-10-31T18:18:16
    waiting for human :crit, 2026-10-31T18:18:15, 2026-10-31T18:41:15
    active :2026-10-31T18:41:14, 2026-10-31T18:41:17
    section test_plan
    active :2026-10-31T18:12:52, 2026-10-31T18:13:27
    section test
    active :2026-10-31T18:41:16, 2026-10-31T18:47:02
```

---

_Computed from the hash-chained event log only (`orch verify-audit` checks it). Retries are split by cause; clarification rounds and change requests are not failures. An incident opens at a stage's first failure (including a switch to the fallback agent) and closes at its next success; MTTR includes time a run sat stopped before a person fixed it. Stage success rate counts executed stages (SKIPPED ones never ran). Human decisions replayed by a resume are counted once._
