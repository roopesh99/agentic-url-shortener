"""Step 3 resilience: rollback, fallback, safe-stop, resume, git checkpoints, approval binding."""

import asyncio
import json
import subprocess
from pathlib import Path

import pytest

from orchestrator.agents.base import FatalAgentError
from orchestrator.approvals.service import (ApprovalRequest, AutoApprover, FileApprover, record_decision)
from orchestrator.engine.events import EventStore, EventType
from orchestrator.engine.scheduler import STOP_FILE, ResumeError
from orchestrator.engine.state import NodeState
from orchestrator.engine.models import GateResult
from orchestrator.gates.base import Gate
from orchestrator.workspace.git import GitWorkspace, WorkspaceError

from .conftest import make_agent

S = NodeState
SRC = "src/main/App.java"


def stage(id_="impl", **overrides):
    return {"id": id_, "agent": "x", "write_scope": ["src/**"], **overrides}


def wf(*stages):
    return {"name": "w", "stages": list(stages)}


def events(engine, type_=None):
    return [e for e in EventStore.load(engine.events.path) if type_ is None or e.type == type_]


def git(path, *args):
    return subprocess.run(["git", *args], cwd=path, capture_output=True, text=True, check=True).stdout.strip()


# --- per-attempt rollback --------------------------------------------------------------------

async def test_failed_attempt_is_reverted_before_the_retry(build_engine, recorder, tmp_path):
    """The known gap from Step 1.5: files from a rejected attempt must not linger."""
    def coder(ctx):
        ctx.write_file(SRC, f"class App {{ /* attempt {ctx.attempt} */ }}")
        if ctx.attempt == 1:
            ctx.write_file("src/main/Leftover.java", "class Leftover {}")

    engine = build_engine(wf(stage(exit_gates=[{"name": "fail_until", "args": {"pass_on": 2}}],
                                   retry={"max_attempts": 2})), {"x": make_agent(recorder, behaviour=coder)})
    assert (await engine.run()).succeeded
    ws = tmp_path / "ws"
    assert "attempt 2" in (ws / SRC).read_text()
    assert not (ws / "src/main/Leftover.java").exists(), "attempt 1's extra file was rolled back"
    [reverted] = events(engine, EventType.CHANGES_REVERTED)
    assert sorted(reverted.payload["reverted"]) == ["src/main/App.java", "src/main/Leftover.java"]


async def test_exhausted_stage_restores_previous_content_and_ends_rolled_back(build_engine, recorder, tmp_path):
    ws = tmp_path / "ws"
    (ws / "src/main").mkdir(parents=True)
    (ws / SRC).write_text("ORIGINAL")

    def coder(ctx):
        ctx.write_file(SRC, "BROKEN")
        ctx.write_file("src/main/New.java", "class New {}")

    engine = build_engine(wf(stage(exit_gates=["fail_until"], retry={"max_attempts": 2})),
                          {"x": make_agent(recorder, behaviour=coder)})
    result = await engine.run()
    assert result.states["impl"] is S.ROLLED_BACK
    assert (ws / SRC).read_text() == "ORIGINAL"
    assert not (ws / "src/main/New.java").exists()
    assert [e.payload["to"] for e in events(engine, EventType.STAGE_STATE)][-2:] == ["FAILED", "ROLLED_BACK"]


async def test_revert_never_clobbers_a_file_someone_else_changed(build_engine, recorder, tmp_path, gates):
    class TouchThenFail(Gate):
        name = "touch_then_fail"

        async def check(self, ctx):
            (ctx.workspace / SRC).write_text("EDITED BY SOMEONE ELSE")
            return self.result(False, "nope")

    gates.register(TouchThenFail.name, TouchThenFail)
    engine = build_engine(wf(stage(exit_gates=["touch_then_fail"])),
                          {"x": make_agent(recorder, behaviour=lambda ctx: ctx.write_file(SRC, "MINE"))})
    await engine.run()
    assert (tmp_path / "ws" / SRC).read_text() == "EDITED BY SOMEONE ELSE"
    [reverted] = events(engine, EventType.CHANGES_REVERTED)
    assert reverted.payload["conflicts"] == [SRC] and reverted.payload["reverted"] == []


