"""Claude-backed agents driven by a scripted LLM, through the real engine, gates and policy."""

import shutil
from pathlib import Path

import pytest

from orchestrator.agents.llm_agents import MAX_CONTEXT_CHARS, llm_agents
from orchestrator.agents.stubs import TEMPLATES
from orchestrator.approvals.service import AutoApprover
from orchestrator.engine.dag import load_workflow
from orchestrator.engine.events import EventStore, EventType
from orchestrator.engine.scheduler import Engine
from orchestrator.engine.state import NodeState
from orchestrator.gates.builtin import builtin_gates
from orchestrator.llm.client import LLMResponse, Usage
from orchestrator.policy.engine import PolicyEngine

ROOT = Path(__file__).resolve().parents[2]
REQUIREMENT = (ROOT / "scenarios" / "greenfield.md").read_text()
POLICY = PolicyEngine.load(ROOT / "policies" / "default.yaml")

SPEC = {
    "summary": "6 FR, 5 NFR, 2 ambiguities resolved",
    "goal": "Shorten URLs and redirect.",
    "functional": [{"id": "FR1", "text": "Create short link"}, {"id": "FR3", "text": "Redirect"}],
    "non_functional": [{"id": "NFR2", "text": "http/https only"}],
    "ambiguities": [{"question": "301 or 302?", "resolution": "302 Found", "source": "assumption",
                     "rationale": "links stay expirable"}],
    "acceptance_criteria": ["POST /api/v1/urls returns 201"],
}
PLAN = {"summary": "3 cases", "decisions": [], "test_cases": [
    {"id": "TC-FR1-01", "covers": "FR1", "level": "integration", "check": "201 with code"}]}


def template_files(prefix: str) -> list[dict]:
    return [{"path": p.relative_to(TEMPLATES).as_posix(), "content": p.read_text()}
            for p in sorted(TEMPLATES.rglob("*")) if p.is_file() and p.relative_to(TEMPLATES).as_posix().startswith(prefix)]


def code(files, summary="change", decisions=()):
    return {"summary": summary, "files": files, "decisions": list(decisions)}


class ScriptedLLM:
    """Returns per-agent responses in order; records every request."""

    def __init__(self, script: dict[str, list]):
        self.script = {k: list(v) for k, v in script.items()}
        self.requests = []

    async def complete(self, request):
        self.requests.append(request)
        nxt = self.script[request.agent].pop(0)
        if isinstance(nxt, Exception):
            raise nxt
        return LLMResponse(data=nxt, model=request.model, stop_reason="end_turn",
                           usage=Usage(input_tokens=1000, output_tokens=200))

    def prompts(self, agent):
        return [r.user for r in self.requests if r.agent == agent]


def engine(tmp_path, llm, workflow=None):
    workflow = workflow or load_workflow(ROOT / "workflows" / "skeleton.yaml")
    return Engine(workflow, llm_agents(llm), builtin_gates(), AutoApprover(), policy=POLICY,
                  run_id="llm", run_dir=tmp_path / "run", workspace=tmp_path / "ws", requirement=REQUIREMENT)


def without(workflow_path, *stage_ids):
    wf = load_workflow(workflow_path)
    wf.stages = [s for s in wf.stages if s.id not in stage_ids]
    return wf


def events(e, type_):
    return [x for x in EventStore.load(e.events.path) if x.type == type_]


async def test_unresolved_ambiguity_from_analyst_stops_the_run(tmp_path):
    spec = {**SPEC, "ambiguities": [{"question": "Who may delete links?", "resolution": None,
                                     "source": "unresolved", "rationale": "product decision"}]}
    llm = ScriptedLLM({"analyst": [spec]})
    result = await engine(tmp_path, llm).run()
    assert result.states["requirements"] is NodeState.FAILED
    assert result.states["implement"] is NodeState.SKIPPED
    assert len(llm.requests) == 1


