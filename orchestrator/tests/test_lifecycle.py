"""The full lifecycle: design, documentation and release stages, their gates, and entry gates."""

import shutil
from pathlib import Path

import pytest
import yaml

from orchestrator.agents.stubs import TEMPLATES, stub_agents
from orchestrator.approvals.service import AutoApprover
from orchestrator.engine.dag import load_workflow
from orchestrator.engine.events import EventStore, EventType
from orchestrator.engine.models import AgentResult, Artifact, StageSpec
from orchestrator.engine.scheduler import Engine
from orchestrator.engine.state import NodeState
from orchestrator.gates.api import (ChecklistPassedGate, DocsCoverApiGate, OpenApiConformanceGate,
                                    OpenApiValidGate, code_operations)
from orchestrator.gates.base import GateContext
from orchestrator.gates.builtin import builtin_gates
from orchestrator.policy.engine import PolicyEngine

ROOT = Path(__file__).resolve().parents[2]

CODE = [{"name": "code", "in": "path", "required": True, "schema": {"type": "string"}}]
SPEC = {
    "openapi": "3.0.3", "info": {"title": "t", "version": "1"},
    "paths": {
        "/api/links": {"post": {"responses": {"201": {"description": "created"}}}},
        "/api/links/{code}": {"parameters": CODE,
                              "get": {"responses": {"200": {"description": "ok"}}},
                              "delete": {"responses": {"204": {"description": "gone"}}}},
        "/{code}": {"parameters": CODE, "get": {"responses": {"302": {"description": "redirect"}}}},
    },
}
CONTROLLER = '''
@RestController
@RequestMapping("/api/links")
public class LinkController {
    @PostMapping
    public Object create() { return null; }
    @GetMapping("/{code}")
    public Object metadata() { return null; }
    @DeleteMapping("/{code}")
    public Object delete() { return null; }
}
'''
REDIRECT = '''
@RestController
public class RedirectController {
    @GetMapping("/{code:[A-Za-z0-9_-]{3,32}}")
    public Object redirect() { return null; }
}
'''
ERRORS = '''
@RestController
public class ApiErrorController implements ErrorController {
    @RequestMapping("${server.error.path:/error}")
    public Object error() { return null; }
}
'''


def ctx(workspace, artifact=None):
    return GateContext(StageSpec(id="s", agent="x"), workspace, artifact, {})


def write(ws: Path, rel: str, text: str):
    (ws / rel).parent.mkdir(parents=True, exist_ok=True)
    (ws / rel).write_text(text)


def service(ws, spec=SPEC, extra_controller=""):
    write(ws, "svc/openapi.yaml", yaml.safe_dump(spec))
    write(ws, "svc/src/LinkController.java", CONTROLLER)
    write(ws, "svc/src/RedirectController.java", REDIRECT)
    write(ws, "svc/src/ApiErrorController.java", ERRORS)
    if extra_controller:
        write(ws, "svc/src/Extra.java", extra_controller)


# --- gates -----------------------------------------------------------------------------------

async def test_openapi_valid_accepts_a_valid_definition_and_rejects_others(tmp_path):
    service(tmp_path)
    assert (await OpenApiValidGate(path="svc/openapi.yaml").check(ctx(tmp_path))).passed
    write(tmp_path, "bad.yaml", yaml.safe_dump({"openapi": "3.0.3", "info": {"title": "no version"}, "paths": {}}))
    bad = await OpenApiValidGate(path="bad.yaml").check(ctx(tmp_path))
    assert not bad.passed and "version" in bad.evidence
    assert not (await OpenApiValidGate(path="missing.yaml").check(ctx(tmp_path))).passed
    empty = {**SPEC, "paths": {}}
    write(tmp_path, "empty.yaml", yaml.safe_dump(empty))
    assert "no operations" in (await OpenApiValidGate(path="empty.yaml").check(ctx(tmp_path))).evidence


def test_the_scanner_reads_spring_mappings_like_the_router_does(tmp_path):
    service(tmp_path)
    assert code_operations(tmp_path / "svc/src") == {
        ("POST", "/api/links"), ("GET", "/api/links/{code}"), ("DELETE", "/api/links/{code}"), ("GET", "/{code}")}


async def test_conformance_passes_when_definition_and_code_agree(tmp_path):
    service(tmp_path)
    result = await OpenApiConformanceGate(spec="svc/openapi.yaml", source="svc/src").check(ctx(tmp_path))
    assert result.passed, result.evidence


async def test_conformance_catches_an_undocumented_endpoint(tmp_path):
    service(tmp_path, extra_controller='@RestController\nclass Extra {\n @PatchMapping("/api/links/{code}")\n'
                                       ' Object patch() { return null; }\n}\n')
    result = await OpenApiConformanceGate(spec="svc/openapi.yaml", source="svc/src").check(ctx(tmp_path))
    assert not result.passed and "implemented but not documented: PATCH /api/links/{code}" in result.evidence


async def test_conformance_catches_a_documented_operation_that_was_not_built(tmp_path):
    spec = {**SPEC, "paths": {**SPEC["paths"], "/api/links/{code}/stats": {
        "parameters": CODE, "get": {"responses": {"200": {"description": "x"}}}}}}
    service(tmp_path, spec=spec)
    result = await OpenApiConformanceGate(spec="svc/openapi.yaml", source="svc/src").check(ctx(tmp_path))
    assert not result.passed and "documented but not implemented: GET /api/links/{code}/stats" in result.evidence


