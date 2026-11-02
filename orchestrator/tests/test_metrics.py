"""Step 6: metrics derived from event logs produced by real engine runs with known faults."""

import asyncio
import json

import pytest

from orchestrator.approvals.service import ApprovalDecision, AutoApprover
from orchestrator.cli import main as orch
from orchestrator.engine.events import EventStore
from orchestrator.observability.metrics import Portfolio, compute
from orchestrator.observability.report import render_portfolio, render_run

from .conftest import make_agent
from .test_resilience import ScriptedApprover


def wf(*stages):
    return {"name": "w", "stages": list(stages)}


def stage(id_="impl", **kw):
    return {"id": id_, "agent": "x", "write_scope": ["src/**"], **kw}


async def metrics_of(engine, resume=False):
    await engine.run(resume=resume)
    return compute(EventStore.load(engine.events.path))


async def test_a_clean_run(build_engine, recorder):
    m = await metrics_of(build_engine(wf(stage("a"), stage("b", needs=["a"])), {"x": make_agent(recorder)}))
    assert m.status == "SUCCEEDED" and m.stage_success_rate == 1.0
    assert m.incidents == [] and m.mttr_seconds is None and sum(m.retries.values()) == 0
    assert m.processes == 1 and m.stopped_seconds == 0


async def test_failure_retry_rollback_and_recovery_are_measured(build_engine, recorder):
    def coder(ctx):
        ctx.write_file("src/App.java", f"attempt {ctx.attempt}")

    engine = build_engine(wf(stage(retry={"max_attempts": 3}, exit_gates=[{"name": "fail_until", "args": {"pass_on": 3}}])),
                          {"x": make_agent(recorder, delay=0.05, behaviour=coder)})
    m = await metrics_of(engine)
    assert m.status == "SUCCEEDED"
    assert m.retries["failure"] == 2
    assert m.rollbacks == 2, "each failed attempt's applied change set was reverted"
    [incident] = m.incidents
    assert incident.stage == "impl" and incident.closed is not None
    assert m.mttr_seconds == pytest.approx(incident.seconds) and m.mttr_seconds >= 0.1
    assert m.gates == {"passed": 1, "failed": 2}


async def test_recovery_ends_when_the_work_passes_its_gates_not_when_a_person_signs_off(build_engine, recorder):
    """live-bugfix-2 reported an MTTR of 8.7 h: the fix passed its gates within a minute, then waited
    hours for an approval. Waiting for a sign-off is human wait, not repair time."""
    class SlowApprover(AutoApprover):
        async def decide(self, request):
            await asyncio.sleep(0.6)
            return await super().decide(request)

    engine = build_engine(wf(stage(retry={"max_attempts": 2}, approval="required",
                                   exit_gates=[{"name": "fail_until", "args": {"pass_on": 2}}])),
                          {"x": make_agent(recorder, delay=0.05)}, approver=SlowApprover())
    m = await metrics_of(engine)
    [incident] = m.incidents
    assert incident.closed is not None and incident.seconds < 0.5, "the approval wait is not repair time"
    assert m.human_wait_seconds >= 0.6, "it is counted as human wait instead"


async def test_an_unrecovered_failure_and_skips(build_engine, recorder):
    m = await metrics_of(build_engine(
        wf(stage("a", exit_gates=["fail"]), stage("b", needs=["a"]), stage("c", needs=["b"])),
        {"x": make_agent(recorder)}))
    assert m.status == "FAILED"
    assert m.stage_success_rate == 0.0, "skipped stages never ran and do not dilute the rate"
    assert m.stage_outcomes["SKIPPED"] == 2
    [incident] = m.incidents
    assert incident.closed is None and m.mttr_seconds is None


async def test_clarifications_and_change_requests_are_not_failures(build_engine, recorder):
    engine = build_engine(wf(stage(approval="required", max_revisions=1)), {"x": make_agent(recorder)},
                          approver=ScriptedApprover((False, "rename it"), (True, "")))
    m = await metrics_of(engine)
    assert m.retries == {"change_request": 1} and m.incidents == []
    h = m.human_decisions
    assert h["approvals"] == 2 and h["rejected"] == 1 and h["change_requests"] == 1


