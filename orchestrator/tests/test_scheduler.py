"""Engine behaviour: ordering, parallel fork/join, retries, approvals, autonomy boundary."""

import pytest

from orchestrator.approvals.service import AutoApprover
from orchestrator.engine.events import EventStore, EventType, replay_states
from orchestrator.engine.state import NodeState

from .conftest import make_agent

S = NodeState

DIAMOND = {
    "name": "diamond",
    "stages": [
        {"id": "a", "agent": "fast"},
        {"id": "b", "agent": "slow", "needs": ["a"]},
        {"id": "c", "agent": "slow", "needs": ["a"]},
        {"id": "d", "agent": "fast", "needs": ["b", "c"]},
    ],
}


def _events(engine, type_=None):
    events = EventStore.load(engine.events.path)
    return [e for e in events if type_ is None or e.type == type_]


async def test_fork_runs_in_parallel_and_join_waits_for_both(build_engine, recorder):
    engine = build_engine(DIAMOND, {"fast": make_agent(recorder), "slow": make_agent(recorder, delay=0.2)})
    result = await engine.run()

    assert result.succeeded
    b_start, b_end = recorder.window("b")
    c_start, c_end = recorder.window("c")
    assert b_start < c_end and c_start < b_end, "b and c should overlap in time"
    d_start, _ = recorder.window("d")
    assert d_start >= max(b_end, c_end), "join must start after both branches finish"
    assert recorder.window("a")[1] <= min(b_start, c_start)


async def test_max_parallel_one_serializes_branches(build_engine, recorder):
    engine = build_engine(
        DIAMOND, {"fast": make_agent(recorder), "slow": make_agent(recorder, delay=0.1)}, max_parallel=1
    )
    assert (await engine.run()).succeeded
    b, c = recorder.window("b"), recorder.window("c")
    assert b[1] <= c[0] or c[1] <= b[0]


async def test_gate_failure_retries_with_feedback_then_succeeds(build_engine, recorder):
    workflow = {"name": "w", "stages": [{
        "id": "impl", "agent": "x", "retry": {"max_attempts": 3},
        "exit_gates": [{"name": "fail_until", "args": {"pass_on": 3}}],
    }]}
    engine = build_engine(workflow, {"x": make_agent(recorder)})
    result = await engine.run()

    assert result.succeeded
    attempts = recorder.attempts("impl")
    assert [a["attempt"] for a in attempts] == [1, 2, 3]
    assert attempts[0]["feedback"] == []
    assert "assertion failed on attempt 1" in attempts[1]["feedback"][0]
    transitions = [e.payload["to"] for e in _events(engine, EventType.STAGE_STATE)]
    assert transitions.count("RETRYING") == 2
    assert len(_events(engine, EventType.ARTIFACT_RECORDED)) == 3  # every attempt is versioned


async def test_retries_exhausted_fails_stage_and_skips_downstream(build_engine, recorder):
    workflow = {"name": "w", "stages": [
        {"id": "impl", "agent": "x", "retry": {"max_attempts": 2}, "exit_gates": ["fail_until"]},
        {"id": "test", "agent": "x", "needs": ["impl"]},
        {"id": "independent", "agent": "x"},
    ]}
    engine = build_engine(workflow, {"x": make_agent(recorder)})
    result = await engine.run()

    assert not result.succeeded
    assert result.states == {"impl": S.FAILED, "test": S.SKIPPED, "independent": S.SUCCEEDED}
    assert len(recorder.attempts("impl")) == 2
    assert recorder.attempts("test") == []


async def test_agent_exception_is_retried(build_engine, recorder):
    def flaky(ctx):
        if ctx.attempt == 1:
            raise TimeoutError("LLM timeout")

    workflow = {"name": "w", "stages": [{"id": "s", "agent": "x", "retry": {"max_attempts": 2}}]}
    engine = build_engine(workflow, {"x": make_agent(recorder, behaviour=flaky)})
    assert (await engine.run()).succeeded
    assert "LLM timeout" in recorder.attempts("s")[1]["feedback"][0]
    assert len(_events(engine, EventType.AGENT_ERROR)) == 1