async def test_docs_must_cover_every_path(tmp_path):
    service(tmp_path)
    write(tmp_path, "svc/README.md", "Create with POST /api/links; redirect with GET /{code}.")
    gate = DocsCoverApiGate(spec="svc/openapi.yaml", docs=["svc/README.md"])
    result = await gate.check(ctx(tmp_path))
    assert not result.passed and "/api/links/{code}" in result.evidence
    write(tmp_path, "svc/README.md", "POST /api/links · GET/DELETE /api/links/{code} · GET /{code}")
    assert (await gate.check(ctx(tmp_path))).passed
    assert not (await DocsCoverApiGate(spec="svc/openapi.yaml", docs=["nope.md"]).check(ctx(tmp_path))).passed


async def test_a_failing_or_unexplained_checklist_item_blocks_the_release(tmp_path):
    def artifact(items):
        return Artifact(name="release", version=1, sha="x", produced_by="release/release#1",
                        result=AgentResult(summary="", outputs={"checklist": items}))

    gate = ChecklistPassedGate()
    ok = [{"item": "tests", "status": "pass", "evidence": "121 passed"},
          {"item": "migrations", "status": "n/a", "evidence": "no schema change"}]
    assert (await gate.check(ctx(tmp_path, artifact(ok)))).passed
    failing = await gate.check(ctx(tmp_path, artifact(ok + [{"item": "docs", "status": "fail", "evidence": ""}])))
    assert not failing.passed and "docs" in failing.evidence
    unexplained = await gate.check(ctx(tmp_path, artifact([{"item": "rollback", "status": "n/a", "evidence": ""}])))
    assert not unexplained.passed
    assert not (await gate.check(ctx(tmp_path, artifact([])))).passed


# --- the workflow ----------------------------------------------------------------------------

def lifecycle_for_skeleton():
    """The lifecycle workflow sized for the 4-test skeleton template: its test-count floor and overall
    coverage (84%) are the template's; the release smoke steps exercise the real service's API, so they
    are tested against it in test_release_gates.py instead."""
    wf = load_workflow(ROOT / "workflows" / "lifecycle.yaml")
    for stage_id in ("test", "release"):
        stage = wf.stage(stage_id)
        stage.entry_gates = [g for g in stage.entry_gates if g.name != "service_smoke"]
        for gate in stage.entry_gates + stage.exit_gates:
            if gate.name == "maven_test":
                gate.args["min_tests"] = 4
            if gate.name == "coverage":
                gate.args["min_line"] = 80
    return wf


def test_lifecycle_workflow_covers_the_sdlc_with_entry_gates():
    wf = load_workflow(ROOT / "workflows" / "lifecycle.yaml")
    assert [s.id for s in wf.stages] == ["requirements", "impact", "design", "implement", "test_plan", "test",
                                         "docs", "release"]
    assert {s.id for s in wf.stages if s.entry_gates} == {"implement", "release"}
    assert {s.id for s in wf.stages if s.approval.value == "required"} == {"requirements", "impact", "design", "release"}


async def test_an_entry_gate_blocks_implementation_without_a_valid_design(tmp_path):
    wf = lifecycle_for_skeleton()
    wf.stage("design").exit_gates = []  # pretend the design stage let a broken definition through
    engine = Engine(wf, stub_agents(), builtin_gates(), AutoApprover(), policy=PolicyEngine.permissive(),
                    run_id="lc", run_dir=tmp_path / "run", workspace=tmp_path / "ws",
                    requirement=(ROOT / "scenarios" / "greenfield.md").read_text())

    class BrokenArchitect(stub_agents().create("architect").__class__):
        async def run(self, ctx):
            ctx.write_file("url-shortener/openapi.yaml", "openapi: 3.0.3\npaths: {}\n")
            return AgentResult(summary="broken")

    engine.agents.register("architect", BrokenArchitect)
    result = await engine.run()
    assert result.states["implement"] is NodeState.BLOCKED
    assert result.states["release"] is NodeState.SKIPPED
    entry = [e for e in EventStore.load(engine.events.path)
             if e.type == EventType.GATE_RESULT and e.payload["phase"] == "entry"]
    assert entry and not entry[0].payload["passed"]


@pytest.mark.maven
@pytest.mark.skipif(shutil.which("mvn") is None, reason="Maven not installed")
async def test_full_lifecycle_runs_end_to_end_with_stub_agents(tmp_path):
    engine = Engine(lifecycle_for_skeleton(), stub_agents(), builtin_gates(), AutoApprover(),
                    policy=PolicyEngine.load(ROOT / "policies" / "default.yaml"), run_id="lc",
                    run_dir=tmp_path / "run", workspace=tmp_path / "ws",
                    requirement=(ROOT / "scenarios" / "greenfield.md").read_text())
    result = await engine.run()
    assert result.succeeded, result.states
    events = EventStore.load(engine.events.path)
    gates = {(e.stage, e.payload["phase"], e.payload["gate"]): e.payload["passed"]
             for e in events if e.type == EventType.GATE_RESULT}
    assert gates[("implement", "entry", "openapi_valid")] and gates[("implement", "exit", "openapi_conformance")]
    assert gates[("release", "entry", "maven_test")] and gates[("docs", "exit", "docs_cover_api")]
    ws = tmp_path / "ws" / "url-shortener"
    for produced in ("openapi.yaml", "docs/design.md", "README.md", "docs/api.md", "CHANGELOG.md"):
        assert (ws / produced).exists(), produced
