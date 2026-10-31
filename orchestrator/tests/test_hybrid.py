"""Hybrid execution: session-served agents, persisted approvals, cost safe-stop."""

import asyncio
import json
import shutil
from pathlib import Path

import pytest

from orchestrator.agents.base import FatalAgentError
from orchestrator.agents.llm_agents import llm_agents
from orchestrator.approvals.service import (ApprovalRequest, AutoApprover, FileApprover,
                                            pending_approvals, record_decision)
from orchestrator.cli import main as orch
from orchestrator.engine.dag import load_workflow
from orchestrator.engine.events import EventStore, EventType
from orchestrator.engine.scheduler import Engine
from orchestrator.engine.state import NodeState
from orchestrator.gates.builtin import builtin_gates
from orchestrator.llm.client import LLMRequest, LLMResponse, Usage
from orchestrator.llm.session import SESSION_MODEL, RoutedLLM, SessionLLM
from orchestrator.policy.engine import PolicyEngine

from .test_llm_agents import PLAN, REQUIREMENT, SPEC, ScriptedLLM, code, template_files

ROOT = Path(__file__).resolve().parents[2]
POLICY = PolicyEngine.load(ROOT / "policies" / "default.yaml")


def _request(agent="coder", user="task"):
    return LLMRequest(agent=agent, model="m", system="sys", user=user,
                      schema={"type": "object", "required": ["summary"]})


async def _answer_when_asked(directory: Path, agent: str, data: dict, timeout=10.0):
    """Plays the assistant session: waits for a request file and writes the response."""
    for _ in range(int(timeout / 0.02)):
        reqs = sorted(directory.glob(f"{agent}-*.request.json"))
        if reqs:
            req = reqs[-1]
            req.with_name(req.name.replace(".request.json", ".response.json")).write_text(json.dumps(data))
            return json.loads(req.read_text())
        await asyncio.sleep(0.02)
    raise AssertionError(f"no {agent} request appeared")


# --- session backend ---------------------------------------------------------------------

async def test_session_request_is_written_and_answer_is_picked_up(tmp_path):
    llm = SessionLLM(tmp_path, poll_seconds=0.01)
    answered, response = await asyncio.gather(
        _answer_when_asked(tmp_path, "coder", {"summary": "done"}),
        llm.complete(_request()),
    )
    assert answered["user"] == "task" and answered["schema"]["required"] == ["summary"]
    prompt = next(tmp_path.glob("coder-*.prompt.md")).read_text()
    assert "## System prompt" in prompt and "## Output schema" in prompt
    assert response.data == {"summary": "done"}
    assert response.model == SESSION_MODEL and response.source == "session"
    assert response.cost_usd == 0.0 and response.provider == "session"


async def test_session_timeout_is_fatal(tmp_path):
    with pytest.raises(FatalAgentError, match="no session response"):
        await SessionLLM(tmp_path, poll_seconds=0.01, timeout_seconds=0.05).complete(_request())


async def test_router_sends_each_agent_to_its_backend():
    api, session = ScriptedLLM({"analyst": [{"a": 1}]}), ScriptedLLM({"coder": [{"c": 1}]})
    routed = RoutedLLM({"coder": session}, default=api)
    assert (await routed.complete(_request("analyst"))).data == {"a": 1}
    assert (await routed.complete(_request("coder"))).data == {"c": 1}
    with pytest.raises(FatalAgentError):
        await RoutedLLM({}, default=None).complete(_request())


# --- persisted approvals -----------------------------------------------------------------

async def test_file_approval_waits_for_a_recorded_human_decision(tmp_path):
    approver = FileApprover(tmp_path, poll_seconds=0.01)
    req = ApprovalRequest(run_id="r", stage="requirements", reason="workflow", summary="spec")
    task = asyncio.create_task(approver.decide(req))
    await asyncio.sleep(0.05)
    assert not task.done(), "the run must wait for a decision"
    [(approval_id, pending)] = pending_approvals(tmp_path)
    assert approval_id == "requirements-1" and pending.summary == "spec"

    record_decision(tmp_path, approval_id, approved=False, comment="needs 301")
    decision = await asyncio.wait_for(task, 1)
    assert decision.approved is False and decision.comment == "needs 301" and decision.approver
    assert pending_approvals(tmp_path) == []
    with pytest.raises(FileExistsError):
        record_decision(tmp_path, approval_id, approved=True)