async def test_rejected_approval_fails_stage_and_skips_downstream(build_engine, recorder):
    workflow = {"name": "w", "stages": [
        {"id": "design", "agent": "x", "approval": "required"},
        {"id": "impl", "agent": "x", "needs": ["design"]},
    ]}
    engine = build_engine(workflow, {"x": make_agent(recorder)}, approver=AutoApprover(approve=False))
    result = await engine.run()

    assert result.states == {"design": S.FAILED, "impl": S.SKIPPED}
    decided = _events(engine, EventType.APPROVAL_DECIDED)
    assert len(decided) == 1 and decided[0].payload["approved"] is False


async def test_approval_happens_after_gates_pass(build_engine, recorder):
    workflow = {"name": "w", "stages": [
        {"id": "design", "agent": "x", "approval": "required", "exit_gates": ["fail"]},
    ]}
    engine = build_engine(workflow, {"x": make_agent(recorder)})
    await engine.run()
    assert _events(engine, EventType.APPROVAL_REQUESTED) == [], "humans only review verified output"


async def test_out_of_scope_write_fails_without_retry(build_engine, recorder, tmp_path):
    def rogue(ctx):
        ctx.write_file("src/main/App.java", "ok")
        ctx.write_file("../../etc/passwd", "nope")

    workflow = {"name": "w", "stages": [
        {"id": "coder", "agent": "x", "write_scope": ["src/main/**"], "retry": {"max_attempts": 3}},
    ]}
    engine = build_engine(workflow, {"x": make_agent(recorder, behaviour=rogue)})
    result = await engine.run()

    assert result.states["coder"] is S.FAILED
    assert len(recorder.attempts("coder")) == 1, "policy violations are not retried"
    assert not (tmp_path / "etc").exists()
    last = _events(engine, EventType.STAGE_STATE)[-1]
    assert last.payload["reason"].startswith("policy:")


async def test_write_outside_scope_glob_is_rejected(build_engine, recorder):
    def sneaky(ctx):
        ctx.write_file("src/test/Hack.java", "x")

    workflow = {"name": "w", "stages": [{"id": "coder", "agent": "x", "write_scope": ["src/main/**"]}]}
    engine = build_engine(workflow, {"x": make_agent(recorder, behaviour=sneaky)})
    assert (await engine.run()).states["coder"] is S.FAILED


async def test_failed_entry_gate_blocks_stage(build_engine, recorder):
    workflow = {"name": "w", "stages": [
        {"id": "release", "agent": "x", "entry_gates": ["fail"]},
        {"id": "after", "agent": "x", "needs": ["release"]},
    ]}
    engine = build_engine(workflow, {"x": make_agent(recorder)})
    result = await engine.run()
    assert result.states == {"release": S.BLOCKED, "after": S.SKIPPED}
    assert recorder.calls == [], "agent never runs when entry gate fails"


async def test_preflight_rejects_unknown_agent_before_side_effects(build_engine, recorder):
    workflow = {"name": "w", "stages": [{"id": "s", "agent": "ghost"}]}
    engine = build_engine(workflow, {"x": make_agent(recorder)})
    with pytest.raises(ValueError, match="unknown agent 'ghost'"):
        await engine.run()
    assert not engine.events.path.exists()


async def test_downstream_receives_upstream_artifacts_with_lineage(build_engine, recorder):
    seen = {}

    def capture(ctx):
        seen[ctx.stage.id] = sorted(ctx.inputs)

    engine = build_engine(DIAMOND, {"fast": make_agent(recorder, behaviour=capture),
                                    "slow": make_agent(recorder, behaviour=capture)})
    await engine.run()
    assert seen["d"] == ["a", "b", "c"], "transitive ancestors, not only direct needs"
    assert seen["b"] == ["a"]
    d_artifact = [e for e in _events(engine, EventType.ARTIFACT_RECORDED) if e.stage == "d"][0]
    assert {i["name"] for i in d_artifact.payload["inputs"]} == {"a", "b", "c"}


async def test_event_log_is_source_of_truth(build_engine, recorder):
    engine = build_engine(DIAMOND, {"fast": make_agent(recorder), "slow": make_agent(recorder)})
    result = await engine.run()
    assert replay_states(EventStore.load(engine.events.path)) == result.states
    ok, msg = EventStore.verify(engine.events.path)
    assert ok, msg