async def test_rejected_workflow_approval_rolls_back_applied_changes(build_engine, recorder, tmp_path):
    engine = build_engine(wf(stage(approval="required", exit_gates=["pass"])),
                          {"x": make_agent(recorder, behaviour=lambda ctx: ctx.write_file(SRC, "x"))},
                          approver=AutoApprover(approve=False))
    result = await engine.run()
    assert result.states["impl"] is S.ROLLED_BACK
    assert not (tmp_path / "ws" / SRC).exists()


# --- fallback --------------------------------------------------------------------------------

async def test_fallback_agent_runs_once_with_feedback_after_retries_are_exhausted(build_engine, recorder):
    primary = make_agent(recorder, behaviour=lambda ctx: ctx.write_file(SRC, "primary"))
    seen = {}

    def rescue(ctx):
        seen["feedback"] = ctx.feedback
        ctx.write_file(SRC, "fallback")

    class ContentGate(Gate):
        name = "content"

        async def check(self, ctx):
            ok = (ctx.workspace / SRC).read_text() == "fallback"
            return self.result(ok, "content check")

    engine = build_engine(wf(stage(retry={"max_attempts": 2}, fallback="y", exit_gates=["content"])),
                          {"x": primary, "y": make_agent(recorder, behaviour=rescue)})
    engine.gates.register(ContentGate.name, ContentGate)
    result = await engine.run()

    assert result.succeeded
    assert [c["attempt"] for c in recorder.attempts("impl")] == [1, 2, 3]
    assert "content" in seen["feedback"][0], "the fallback agent learns why the primary failed"
    [engaged] = events(engine, EventType.FALLBACK_ENGAGED)
    assert engaged.payload == {**engaged.payload, "from_agent": "x", "to_agent": "y"}
    accepted = [e for e in events(engine, EventType.ARTIFACT_RECORDED)][-1]
    assert accepted.payload["produced_by"] == "impl/y#3"


async def test_fallback_also_follows_a_refusal(build_engine, recorder):
    def refuse(ctx):
        raise FatalAgentError("model declined the request")

    engine = build_engine(wf(stage(fallback="y")), {"x": make_agent(recorder, behaviour=refuse),
                                                   "y": make_agent(recorder)})
    assert (await engine.run()).succeeded


async def test_policy_block_is_not_rescued_by_fallback(build_engine, recorder):
    def rogue(ctx):
        ctx.write_file("../escape.txt", "x")

    engine = build_engine(wf(stage(fallback="y")), {"x": make_agent(recorder, behaviour=rogue),
                                                   "y": make_agent(recorder)})
    result = await engine.run()
    assert result.states["impl"] is S.FAILED
    assert recorder.attempts("impl")[-1]["attempt"] == 1, "a breach of the autonomy boundary is final"


# --- safe-stop -------------------------------------------------------------------------------

async def test_stop_file_halts_before_new_work_and_resume_finishes(build_engine, recorder, tmp_path):
    def stop_after_a(ctx):
        (tmp_path / "run" / STOP_FILE).write_text("stop")

    workflow = wf(stage("a"), stage("b", needs=["a"]), stage("c", needs=["b"]))
    engine = build_engine(workflow, {"x": make_agent(recorder, behaviour=stop_after_a)})
    first = await engine.run()
    assert first.states == {"a": S.SUCCEEDED, "b": S.SKIPPED, "c": S.SKIPPED}
    assert events(engine, EventType.RUN_COMPLETED)[-1].payload["status"] == "HALTED"

    resumed = build_engine(workflow, {"x": make_agent(recorder)})
    second = await resumed.run(resume=True)
    assert second.succeeded
    assert [c["stage"] for c in recorder.calls] == ["a", "b", "c"], "a is not re-run"
    assert not (tmp_path / "run" / STOP_FILE).exists()
    [resumed_evt] = events(resumed, EventType.RUN_RESUMED)
    assert resumed_evt.payload["kept"] == ["a"] and resumed_evt.payload["stop_cleared"] is True
    ok, msg = EventStore.verify(resumed.events.path)
    assert ok, msg


