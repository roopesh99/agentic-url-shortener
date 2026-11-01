# Agentic URL Shortener

A governed agentic SDLC orchestrator (Python) that turns a requirement into a
reviewed, tested URL shortener service (Java 17 / Spring Boot).

> Status: **Step 6 — metrics and reports.** Engine, gates, approvals, clarifications,
> change requests, policy guardrails, audit log, LLM agents (Anthropic, OpenAI,
> assistant session), rollback, fallback, safe-stop, resume and lineage-based
> re-planning are real. All three scenarios (greenfield, brownfield, ambiguous)
> have run; their output is `url-shortener/` and their evidence `runs/samples/`.

## Setup

Requires Python 3.11+, JDK 17, Maven 3.8+.

```bash
python3 -m venv .venv
.venv/bin/pip install -e '.[dev]'            # dev: tests + both provider SDKs
# or only what you use:  pip install -e '.[openai]'   /   pip install -e '.[anthropic]'

cp .env.example .env && chmod 600 .env       # then fill in your key(s); .env is git-ignored
```

`orch` loads `.env` at startup (override with `--env-file`). Variables already
set in the shell take precedence; only variable *names* are ever printed.

## Run

```bash
# interactive: you approve the normalized requirements before any code is written
.venv/bin/orch run workflows/skeleton.yaml --requirement scenarios/greenfield.md --workspace ./out

# non-interactive (recorded in the audit log as a non-human approver)
.venv/bin/orch run workflows/skeleton.yaml --requirement scenarios/greenfield.md --workspace ./out --auto-approve

# LLM agents: which provider serves which agent is set in config/llm.*.yaml
export OPENAI_API_KEY=...  OPENAI_MODEL=...
.venv/bin/orch run workflows/skeleton.yaml --requirement scenarios/greenfield.md --workspace ./out \
    --agents llm --llm record --llm-config config/llm.openai-hybrid.yaml --approvals file

# Or all on Claude (ANTHROPIC_API_KEY or `ant auth login`):
.venv/bin/orch run workflows/skeleton.yaml --requirement scenarios/greenfield.md --workspace ./out \
    --agents llm --llm record     # live calls, saved as cassettes under scenarios/cassettes/
.venv/bin/orch run workflows/skeleton.yaml --requirement scenarios/greenfield.md --workspace ./out2 \
    --agents llm --llm replay     # offline, deterministic, zero cost (a cassette miss fails the stage)

# Hybrid: analyst + test planner via the API; coder + tester served by an assistant
# session (e.g. Claude Code) through files. Approvals are persisted and decided by you.
.venv/bin/orch run workflows/skeleton.yaml --requirement scenarios/greenfield.md --workspace ./out \
    --agents llm --llm record --session-agents coder,tester --approvals file --max-cost-usd 2
.venv/bin/orch pending <run-id>                    # what is waiting for a human
.venv/bin/orch approve <run-id> <approval-id> [--reject] [--comment "..."]
.venv/bin/orch respond <request.json> --files-from <dir> --summary "..."   # session answers

.venv/bin/orch stop <run-id>           # safe-stop: nothing new starts; resumable
.venv/bin/orch resume <run-id>         # continue a stopped, halted or failed run
.venv/bin/orch replan <run-id> --from impact --reason "..."   # upstream changed: re-plan from a stage
.venv/bin/orch replan <run-id> --requirement revised.md       # or from a revised requirement
.venv/bin/orch status <run-id>         # state rebuilt from the event log alone
.venv/bin/orch report <run-id>         # reliability, latency, human decisions, timeline (markdown; --json)
.venv/bin/orch report --all            # metrics across every run in --runs-dir
.venv/bin/orch verify-audit <run-id>   # verify the hash chain (detects edits/deletions)
```

Each run writes `runs/<run-id>/events.jsonl` (hash-chained audit log),
`runs/<run-id>/artifacts/<stage>.v<n>.json` (versioned stage outputs with lineage),
`runs/<run-id>/run.json` (its settings, for resume; no secrets) and, by default,
works in `runs/<run-id>/workspace` (its own git repository).

## Resilience

| Mechanism | Behaviour |
|---|---|
| Bounded retries | per stage `retry.max_attempts` (capped at 10), with the gate/policy evidence fed back |
| Rollback | a failed attempt's applied files are restored (or removed) file by file before the next attempt; a file someone else changed meanwhile is never clobbered; a stage that fails for good ends `ROLLED_BACK` |
| Fallback | `fallback: <agent>` gets one attempt after retries are exhausted or a refusal, with all feedback so far; policy blocks and rejections are final |
| Git checkpoints | one commit per accepted stage containing only its files (`--no-git` to disable). An existing repository is used only if clean, and only on a new `orch/<run-id>` branch |
| Safe-stop | `orch stop`, `--max-minutes`, `--max-cost-usd`: no new work starts, the run ends `HALTED`, resumable |
| Re-planning | `orch replan` (or a changed requirement detected on resume) marks the stage and everything downstream `STALE`. The named stage re-runs; each stale stage downstream is then **reused** if the artifacts it was built from (its recorded lineage) are unchanged, and **re-run** otherwise. Reused artifacts keep their approvals; re-run content needs fresh ones |
| Change requests | rejecting a workflow approval *with a comment* sends the comment back to the agent as a binding instruction (bounded by `max_revisions`); each revision allows one more clarification round |
| Resume | rebuilds state from the verified log; keeps accepted stages (artifact files checked against their recorded hashes), resets the rest, discards an interrupted stage's uncommitted files. Persisted approvals are bound to the exact content approved, so a resumed run that produces something different needs a new decision |