async def test_human_wait_is_separated_from_active_time(build_engine, recorder):
    class SlowHuman(AutoApprover):
        async def decide(self, request):
            await asyncio.sleep(0.3)
            return ApprovalDecision(approved=True, approver="person")

    m = await metrics_of(build_engine(wf(stage(approval="required")), {"x": make_agent(recorder, delay=0.05)},
                                      approver=SlowHuman()))
    assert m.human_wait_seconds == pytest.approx(0.3, abs=0.1)
    assert m.approvals[0]["wait_seconds"] == pytest.approx(0.3, abs=0.1)
    assert m.active_seconds < m.wall_seconds - 0.2


async def test_a_resume_counts_stopped_time_and_does_not_double_count_decisions(build_engine, recorder, tmp_path):
    from orchestrator.engine.scheduler import STOP_FILE

    def stop_after_a(ctx):
        if ctx.stage.id == "a":
            (tmp_path / "run" / STOP_FILE).write_text("stop")

    workflow = wf(stage("a", approval="required"), stage("b", needs=["a"]))
    await build_engine(workflow, {"x": make_agent(recorder, behaviour=stop_after_a)}).run()
    await asyncio.sleep(0.3)  # the run sits stopped
    m = await metrics_of(build_engine(workflow, {"x": make_agent(recorder)}), resume=True)

    assert m.status == "SUCCEEDED" and m.processes == 2
    assert m.stopped_seconds >= 0.25
    assert m.human_decisions["approvals"] == 1


async def test_parallel_human_waits_count_once(build_engine, recorder):
    class SlowHuman(AutoApprover):
        async def decide(self, request):
            await asyncio.sleep(0.3)
            return ApprovalDecision(approved=True, approver="person")

    m = await metrics_of(build_engine(
        wf(stage("a"), stage("b", needs=["a"], approval="required"), stage("c", needs=["a"], approval="required")),
        {"x": make_agent(recorder)}, approver=SlowHuman()))
    assert sum(s["human_wait_seconds"] for s in m.stages.values()) == pytest.approx(0.6, abs=0.15)
    assert m.human_wait_seconds == pytest.approx(0.3, abs=0.1), "two stages waiting at once is one human wait"


async def test_reports_render_and_aggregate(build_engine, recorder, tmp_path):
    ok = await metrics_of(build_engine(wf(stage("a")), {"x": make_agent(recorder)}))
    md = render_run(ok)
    for section in ("## Reliability", "## Latency", "## Human oversight", "## LLM usage", "```mermaid", "gantt"):
        assert section in md
    portfolio = Portfolio([ok])
    assert portfolio.as_dict()["run_success_rate"] == 1.0
    assert "| Runs (succeeded) | 1 (100%) |" in render_portfolio(portfolio)
    json.dumps(ok.as_dict(), default=str)


async def test_cli_report_refuses_a_tampered_log_and_emits_json(build_engine, recorder, tmp_path, capsys):
    engine = build_engine(wf(stage("a")), {"x": make_agent(recorder)})
    await engine.run()
    base = ["--env-file", str(tmp_path / "none"), "--runs-dir", str(tmp_path)]
    assert orch(base + ["report", "run", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "SUCCEEDED"
    assert orch(base + ["report", "--all"]) == 0
    assert "Delivery metrics across runs" in capsys.readouterr().out

    lines = engine.events.path.read_text().splitlines()
    lines[1] = lines[1].replace("PENDING", "FAILED", 1)
    engine.events.path.write_text("\n".join(lines) + "\n")
    assert orch(base + ["report", "run"]) == 2
    assert "unverifiable" in capsys.readouterr().err


async def test_a_fallback_is_an_incident_recovered_by_the_fallback_agent(build_engine, recorder):
    from orchestrator.agents.base import FatalAgentError

    def refuse(ctx):
        raise FatalAgentError("declined")

    m = await metrics_of(build_engine(wf(stage(fallback="y")), {"x": make_agent(recorder, behaviour=refuse),
                                                                "y": make_agent(recorder)}))
    assert m.status == "SUCCEEDED" and m.retries == {"fallback": 1}
    [incident] = m.incidents
    assert incident.closed is not None and m.mttr_seconds is not None