async def test_time_budget_halts_the_run(build_engine, recorder):
    engine = build_engine(wf(stage("a"), stage("b", needs=["a"])), {"x": make_agent(recorder, delay=0.05)},
                          max_minutes=0.0001)
    result = await engine.run()
    assert result.states["b"] is S.SKIPPED
    assert "time budget" in events(engine, EventType.RUN_HALTED)[0].payload["reason"]


# --- resume ----------------------------------------------------------------------------------

async def test_resume_reruns_only_unfinished_stages_with_accepted_context(build_engine, recorder):
    flaky = {"broken": True}

    def b_agent(ctx):
        if flaky["broken"]:
            raise RuntimeError("upstream API down")

    workflow = wf(stage("a"), stage("b", needs=["a"]), stage("c", needs=["b"]))
    first = await build_engine(workflow, {"x": make_agent(recorder, behaviour=lambda ctx: b_agent(ctx)
                                                           if ctx.stage.id == "b" else None)}).run()
    assert first.states == {"a": S.SUCCEEDED, "b": S.FAILED, "c": S.SKIPPED}

    flaky["broken"] = False
    seen = {}

    def capture(ctx):
        seen[ctx.stage.id] = sorted(ctx.inputs)

    resumed = build_engine(workflow, {"x": make_agent(recorder, behaviour=capture)})
    second = await resumed.run(resume=True)
    assert second.succeeded
    assert "a" not in seen and seen["c"] == ["a", "b"], "c sees a's artifact restored from the first run"
    resets = [e for e in events(resumed, EventType.STAGE_STATE) if e.payload["reason"].startswith("resume:")]
    assert {(e.stage, e.payload["from"]) for e in resets} == {("b", "FAILED"), ("c", "SKIPPED")}


async def test_resume_refuses_a_tampered_log_or_artifact(build_engine, recorder, tmp_path):
    workflow = wf(stage("a"), stage("b", needs=["a"]))
    await build_engine(workflow, {"x": make_agent(recorder, behaviour=lambda ctx: (_ for _ in ()).throw(
        RuntimeError("x")) if ctx.stage.id == "b" else None)}).run()

    artifact = tmp_path / "run" / "artifacts" / "a.v1.json"
    original = artifact.read_text()
    artifact.write_text(original.replace('"summary": "a done"', '"summary": "forged"'))
    with pytest.raises(ResumeError, match="modified"):
        await build_engine(workflow, {"x": make_agent(recorder)}).run(resume=True)
    artifact.write_text(original)

    log = tmp_path / "run" / "events.jsonl"
    lines = log.read_text().splitlines()
    lines[1] = lines[1].replace("PENDING", "SUCCEEDED", 1)
    log.write_text("\n".join(lines) + "\n")
    with pytest.raises(ResumeError, match="verification"):
        await build_engine(workflow, {"x": make_agent(recorder)}).run(resume=True)


# --- git checkpoints -------------------------------------------------------------------------

async def test_each_accepted_stage_is_one_commit_with_only_its_files(build_engine, recorder, tmp_path):
    ws = tmp_path / "ws"

    def write(ctx):
        ctx.write_file(f"src/{ctx.stage.id}.txt", ctx.stage.id)

    workflow = wf(stage("a"), stage("b", needs=["a"]), stage("c", needs=["a"]))
    engine = build_engine(workflow, {"x": make_agent(recorder, behaviour=write)}, git=GitWorkspace(ws, "test-run"))
    assert (await engine.run()).succeeded

    log = git(ws, "log", "--format=%s", "--reverse").splitlines()
    assert log[0] == "orch(test-run): workspace baseline"
    assert sorted(log[1:]) == ["orch(test-run): a a@v1", "orch(test-run): b b@v1", "orch(test-run): c c@v1"]
    for commit in events(engine, EventType.CHECKPOINT_COMMITTED):
        files = git(ws, "show", "--name-only", "--format=", commit.payload["commit"]).splitlines()
        assert files == [f"src/{commit.stage}.txt"], "a checkpoint contains exactly its stage's files"
    assert git(ws, "status", "--porcelain") == ""