# --- cost safe-stop ----------------------------------------------------------------------

class CostlyLLM(ScriptedLLM):
    async def complete(self, request):
        resp = await super().complete(request)
        resp.usage = Usage(output_tokens=100_000)
        resp.cost_usd = 2.00
        return resp


async def test_budget_exhaustion_safe_stops_the_run(tmp_path):
    llm = CostlyLLM({"analyst": [SPEC], "test_planner": [PLAN], "coder": [code([])]})
    engine = Engine(load_workflow(ROOT / "workflows" / "skeleton.yaml"), llm_agents(llm, "m"), builtin_gates(),
                    AutoApprover(), policy=POLICY, run_id="b", run_dir=tmp_path / "run",
                    workspace=tmp_path / "ws", requirement=REQUIREMENT, max_cost_usd=1.0)
    result = await engine.run()

    assert result.states["requirements"] is NodeState.FAILED
    assert all(result.states[s] is NodeState.SKIPPED for s in ("implement", "test_plan", "test"))
    assert [r.agent for r in llm.requests] == ["analyst"], "nothing new starts after the budget is hit"
    events = EventStore.load(engine.events.path)
    assert [e for e in events if e.type == EventType.RUN_HALTED]
    assert events[-1].payload["status"] == "HALTED" and events[-1].payload["cost_usd"] == pytest.approx(2.0)


# --- CLI respond -------------------------------------------------------------------------

def test_respond_packages_a_directory_as_a_code_change(tmp_path):
    req = tmp_path / "coder-abc.request.json"
    req.write_text(json.dumps({"schema": {"required": ["summary", "files", "decisions"]}}))
    src = tmp_path / "out" / "url-shortener" / "src" / "main"
    src.mkdir(parents=True)
    (src / "App.java").write_text("class App {}")
    assert orch(["--env-file", str(tmp_path / "no.env"), "respond", str(req), "--files-from", str(tmp_path / "out"), "--summary", "impl",
                 "--decision", "codes::Base62::short and URL-safe"]) == 0
    data = json.loads((tmp_path / "coder-abc.response.json").read_text())
    assert data["files"] == [{"path": "url-shortener/src/main/App.java", "content": "class App {}"}]
    assert data["decisions"] == [{"topic": "codes", "choice": "Base62", "rationale": "short and URL-safe"}]


# --- hybrid end to end -------------------------------------------------------------------

@pytest.mark.maven
@pytest.mark.skipif(shutil.which("mvn") is None, reason="Maven not installed")
async def test_hybrid_run_api_analyst_session_coder_and_tester(tmp_path):
    api = ScriptedLLM({"analyst": [SPEC], "test_planner": [PLAN]})
    session = SessionLLM(tmp_path / "run" / "llm-requests", poll_seconds=0.02)
    llm = RoutedLLM({"coder": session, "tester": session}, default=api)
    models = {"analyst": "gpt-test", "test_planner": "gpt-test", "coder": SESSION_MODEL, "tester": SESSION_MODEL}
    engine = Engine(load_workflow(ROOT / "workflows" / "skeleton.yaml"), llm_agents(llm, models.get), builtin_gates(),
                    AutoApprover(), policy=POLICY, run_id="h", run_dir=tmp_path / "run",
                    workspace=tmp_path / "ws", requirement=REQUIREMENT)

    async def assistant():
        reqs = tmp_path / "run" / "llm-requests"
        coder_req = await _answer_when_asked(reqs, "coder", code(
            template_files("url-shortener/pom.xml") + template_files("url-shortener/src/main/")), timeout=60)
        tester_req = await _answer_when_asked(reqs, "tester", code(template_files("url-shortener/src/test/")),
                                              timeout=120)
        return coder_req, tester_req

    result, (coder_req, tester_req) = await asyncio.gather(engine.run(), assistant())

    assert result.succeeded, result.states
    assert "approved_specification" in coder_req["user"], "session gets the same context the API would"
    assert "ShortUrlController.java" in tester_req["user"]
    served = {c["agent"]: c["served_model"] for e in EventStore.load(engine.events.path)
              if e.type == EventType.AGENT_COMPLETED for c in e.payload["llm_calls"]}
    assert served["coder"] == served["tester"] == SESSION_MODEL
    assert served["analyst"] == "gpt-test"
