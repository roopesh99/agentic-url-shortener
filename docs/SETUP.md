# Setup and running

## Prerequisites

| Tool | Version used | Needed for |
|---|---|---|
| Python | 3.11+ (developed on 3.13) | the orchestrator |
| JDK | 17 | the generated service and the orchestrator's Maven gates |
| Maven | 3.8+ | building and testing the service |
| git | 2.28+ | workspace checkpoints, the replay script |

No Docker, database server or other infrastructure: the service uses file-based H2.

## Install

```bash
python3 -m venv .venv
.venv/bin/pip install -e '.[dev]'     # tests + both provider SDKs
# or only what you use: .venv/bin/pip install -e '.[openai]'  /  '.[anthropic]'
```

## 1. Reproduce the four scenarios offline (no key, $0)

```bash
scripts/replay-scenarios.sh
```

Replays greenfield, brownfield, ambiguous and the full lifecycle from the recorded LLM exchanges (`scenarios/cassettes/`)
and the recorded human decisions (`runs/samples/*/approvals/`), each from the repository state it
originally started from, runs the real Maven gates, and checks that the generated `url-shortener`
is identical to the committed result. Expected output ends with four `✓` lines and four
`events verified` lines.

## 2. Run the service

```bash
cd url-shortener
mvn spring-boot:run                     # public API on :8080, management on 127.0.0.1:8081
```

```bash
curl -s -X POST localhost:8080/api/links -H 'Content-Type: application/json' \
     -d '{"url":"https://example.com/a/long/path","alias":"demo"}'
#  {"code":"demo","shortPath":"/demo","managementToken":"…"}      (keep the token)
curl -si localhost:8080/demo | head -4                             # 302 Location: https://example.com/a/long/path
curl -s localhost:8080/api/links/demo/stats -H "X-Management-Token: <token>"
curl -s -X PATCH localhost:8080/api/links/demo -H "X-Management-Token: <token>" \
     -H 'Content-Type: application/json' -d '{"expiresAt":"2030-01-01T00:00:00Z"}'   # or null to remove
curl -s 127.0.0.1:8081/actuator/metrics/shortener.redirects
mvn test                                                           # 138 tests
```

## 3. Run the orchestrator

### Stub agents (deterministic, no key)

```bash
.venv/bin/orch run workflows/skeleton.yaml --requirement scenarios/greenfield.md --agents stub --auto-approve
.venv/bin/orch run workflows/fault-demo.yaml --requirement scenarios/greenfield.md --agents stub --auto-approve
```

The full lifecycle (`workflows/lifecycle.yaml`: design, docs and release stages included) runs with LLM
agents against this repository's service, as in the recorded run:

```bash
.venv/bin/orch run workflows/lifecycle.yaml --requirement scenarios/lifecycle-expiry.md --workspace . \
    --agents llm --llm record --llm-config config/llm.openai-hybrid.yaml --approvals file
```

The second injects a compile failure (rolled back and retried) and a refusal (handled by the fallback
agent), so its report shows retries, rollback, fallback and MTTR.

### LLM agents

Credentials go in `.env` (git-ignored; `orch` loads it and only ever prints variable names):

```bash
cp .env.example .env && chmod 600 .env      # then edit: OPENAI_API_KEY, OPENAI_MODEL (or ANTHROPIC_API_KEY)
```

| Setup | Command |
|---|---|
| All agents on Claude | `orch run <workflow> --requirement <md> --agents llm --llm record --llm-config config/llm.anthropic.yaml` |
| Hybrid used in this repo: analyst, impact analyst, test planner on OpenAI; coder and tester served by an assistant session | `… --llm-config config/llm.openai-hybrid.yaml --approvals file` |
| Cap spend / time | `--max-cost-usd 2` (needs pricing in the config for non-Claude models) · `--max-minutes 30` |

`--llm record` reuses saved exchanges and records only what is missing; `rerecord` calls the API for
everything; `replay` never calls it.

**Workspace.** By default a run works in `runs/<run-id>/workspace` (its own git repository).
`--workspace .` targets this repository: only if the tree is clean, and only on a new
`orch/<run-id>` branch, one commit per accepted stage; merge it like a pull request.

### Human checkpoints (with `--approvals file`)

The run pauses and prints what is waiting. Answer from any terminal:

```bash
.venv/bin/orch pending <run-id>                                  # what needs a person
.venv/bin/orch answer  <run-id> <clarify-id>                     # after filling runs/<id>/approvals/<clarify-id>.answers.yaml
.venv/bin/orch approve <run-id> <approval-id>                    # approve
.venv/bin/orch approve <run-id> <approval-id> --reject --comment "…"   # reject; with a comment = change request
```

Session-served agents (hybrid mode) write their requests to `runs/<id>/llm-requests/*.prompt.md`; an
assistant answers with `orch respond <request.json> --files-from <dir> --summary "…" --decision "t::c::r"`.

### Control a run

```bash
.venv/bin/orch status <run-id>                 # state rebuilt from the log alone
.venv/bin/orch stop <run-id>                   # safe-stop: nothing new starts
.venv/bin/orch resume <run-id>                 # continue; a changed requirement is detected
.venv/bin/orch replan <run-id> --from impact --reason "…"
.venv/bin/orch replan <run-id> --requirement revised.md
.venv/bin/orch verify-audit <run-id>           # hash chain intact?
.venv/bin/orch report <run-id>                 # or --all, --json
```

## 4. Tests

```bash
.venv/bin/pytest                    # orchestrator: 186 tests, incl. real Maven builds (~40 s)
.venv/bin/pytest -m "not maven"     # without the Maven builds (~6 s)
cd url-shortener && mvn test        # service: 138 tests
```

See [TESTING.md](TESTING.md).

## Troubleshooting

| Symptom | Cause |
|---|---|
| `! export X=…` in Claude Code has no effect on later commands | Each command runs in a fresh shell: put credentials in `.env` |
| A command with a leading `!` fails in a normal terminal | `!` is a Claude Code prompt prefix; in a terminal, drop it (zsh treats `!` as history expansion) |
| `error: … needs pricing …` | `--max-cost-usd` with a backend that has no pricing in its config |
| A replayed run waits at a checkpoint | The replayed content differs from what the decision was recorded on (decisions are content-bound), so it waits for a person by design |
| `no cassette for …` | Replay inputs differ from the recording (prompt, code, model name: set `OPENAI_MODEL=gpt-6-luna`) |