def test_existing_repository_is_used_only_clean_and_on_a_new_branch(tmp_path):
    repo = tmp_path / "project"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    (repo / "README.md").write_text("hello")
    git(repo, "add", "-A")
    git(repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "init")

    (repo / "dirty.txt").write_text("uncommitted work")
    with pytest.raises(WorkspaceError, match="uncommitted"):
        GitWorkspace(repo, "r1").prepare()
    (repo / "dirty.txt").unlink()

    info = GitWorkspace(repo, "r1").prepare()
    assert info["mode"] == "branch" and info["started_from"] == "main"
    assert git(repo, "rev-parse", "--abbrev-ref", "HEAD") == "orch/r1"
    assert git(repo, "log", "--format=%s", "main") == "init", "the person's branch is untouched"


def test_only_new_files_in_the_selectors_recording_directory_are_exempt_from_the_clean_check(tmp_path):
    """orch run auto records the selector's exchange in the repository before the run's branch exists."""
    repo = tmp_path / "project"
    (repo / "scenarios" / "cassettes" / "old").mkdir(parents=True)
    (repo / "scenarios" / "cassettes" / "old" / "x.json").write_text("{}")
    git(repo, "init", "-q", "-b", "main")
    git(repo, "add", "-A")
    git(repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "init")
    recording = "scenarios/cassettes/select-req"
    (repo / recording).mkdir(parents=True)
    (repo / recording / "selector-1.json").write_text("{}")

    with pytest.raises(WorkspaceError, match="uncommitted"):
        GitWorkspace(repo, "r0").prepare()  # without the exemption it is dirty
    (repo / "elsewhere.txt").write_text("not exempt")
    with pytest.raises(WorkspaceError, match="uncommitted"):
        GitWorkspace(repo, "r1", untracked_ok=[recording]).prepare()
    (repo / "elsewhere.txt").unlink()
    (repo / "scenarios" / "cassettes" / "old" / "x.json").write_text('{"changed": true}')
    with pytest.raises(WorkspaceError, match="uncommitted"):
        GitWorkspace(repo, "r2", untracked_ok=["scenarios/cassettes/old"]).prepare()  # modified, not new
    git(repo, "checkout", "-q", "--", ".")

    assert GitWorkspace(repo, "r3", untracked_ok=[recording]).prepare()["branch"] == "orch/r3"


def test_discard_uncommitted_only_touches_the_given_scopes(tmp_path):
    ws = tmp_path / "ws"
    g = GitWorkspace(ws, "r1")
    (ws / "src").mkdir(parents=True)
    (ws / "src" / "Kept.java").write_text("committed")
    (ws / "notes.txt").write_text("outside scope")
    g.prepare()
    (ws / "src" / "Kept.java").write_text("half-applied")
    (ws / "src" / "New.java").write_text("half-applied")
    (ws / "notes.txt").write_text("edited outside scope")

    discarded = g.discard_uncommitted(["src/**"])
    assert sorted(discarded) == ["src/Kept.java", "src/New.java"]
    assert (ws / "src" / "Kept.java").read_text() == "committed"
    assert not (ws / "src" / "New.java").exists()
    assert (ws / "notes.txt").read_text() == "edited outside scope"


