# Agentic URL Shortener

A governed agentic SDLC orchestrator (Python) that turns a requirement into a
reviewed, tested URL shortener service (Java 17 / Spring Boot).

> Status: **Step 2 — LLM-backed agents, pluggable providers.** Engine, gates,
> approvals, policy guardrails, audit log and LLM agents are real. Providers
> (Anthropic, OpenAI, assistant session) are configuration; deterministic stubs
> remain available for fast, key-free runs.

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

.venv/bin/orch status <run-id>         # state rebuilt from the event log alone
.venv/bin/orch verify-audit <run-id>   # verify the hash chain (detects edits/deletions)
```

Each run writes `runs/<run-id>/events.jsonl` (hash-chained audit log) and
`runs/<run-id>/artifacts/<stage>.v<n>.json` (versioned stage outputs with lineage).

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
