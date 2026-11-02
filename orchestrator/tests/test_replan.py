"""Step 5: dynamic re-planning. Invalidate upstream, re-run only what its change actually reaches."""

import pytest

from orchestrator.engine.events import EventStore, EventType
from orchestrator.engine.models import AgentResult
from orchestrator.engine.scheduler import ResumeError
from orchestrator.engine.state import NodeState

from .conftest import make_agent
from .test_resilience import ScriptedApprover

S = NodeState

#   spec ──► impact ──┬──► implement ──┐
#                     └──► test_plan ──┴──► test          docs (independent of impact)
WORKFLOW = {"name": "w", "stages": [
    {"id": "spec", "agent": "x"},
    {"id": "impact", "agent": "x", "needs": ["spec"]},
    {"id": "implement", "agent": "x", "needs": ["impact"]},
    {"id": "test_plan", "agent": "x", "needs": ["impact"]},
    {"id": "test", "agent": "x", "needs": ["implement", "test_plan"]},
    {"id": "docs", "agent": "x", "needs": ["spec"]},
]}


def events(engine, type_=None):
    return [e for e in EventStore.load(engine.events.path) if type_ is None or e.type == type_]


def varying(versions: dict):
    """An agent whose output for a stage is whatever version the test currently says."""
    def behaviour(ctx):
        return AgentResult(summary=f"{ctx.stage.id} output v{versions.get(ctx.stage.id, 1)}")
    return behaviour


async def finished_run(build_engine, recorder, versions):
    engine = build_engine(WORKFLOW, {"x": make_agent(recorder, behaviour=varying(versions))})
    assert (await engine.run()).succeeded
    recorder.calls.clear()
    return engine


async def test_unchanged_output_stops_the_replan_where_it_is(build_engine, recorder):
    """Re-running impact yields the same output: nothing downstream is rebuilt."""
    versions = {}
    await finished_run(build_engine, recorder, versions)

    replanned = build_engine(WORKFLOW, {"x": make_agent(recorder, behaviour=varying(versions))})
    result = await replanned.run(resume=True, replan_from=["impact"], replan_reason="reviewer asked for a re-check")

    assert result.succeeded
    assert [c["stage"] for c in recorder.calls] == ["impact"], "only the requested stage ran"
    reused = {e.stage for e in events(replanned, EventType.ARTIFACT_ACCEPTED) if e.payload.get("reused")}
    assert reused == {"implement", "test_plan", "test"}
    [plan] = events(replanned, EventType.RUN_REPLANNED)
    assert plan.payload["reason"] == "reviewer asked for a re-check"
    assert set(plan.payload["stale"]) == {"impact", "implement", "test_plan", "test"}
    assert plan.payload["forced"] == ["impact"]
    assert "docs" not in plan.payload["stale"] and "spec" not in plan.payload["stale"]


async def test_changed_output_re_runs_exactly_what_depends_on_it(build_engine, recorder):
    versions = {}
    await finished_run(build_engine, recorder, versions)

    versions["impact"] = 2  # the re-run produces a different impact plan
    replanned = build_engine(WORKFLOW, {"x": make_agent(recorder, behaviour=varying(versions))})
    assert (await replanned.run(resume=True, replan_from=["impact"])).succeeded

    assert sorted(c["stage"] for c in recorder.calls) == ["impact", "implement", "test", "test_plan"]
    assert replanned.artifacts["impact"].version == 2
    implement = replanned.artifacts["implement"]
    assert {(r.name, r.version) for r in implement.inputs} >= {("impact", 2)}, "lineage points at the new plan"
    reasons = [e.payload["reason"] for e in events(replanned, EventType.STAGE_STATE)
               if e.stage == "implement" and e.payload["to"] == "READY"]
    assert any("inputs changed (impact)" in r for r in reasons)


async def test_a_change_in_one_branch_never_touches_its_sibling(build_engine, recorder):
    """Re-planning implement re-runs implement and its dependant (test) only: the sibling branch
    (test_plan), the stages above (spec, impact) and the unrelated docs are not even marked stale."""
    versions = {}
    await finished_run(build_engine, recorder, versions)

    versions["implement"] = 2
    replanned = build_engine(WORKFLOW, {"x": make_agent(recorder, behaviour=varying(versions))})
    assert (await replanned.run(resume=True, replan_from=["implement"])).succeeded

    assert sorted(c["stage"] for c in recorder.calls) == ["implement", "test"]
    [plan] = events(replanned, EventType.RUN_REPLANNED)
    assert sorted(plan.payload["stale"]) == ["implement", "test"]
    for untouched in ("spec", "impact", "test_plan", "docs"):
        assert replanned.artifacts[untouched].version == 1, untouched


GATED = {"name": "w", "stages": [
    {"id": "spec", "agent": "x"},
    {"id": "impact", "agent": "x", "needs": ["spec"], "approval": "required"},
    {"id": "implement", "agent": "x", "needs": ["impact"], "approval": "required"},
]}