async def test_resume_discards_an_interrupted_stages_uncommitted_files(build_engine, recorder, tmp_path):
    ws = tmp_path / "ws"
    workflow = wf(stage("a"))
    first = build_engine(workflow, {"x": make_agent(recorder, behaviour=lambda ctx: (_ for _ in ()).throw(
        RuntimeError("crash")))}, git=GitWorkspace(ws, "r1"))
    await first.run()
    (ws / "src").mkdir(exist_ok=True)
    (ws / "src" / "half.txt").write_text("written before the crash")  # simulate a crash mid-apply

    resumed = build_engine(workflow, {"x": make_agent(recorder)}, git=GitWorkspace(ws, "r1"))
    assert (await resumed.run(resume=True)).succeeded
    assert not (ws / "src" / "half.txt").exists()
    assert events(resumed, EventType.RUN_RESUMED)[0].payload["discarded_uncommitted"] == ["src/half.txt"]


# --- approvals bound to content --------------------------------------------------------------

async def test_a_persisted_approval_applies_only_to_the_content_it_approved(tmp_path):
    directory = tmp_path / "approvals"

    def request(sha):
        return ApprovalRequest(run_id="r", stage="design", reason="r", summary="s", artifact_sha=sha)

    pending = asyncio.create_task(FileApprover(directory, poll_seconds=0.01).decide(request("a" * 64)))
    await asyncio.sleep(0.05)
    record_decision(directory, "design-" + "a" * 12, approved=True)
    assert (await asyncio.wait_for(pending, 1)).approved

    # a new process (resume) with the same content gets the recorded decision immediately...
    assert (await asyncio.wait_for(FileApprover(directory).decide(request("a" * 64)), 1)).approved
    # ...but different content needs a fresh decision
    other = asyncio.create_task(FileApprover(directory, poll_seconds=0.01).decide(request("b" * 64)))
    await asyncio.sleep(0.05)
    assert not other.done()
    other.cancel()


# --- CLI -------------------------------------------------------------------------------------

def test_run_settings_are_saved_without_secrets_and_stop_needs_a_run(tmp_path, monkeypatch):
    from orchestrator.cli import RUN_SETTINGS, main as orch
    assert not any("key" in s or "token" in s or "secret" in s for s in RUN_SETTINGS)
    assert orch(["--env-file", str(tmp_path / "none"), "--runs-dir", str(tmp_path), "stop", "nope"]) == 2


async def test_workflow_hash_is_recorded_and_a_change_on_resume_is_flagged(build_engine, recorder):
    def fail_b(ctx):
        if ctx.stage.id == "b":
            raise RuntimeError("down")

    workflow = wf(stage("a"), stage("b", needs=["a"]))
    first = build_engine(workflow, {"x": make_agent(recorder, behaviour=fail_b)})
    await first.run()
    started = events(first, EventType.RUN_STARTED)[0].payload
    assert len(started["workflow_sha"]) == 64

    same = build_engine(workflow, {"x": make_agent(recorder, behaviour=fail_b)})
    await same.run(resume=True)
    assert events(same, EventType.RUN_RESUMED)[-1].payload["workflow_changed"] is False

    changed = wf(stage("a"), stage("b", needs=["a"], retry={"max_attempts": 2}))
    resumed = build_engine(changed, {"x": make_agent(recorder)})
    assert (await resumed.run(resume=True)).succeeded
    last = events(resumed, EventType.RUN_RESUMED)[-1].payload
    assert last["workflow_changed"] is True and last["workflow_sha"] != started["workflow_sha"]


# --- request changes -------------------------------------------------------------------------

class ScriptedApprover(AutoApprover):
    """Returns pre-set decisions in order: (approved, comment)."""

    def __init__(self, *decisions):
        super().__init__()
        self.decisions = list(decisions)

    async def decide(self, request):
        from orchestrator.approvals.service import ApprovalDecision
        approved, comment = self.decisions.pop(0)
        return ApprovalDecision(approved=approved, approver="reviewer", comment=comment)


