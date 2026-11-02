#!/usr/bin/env bash
# Replays the seven recorded scenarios offline: no API key, no network calls to an LLM, $0.
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
      git -C "$ROOT" worktree remove --force "$WORK/wt-bugfix" 2>/dev/null || true
      git -C "$ROOT" worktree remove --force "$WORK/wt-auto" 2>/dev/null || true
      git -C "$ROOT" worktree remove --force "$WORK/wt-tests" 2>/dev/null || true
      git -C "$ROOT" branch -D orch/replay-brownfield orch/replay-ambiguous orch/replay-lifecycle orch/replay-bugfix orch/replay-auto orch/replay-tests >/dev/null 2>&1 || true
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
mkdir -p "$WORK/expected" && git archive ca25c18 url-shortener | tar -x -C "$WORK/expected"
rm -f "$WORK/expected/url-shortener/.gitignore"   # added by hand when the service moved to the repo root
diff -rq --exclude=target --exclude=data "$WORK/expected/url-shortener" "$WORK/runs/replay-greenfield/workspace/url-shortener" >/dev/null; check greenfield $?

echo "== brownfield: add click analytics to the existing service"
git worktree add -q --detach "$WORK/wt-brownfield" 298fa02
orch run workflows/brownfield.yaml --requirement scenarios/brownfield-analytics.md --workspace "$WORK/wt-brownfield" \
    "${llm[@]}" --recorded-decisions runs/samples/live-brownfield-1/approvals --run-id replay-brownfield | tail -2
git -C "$WORK/wt-brownfield" diff --quiet b5c4980 -- url-shortener; check brownfield $?

echo "== ambiguous: 'make it more reliable and secure' (includes a rejection with a change request)"
git worktree add -q --detach "$WORK/wt-ambiguous" 3d4d816
orch run workflows/brownfield.yaml --requirement scenarios/ambiguous-reliability.md --workspace "$WORK/wt-ambiguous" \
    "${llm[@]}" --recorded-decisions runs/samples/live-ambiguous-1/approvals --run-id replay-ambiguous | tail -2
git -C "$WORK/wt-ambiguous" diff --quiet e7efb93 -- url-shortener; check ambiguous $?

echo "== lifecycle: let owners change a link's expiry, through design, docs and release readiness"
# The workflow file is the one the run started with: later workflow changes (e.g. downstream_context)
# change prompts, and a replay must send exactly the recorded requests. The release prompt was fixed
# mid-run, so the replay's release passes first time where the live run failed once and was re-planned.
git worktree add -q --detach "$WORK/wt-lifecycle" 668cb13
orch run "$WORK/wt-lifecycle/workflows/lifecycle.yaml" --requirement scenarios/lifecycle-expiry.md \
    --workspace "$WORK/wt-lifecycle" "${llm[@]}" --recorded-decisions runs/samples/live-lifecycle-1/approvals \
    --run-id replay-lifecycle | tail -2
git -C "$WORK/wt-lifecycle" diff --quiet 0e47485 -- url-shortener; check lifecycle $?

echo "== bug fix: links to international and underscore host names were rejected (reproduce, then fix)"
# The workflow file as of the re-planned release (1084e53, with gate_context): later gates would change
# what the release agent is shown. The replay follows the re-planned release, so its release passes
# first time where the live run failed once.
git worktree add -q --detach "$WORK/wt-bugfix" 4f6bd17
git show 1084e53:workflows/bugfix.yaml > "$WORK/bugfix.yaml"
orch run "$WORK/bugfix.yaml" --requirement scenarios/bugfix-idn.md --workspace "$WORK/wt-bugfix" \
    "${llm[@]}" --recorded-decisions runs/samples/live-bugfix-1/approvals --run-id replay-bugfix | tail -2
git -C "$WORK/wt-bugfix" diff --quiet 5bc359a -- url-shortener; check bugfix $?

echo "== auto: a bug report routed by 'orch run auto', with the live run's failure and re-plan"
# The selection (recorded exchange and the owner's confirmation) is replayed too. The live run failed
# its first gate and was re-planned with a corrected workflow; the replay does the same, because the
# release agent sees stage versions (requirements@v2), which only that sequence reproduces.
git worktree add -q --detach "$WORK/wt-auto" 0949920
mkdir -p "$WORK/wf-auto" && git archive 0949920 workflows | tar -x -C "$WORK/wf-auto"
orch run auto --requirement scenarios/bugfix-html-error.md --workspace "$WORK/wt-auto" \
    --workflows-dir "$WORK/wf-auto/workflows" "${llm[@]}" \
    --recorded-decisions runs/samples/live-bugfix-2/approvals --run-id replay-auto | tail -1 \
    || echo "  (failed at its first gate, as the live run did)"
git show 6ce4920:workflows/bugfix.yaml > "$WORK/wf-auto/workflows/bugfix.yaml"
if ! orch replan replay-auto --from requirements --reason "replay of the live re-plan" > "$WORK/auto.log" 2>&1; then
    tail -20 "$WORK/auto.log"
    grep '"passed":false\|"AGENT_ERROR"' "$WORK/runs/replay-auto/events.jsonl" | cut -c1-400 || true
    exit 1
fi
tail -2 "$WORK/auto.log"
git -C "$WORK/wt-auto" diff --quiet 6484c6a -- url-shortener; check auto $?

echo "== tests: a test-quality request routed by 'orch run auto' to brownfield"
git worktree add -q --detach "$WORK/wt-tests" 16f3bd2
mkdir -p "$WORK/wf-tests" && git archive 16f3bd2 workflows | tar -x -C "$WORK/wf-tests"
orch run auto --requirement scenarios/harden-race-tests.md --workspace "$WORK/wt-tests" \
    --workflows-dir "$WORK/wf-tests/workflows" "${llm[@]}" \
    --recorded-decisions runs/samples/live-brownfield-2/approvals --run-id replay-tests | tail -2
git -C "$WORK/wt-tests" diff --quiet 1b837e6 -- url-shortener; check tests $?

for r in replay-greenfield replay-brownfield replay-ambiguous replay-lifecycle replay-bugfix replay-auto replay-tests; do echo "  $r: $(orch verify-audit $r)"; done
exit $status