async def test_policy_violation_is_fed_back_into_the_next_prompt(tmp_path):
    main = template_files("url-shortener/src/main/") + template_files("url-shortener/pom.xml")
    leaky = [dict(f) for f in main]
    svc = next(f for f in leaky if f["path"].endswith("ShortUrlService.java"))
    svc["content"] = svc["content"].replace("public class ShortUrlService {",
                                            'public class ShortUrlService {\n    private static final String API_KEY = "sk-live-abcdef123";')
    llm = ScriptedLLM({"analyst": [SPEC], "test_planner": [PLAN], "coder": [code(leaky), code(main)]})
    wf = without(ROOT / "workflows" / "skeleton.yaml", "test")
    wf.stage("implement").exit_gates = [g for g in wf.stage("implement").exit_gates if g.name != "maven_test"]

    result = await engine(tmp_path, llm, wf).run()

    assert result.succeeded
    first, second = llm.prompts("coder")
    assert "previous_attempt_feedback" not in first
    assert "previous_attempt_feedback" in second and "secrets" in second and "ShortUrlService.java" in second
    assert "API_KEY" not in (tmp_path / "ws" / svc["path"]).read_text()


async def test_coder_sees_only_its_read_scope(tmp_path):
    ws = tmp_path / "ws"
    (ws / "url-shortener" / "src" / "main").mkdir(parents=True)
    (ws / "url-shortener" / "src" / "main" / "Existing.java").write_text("class Existing {}")
    (ws / "secrets.env").write_text("TOKEN=abc")
    llm = ScriptedLLM({"analyst": [SPEC], "test_planner": [PLAN],
                       "coder": [code(template_files("url-shortener/pom.xml"))]})
    wf = without(ROOT / "workflows" / "skeleton.yaml", "test")
    wf.stage("implement").exit_gates = []
    await engine(tmp_path, llm, wf).run()

    [prompt] = llm.prompts("coder")
    assert 'path="url-shortener/src/main/Existing.java"' in prompt
    assert "secrets.env" not in prompt and "TOKEN=abc" not in prompt


async def test_oversized_context_fails_without_retry(tmp_path):
    ws = tmp_path / "ws"
    (ws / "url-shortener" / "src" / "main").mkdir(parents=True)
    (ws / "url-shortener" / "src" / "main" / "Huge.java").write_text("x" * (MAX_CONTEXT_CHARS + 1))
    llm = ScriptedLLM({"analyst": [SPEC], "test_planner": [PLAN], "coder": []})
    result = await engine(tmp_path, llm, without(ROOT / "workflows" / "skeleton.yaml", "test")).run()
    assert result.states["implement"] is NodeState.FAILED
    assert llm.prompts("coder") == [], "no tokens spent on a request we know is too large"


async def test_malformed_output_is_retried(tmp_path):
    llm = ScriptedLLM({"analyst": [{"summary": "oops"}, SPEC]})
    wf = without(ROOT / "workflows" / "skeleton.yaml", "implement", "test_plan", "test")
    wf.stage("requirements").retry.max_attempts = 2
    result = await engine(tmp_path, llm, wf).run()
    assert result.succeeded
    assert "did not match AnalystOutput" in llm.prompts("analyst")[1]


async def test_llm_telemetry_and_cost_are_audited(tmp_path):
    llm = ScriptedLLM({"analyst": [SPEC]})
    e = engine(tmp_path, llm, without(ROOT / "workflows" / "skeleton.yaml", "implement", "test_plan", "test"))
    await e.run()
    [done] = events(e, EventType.AGENT_COMPLETED)
    [call] = done.payload["llm_calls"]
    assert call["requested_model"] == "claude-opus-5-5" and call["cost_usd"] > 0 and len(call["request_key"]) == 64


@pytest.mark.maven
@pytest.mark.skipif(shutil.which("mvn") is None, reason="Maven not installed")
async def test_full_pipeline_with_llm_agents_and_real_build(tmp_path):
    llm = ScriptedLLM({
        "analyst": [SPEC],
        "test_planner": [PLAN],
        "coder": [code(template_files("url-shortener/pom.xml") + template_files("url-shortener/src/main/"))],
        "tester": [code(template_files("url-shortener/src/test/"))],
    })
    result = await engine(tmp_path, llm).run()
    assert result.succeeded, result.states
    tester_prompt = llm.prompts("tester")[0]
    assert "ShortUrlController.java" in tester_prompt, "tester sees the implementation it tests"
    assert "TC-FR1-01" in tester_prompt