async def test_rejection_with_a_comment_sends_it_back_as_a_change_request(build_engine, recorder):
    engine = build_engine(wf(stage(approval="required", max_revisions=2)), {"x": make_agent(recorder)},
                          approver=ScriptedApprover((False, "keep error code expired"), (True, "")))
    assert (await engine.run()).succeeded
    first, second = recorder.attempts("impl")
    assert first["feedback"] == []
    assert any("keep error code expired" in f and "binding" in f for f in second["feedback"])
    [req] = events(engine, EventType.CHANGES_REQUESTED)
    assert req.payload["requested_by"] == "reviewer" and req.payload["revision"] == 1
    accepted = engine.artifacts["impl"].result.outputs
    assert accepted["change_requests"] == ["keep error code expired"], "the instruction travels with the output"


async def test_change_request_survives_a_later_gate_failure(build_engine, recorder, gates):
    class FailsOnSecondAttempt(Gate):
        name = "fails_on_second"

        async def check(self, ctx):
            attempt = int(ctx.artifact.produced_by.rsplit("#", 1)[1])
            return self.result(attempt != 2, f"attempt {attempt} broke the build")

    gates.register(FailsOnSecondAttempt.name, FailsOnSecondAttempt)
    # attempt 1: passes gates, rejected with a comment; attempt 2: the gate fails; attempt 3: passes, approved
    engine = build_engine(
        wf(stage(approval="required", max_revisions=1, retry={"max_attempts": 2}, exit_gates=["fails_on_second"])),
        {"x": make_agent(recorder)},
        approver=ScriptedApprover((False, "use 403 for wrong tokens"), (True, "")))
    assert (await engine.run()).succeeded
    third = recorder.attempts("impl")[2]["feedback"]
    assert any("use 403 for wrong tokens" in f for f in third), "the reviewer's instruction outlives the gate failure"
    assert any("attempt 2 broke the build" in f for f in third), "and the gate evidence is there too"


async def test_rejection_without_a_comment_is_final_and_revisions_are_bounded(build_engine, recorder):
    silent = build_engine(wf(stage(approval="required", max_revisions=2)), {"x": make_agent(recorder)},
                          approver=ScriptedApprover((False, "")))
    assert (await silent.run()).states["impl"] is S.FAILED

    bounded = build_engine(wf(stage("b", approval="required", max_revisions=1)), {"x": make_agent(recorder)},
                           approver=ScriptedApprover((False, "change 1"), (False, "change 2")))
    assert (await bounded.run()).states["b"] is S.FAILED
    assert len(recorder.attempts("b")) == 2


async def test_a_revision_earns_one_more_clarification_round(build_engine, recorder, gates):
    """Rounds exhausted, then a change request raises a new question: it gets answered, not failed."""
    from orchestrator.approvals.service import ClarificationResponse

    class AsksAfterRevision(Gate):
        name = "asks_after_revision"

        async def check(self, ctx):
            attempt = int(ctx.artifact.produced_by.rsplit("#", 1)[1])
            answered = {c["question"] for c in ctx.artifact.result.outputs.get("clarifications", [])}
            q = {1: "first question?", 3: "question raised by the revision?"}.get(attempt)
            if q and q not in answered:
                result = self.result(False, "open question")
                result.questions = [{"question": q, "why": ""}]
                return result
            return self.result(True, "resolved")

    class Reviewer(ScriptedApprover):
        async def clarify(self, request):
            return ClarificationResponse(answers=[{"question": q["question"], "answer": "yes"}
                                                  for q in request.questions], answered_by="reviewer")

    gates.register(AsksAfterRevision.name, AsksAfterRevision)
    engine = build_engine(
        wf(stage(approval="required", max_revisions=1, clarification={"max_rounds": 1},
                 exit_gates=["asks_after_revision"])),
        {"x": make_agent(recorder)},
        approver=Reviewer((False, "please change X"), (True, "")))
    # attempt 1: question (round 1 of 1) -> attempt 2: passes, rejected with a comment (revision 1)
    # -> attempt 3: new question; without the extra round this would fail -> attempt 4: approved
    assert (await engine.run()).succeeded
    assert [e.payload["round"] for e in events(engine, EventType.CLARIFICATION_ANSWERED)] == [1, 2]
    assert len(recorder.attempts("impl")) == 4