async def test_a_reused_stage_asks_for_no_new_approval(build_engine, recorder):
    versions = {}
    first = build_engine(GATED, {"x": make_agent(recorder, behaviour=varying(versions))},
                         approver=ScriptedApprover((True, ""), (True, "")))
    assert (await first.run()).succeeded

    # spec is re-run but reproduces its output, so impact and implement are reused as approved
    nobody = ScriptedApprover()  # holds no decisions: any approval request would fail this run
    replanned = build_engine(GATED, {"x": make_agent(recorder, behaviour=varying(versions))}, approver=nobody)
    assert (await replanned.run(resume=True, replan_from=["spec"])).succeeded
    assert events(replanned, EventType.APPROVAL_REQUESTED)[len(events(first, EventType.APPROVAL_REQUESTED)):] == []


async def test_a_stage_re_run_with_new_content_needs_a_fresh_approval(build_engine, recorder):
    versions = {}
    first = build_engine(GATED, {"x": make_agent(recorder, behaviour=varying(versions))},
                         approver=ScriptedApprover((True, ""), (True, "")))
    assert (await first.run()).succeeded
    asked_before = len(events(first, EventType.APPROVAL_REQUESTED))

    versions["impact"] = 2
    replanned = build_engine(GATED, {"x": make_agent(recorder, behaviour=varying(versions))},
                             approver=ScriptedApprover((True, ""), (True, "")))
    assert (await replanned.run(resume=True, replan_from=["impact"])).succeeded
    asked = [e for e in events(replanned, EventType.APPROVAL_REQUESTED)][asked_before:]
    assert [e.stage for e in asked] == ["impact", "implement"]
    assert asked[0].payload["artifact"]["version"] == 2, "the human approves the new content, not the old"


async def test_requirement_change_on_resume_is_detected_and_lineage_bounds_its_reach(build_engine, recorder):
    versions = {}
    await finished_run(build_engine, recorder, versions)

    # The spec agent ignores the wording change (same output), so everything downstream is reused.
    replanned = build_engine(WORKFLOW, {"x": make_agent(recorder, behaviour=varying(versions))},
                             requirement="test requirement, now with a clarified sentence")
    assert (await replanned.run(resume=True)).succeeded
    assert [c["stage"] for c in recorder.calls] == ["spec"]
    [plan] = events(replanned, EventType.RUN_REPLANNED)
    assert plan.payload["requirement_changed"] is True and plan.payload["forced"] == ["spec"]
    assert len(events(replanned, EventType.ARTIFACT_ACCEPTED)) >= 5

    # A second resume with that same requirement is not a change any more.
    again = build_engine(WORKFLOW, {"x": make_agent(recorder)},
                         requirement="test requirement, now with a clarified sentence")
    recorder.calls.clear()
    assert (await again.run(resume=True)).succeeded
    assert recorder.calls == [] and len(events(again, EventType.RUN_REPLANNED)) == 1


async def test_replanning_an_unknown_stage_is_refused(build_engine, recorder):
    await finished_run(build_engine, recorder, {})
    with pytest.raises(ResumeError, match="unknown stage"):
        await build_engine(WORKFLOW, {"x": make_agent(recorder)}).run(resume=True, replan_from=["nope"])


async def test_replan_requires_an_existing_run(build_engine, recorder):
    with pytest.raises(ValueError, match="existing run"):
        await build_engine(WORKFLOW, {"x": make_agent(recorder)}).run(replan_from=["impact"])


async def test_replanned_log_still_verifies(build_engine, recorder):
    await finished_run(build_engine, recorder, {})
    replanned = build_engine(WORKFLOW, {"x": make_agent(recorder)})
    await replanned.run(resume=True, replan_from=["spec"])
    ok, msg = EventStore.verify(replanned.events.path)
    assert ok, msg


async def test_replanning_a_failed_stage_is_recorded_with_its_reason(build_engine, recorder):
    """A re-plan aimed at a stage that failed re-runs it, and the audit log says so and why
    (found in the live lifecycle run: it used to be recorded as a plain resume)."""
    from orchestrator.engine.scheduler import FatalAgentError

    def test_fails(ctx):
        if ctx.stage.id == "test":
            raise FatalAgentError("broken prompt")

    first = build_engine(WORKFLOW, {"x": make_agent(recorder, behaviour=test_fails)})
    assert not (await first.run()).succeeded
    recorder.calls.clear()

    replanned = build_engine(WORKFLOW, {"x": make_agent(recorder)})
    result = await replanned.run(resume=True, replan_from=["test"], replan_reason="prompt fixed")

    assert result.succeeded
    assert [c["stage"] for c in recorder.calls] == ["test"]
    [plan] = events(replanned, EventType.RUN_REPLANNED)
    assert plan.payload["reason"] == "prompt fixed"
    assert plan.payload["rerun"] == ["test"] and plan.payload["stale"] == []


async def test_a_plain_resume_of_a_failed_run_is_not_a_replan(build_engine, recorder):
    from orchestrator.engine.scheduler import FatalAgentError

    def test_fails(ctx):
        if ctx.stage.id == "test":
            raise FatalAgentError("transient")

    assert not (await build_engine(WORKFLOW, {"x": make_agent(recorder, behaviour=test_fails)}).run()).succeeded
    resumed = build_engine(WORKFLOW, {"x": make_agent(recorder)})
    assert (await resumed.run(resume=True)).succeeded
    assert events(resumed, EventType.RUN_REPLANNED) == []
