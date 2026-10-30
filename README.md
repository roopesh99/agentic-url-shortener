# Agentic URL Shortener

A governed agentic SDLC orchestrator (Python) that turns a requirement into a
reviewed, tested URL shortener service (Java 17 / Spring Boot).

> Status: **Step 1.5 — skeleton + policy engine.** Engine, gates, approvals,
> policy guardrails and audit log are real; agents are deterministic stubs.
> LLM-backed agents land in Step 2.

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

.venv/bin/orch status <run-id>         # state rebuilt from the event log alone
.venv/bin/orch verify-audit <run-id>   # verify the hash chain (detects edits/deletions)
```

Each run writes `runs/<run-id>/events.jsonl` (hash-chained audit log) and
`runs/<run-id>/artifacts/<stage>.v<n>.json` (versioned stage outputs with lineage).

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
| `orchestrator/policy/` | policy engine, rules, risk tiers |
| `orchestrator/workspace/` | proposed change sets; the only code path that writes agent output |
| `policies/` | governance policy (policy-as-code) |
| `workflows/` | declarative lifecycle DAGs |
| `scenarios/` | requirement inputs |
