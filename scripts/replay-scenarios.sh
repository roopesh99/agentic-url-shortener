#!/usr/bin/env bash
# Replays the four recorded scenarios offline: no API key, no network calls to an LLM, $0.
# Every LLM exchange comes from scenarios/cassettes/, every human decision from runs/samples/.
# Each scenario starts from the repository state it originally started from (a temporary git
# worktree) and its generated url-shortener is compared with the commit the original run produced.
set -euo pipefail
cd "$(dirname "$0")/.."
ROOT="$PWD"
WORK="$(mktemp -d)"
trap 'git -C "$ROOT" worktree remove --force "$WORK/wt-brownfield" 2>/dev/null || true
      git -C "$ROOT" worktree remove --force "$WORK/wt-ambiguous" 2>/dev/null || true
      git -C "$ROOT" worktree remove --force "$WORK/wt-lifecycle" 2>/dev/null || true
      git -C "$ROOT" branch -D orch/replay-brownfield orch/replay-ambiguous orch/replay-lifecycle >/dev/null 2>&1 || true
      rm -rf "$WORK"' EXIT

unset OPENAI_API_KEY ANTHROPIC_API_KEY
export OPENAI_MODEL=gpt-6-luna   # the recorded model name: it is part of each cassette's key
orch() { .venv/bin/orch --env-file /dev/null --runs-dir "$WORK/runs" "$@"; }
llm=(--agents llm --llm replay --llm-config config/llm.openai-hybrid.yaml)
status=0
check() {  # $1 label, $2 diff command result
  if [ "$2" = 0 ]; then echo "  ✓ $1: generated code identical to the committed result"; else echo "  ✗ $1: differs"; status=1; fi
}

echo "== greenfield: build the service from scenarios/greenfield.md"
# Recorded before decision ids were content-bound, so its answers replay from the reviewed answers
# file and its (all-approve) checkpoints from the auto-approver, which logs itself as non-human.
orch run workflows/skeleton.yaml --requirement scenarios/greenfield.md "${llm[@]}" \
    --answers scenarios/greenfield.answers.yaml --approvals auto --run-id replay-greenfield | tail -2
mkdir -p "$WORK/expected" && git archive cbb7946 url-shortener | tar -x -C "$WORK/expected"
rm -f "$WORK/expected/url-shortener/.gitignore"   # added by hand when the service moved to the repo root
diff -rq --exclude=target --exclude=data "$WORK/expected/url-shortener" "$WORK/runs/replay-greenfield/workspace/url-shortener" >/dev/null; check greenfield $?

echo "== brownfield: add click analytics to the existing service"
git worktree add -q --detach "$WORK/wt-brownfield" 6c38ebb
orch run workflows/brownfield.yaml --requirement scenarios/brownfield-analytics.md --workspace "$WORK/wt-brownfield" \
    "${llm[@]}" --recorded-decisions runs/samples/live-brownfield-1/approvals --run-id replay-brownfield | tail -2
git -C "$WORK/wt-brownfield" diff --quiet 94d3336 -- url-shortener; check brownfield $?

echo "== ambiguous: 'make it more reliable and secure' (includes a rejection with a change request)"
git worktree add -q --detach "$WORK/wt-ambiguous" b752f94
orch run workflows/brownfield.yaml --requirement scenarios/ambiguous-reliability.md --workspace "$WORK/wt-ambiguous" \
    "${llm[@]}" --recorded-decisions runs/samples/live-ambiguous-1/approvals --run-id replay-ambiguous | tail -2
git -C "$WORK/wt-ambiguous" diff --quiet c225b82 -- url-shortener; check ambiguous $?

echo "== lifecycle: let owners change a link's expiry, through design, docs and release readiness"
# The workflow file is the one the run started with: later workflow changes (e.g. downstream_context)
# change prompts, and a replay must send exactly the recorded requests. The release prompt was fixed
# mid-run, so the replay's release passes first time where the live run failed once and was re-planned.
git worktree add -q --detach "$WORK/wt-lifecycle" 5622981
orch run "$WORK/wt-lifecycle/workflows/lifecycle.yaml" --requirement scenarios/lifecycle-expiry.md \
    --workspace "$WORK/wt-lifecycle" "${llm[@]}" --recorded-decisions runs/samples/live-lifecycle-1/approvals \
    --run-id replay-lifecycle | tail -2
git -C "$WORK/wt-lifecycle" diff --quiet f404c98 -- url-shortener; check lifecycle $?

for r in replay-greenfield replay-brownfield replay-ambiguous replay-lifecycle; do echo "  $r: $(orch verify-audit $r)"; done
exit $status
