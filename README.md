# Agentic URL Shortener

A governed agentic SDLC orchestrator (Python) that turns a requirement into a
reviewed, tested URL shortener service (Java 17 / Spring Boot).

> Status: **Step 2 — Claude-backed agents.** Engine, gates, approvals, policy
> guardrails, audit log and Claude agents are real; deterministic stubs remain
> available for fast, key-free runs.

## Setup

Requires Python 3.11+, JDK 17, Maven 3.8+.

```bash
python3 -m venv .venv
.venv/bin/pip install -e '.[dev]'
```

## Run

```bash
# interactive: you approve the normalized requirements before any code is written
.venv/bin/orch run workflows/skeleton.yaml --requirement scenarios/greenfield.md --workspace ./out

# non-interactive (recorded in the audit log as a non-human approver)
.venv/bin/orch run workflows/skeleton.yaml --requirement scenarios/greenfield.md --workspace ./out --auto-approve

# Claude agents (claude-opus-5-5). Credentials: ANTHROPIC_API_KEY or `ant auth login`.
.venv/bin/orch run workflows/skeleton.yaml --requirement scenarios/greenfield.md --workspace ./out \
    --agents llm --llm record     # live calls, saved as cassettes under scenarios/cassettes/
.venv/bin/orch run workflows/skeleton.yaml --requirement scenarios/greenfield.md --workspace ./out2 \
    --agents llm --llm replay     # offline, deterministic, zero cost (a cassette miss fails the stage)

.venv/bin/orch status <run-id>         # state rebuilt from the event log alone
.venv/bin/orch verify-audit <run-id>   # verify the hash chain (detects edits/deletions)
```

Each run writes `runs/<run-id>/events.jsonl` (hash-chained audit log) and
`runs/<run-id>/artifacts/<stage>.v<n>.json` (versioned stage outputs with lineage).

## Agents

Each agent turn is **one structured-output call**: a cached system prompt
(`orchestrator/agents/prompts/`), one context message, and a JSON schema
generated from the agent's Pydantic output model (`agents/outputs.py`). The
orchestrator owns the loop, so retries, gates and policy apply to every turn.

- **Least privilege both ways:** a stage's `read_scope` decides what an agent is shown; `write_scope` decides what it may propose.
- **Failure handling:** refusals, auth errors and cassette misses fail the stage immediately; truncation, malformed output and transient errors are retried with feedback.
- **Server-side refusal fallback** (`fallbacks: "default"`) is enabled; pass `refusal_fallback=False` to `AnthropicLLM` to turn it off.
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
| `orchestrator/llm/` | Claude client, record/replay cassettes, strict-schema generation |
| `orchestrator/policy/` | policy engine, rules, risk tiers |
| `orchestrator/workspace/` | proposed change sets; the only code path that writes agent output |
| `policies/` | governance policy (policy-as-code) |
| `workflows/` | declarative lifecycle DAGs |
| `scenarios/` | requirement inputs |