## Metrics and reports

`orch report` derives everything from the hash-chained event log (it refuses a log that fails
verification), so every number can be recomputed from the audit trail:

| Metric | Definition |
|---|---|
| Run / stage success rate | final status per run; executed stages that succeeded (skipped stages never ran) |
| Retries | split by cause: failure (agent error, gate, policy) vs clarification, change request, fallback |
| Rollbacks | reverted change sets, and stages ending `ROLLED_BACK` |
| Incidents, MTTR | opens at a stage's first failure (incl. a fallback), closes at its next success; mean time open, including time stopped before a person fixed it |
| Latency | end to end, split into active, waiting for humans (parallel waits counted once), stopped between processes; per-stage agent and gate time |
| Human decisions | approvals, rejections, change requests, clarification answers; decisions replayed by a resume counted once |

Reports for every recorded run are in `runs/samples/<run>/report.md`, and the cross-run summary in
[`runs/samples/REPORT.md`](runs/samples/REPORT.md). `workflows/fault-demo.yaml` injects two faults
(stub agents only) so a real run records a failure retry, a rollback, a fallback and their recovery.

## Agents

Each agent turn is **one structured-output call** to whichever backend the
config assigns it: a stable system prompt
(`orchestrator/agents/prompts/`), one context message, and a JSON schema
generated from the agent's Pydantic output model (`agents/outputs.py`). The
orchestrator owns the loop, so retries, gates and policy apply to every turn.

- **Least privilege both ways:** a stage's `read_scope` decides what an agent is shown; `write_scope` decides what it may propose.
- **Failure handling:** refusals, auth errors and cassette misses fail the stage immediately; truncation, malformed output and transient errors are retried with feedback.
- **Providers are plug-ins** (`orchestrator/llm/providers/`, registered in `llm/factory.py`): `anthropic` (streaming, cached system prompt, effort, server-side refusal fallback), `openai` (Responses API, strict JSON schema, opt-in reasoning effort, `store=False`), and `session`. Adding one is a single `LLMClient` class plus `register_provider(...)`; each SDK is an optional dependency.
- **Config** (`config/llm.*.yaml`) maps agents to backends and models, expands `${ENV_VARS}`, and carries per-backend pricing. No OpenAI model or price is hard-coded: both change often and belong in config.
- **Hybrid backends:** `--session-agents` routes chosen agents to an assistant session through files (`runs/<id>/llm-requests/`). The session sees the same prompt, context and schema the API would, and its output passes the same validation, policy and gates. Those calls are recorded as `served_model: claude-code-session` at $0, never as API calls.
- **Cost cap:** `--max-cost-usd` safe-stops the run (no new stages start; status `HALTED`) once recorded spend reaches the limit.
- **Telemetry:** every call's model, effort, tokens, cache hits, cost and request id are recorded in the audit log.

## Guardrails

Agents only *propose* a change set. The engine writes it to disk, and only
after `policies/default.yaml` allows it (the strictest triggered action wins):

| Action | Effect | Default rules |
|---|---|---|
| `reject` | change discarded; agent retries with the violations as feedback | secrets, dangerous code (exec, SQL concat, deserialization, wildcard CORS, TLS off), PII in logs |
| `require_approval` | human approves the change *before* it is applied | non-allowlisted Maven dependency, migrations / security / CI paths, modified config, diffs > 1500 lines or 40 files |
| `flag` | applied; recorded for review | (configurable) |
| `block` | stage fails, no retry | (configurable); write-scope and workspace-escape breaches always block |

Every evaluation (`POLICY_EVALUATED`) and the policy file's sha256 are in the audit log.

## Test

```bash
.venv/bin/pytest                 # full suite, including real Maven builds
.venv/bin/pytest -m "not maven"  # fast engine-only suite
```

## Layout

| Path | Purpose |
|---|---|
| `orchestrator/engine/` | contracts (`models.py`), state machine, hash-chained event store, DAG loader, scheduler |
| `orchestrator/agents/` | agent contract + scoped workspace (write allowlist = autonomy boundary), stub agents |
| `orchestrator/gates/` | gate contract + built-ins (`maven_test`, `ambiguities_resolved`, …) |
| `orchestrator/approvals/` | human approval checkpoints (CLI, auto) |
| `orchestrator/llm/` | provider-neutral contract, provider registry + config, providers, session backend, cassettes, strict-schema generation |
| `config/` | LLM backend configurations (which provider serves which agent) |
| `orchestrator/policy/` | policy engine, rules, risk tiers |
| `orchestrator/workspace/` | proposed change sets; the only code path that writes agent output |
| `policies/` | governance policy (policy-as-code) |
| `workflows/` | declarative lifecycle DAGs |
| `scenarios/` | requirement inputs |
