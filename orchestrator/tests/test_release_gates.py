"""Coverage and real-server smoke gates, against a copy of the real service."""

import shutil
import socket
from pathlib import Path

import pytest

from orchestrator.engine.dag import load_workflow
from orchestrator.engine.models import AgentResult, Artifact
from orchestrator.gates.base import GateContext
from orchestrator.gates.coverage import CoverageGate, changed_sources
from orchestrator.gates.smoke import ServiceSmokeGate

ROOT = Path(__file__).resolve().parents[2]
needs_build = pytest.mark.skipif(not (shutil.which("mvn") and shutil.which("java")), reason="Maven and Java needed")
SERVICE = "url-shortener/src/main/java/com/example/shortener"


@pytest.fixture(scope="module")
def service(tmp_path_factory):
    ws = tmp_path_factory.mktemp("ws")
    shutil.copytree(ROOT / "url-shortener", ws / "url-shortener", ignore=shutil.ignore_patterns("target", "data"))
    return ws


def artifact(*written):
    return Artifact(name="s", version=1, sha="x", produced_by="a#1", result=AgentResult(summary="", files_written=list(written)))


def gate_args(workflow, stage, gate, phase="exit_gates"):
    spec = load_workflow(ROOT / "workflows" / f"{workflow}.yaml").stage(stage)
    return next(g.args for g in getattr(spec, phase) if g.name == gate), spec


def test_changed_sources_are_the_production_files_this_stage_and_its_inputs_wrote():
    stage = load_workflow(ROOT / "workflows" / "lifecycle.yaml").stage("test")
    ctx = GateContext(stage, Path("."), artifact("url-shortener/src/test/java/X.java"),
                      {"implement": artifact(f"{SERVICE}/service/LinkService.java", "url-shortener/pom.xml")})
    assert changed_sources(ctx, "url-shortener") == ["com/example/shortener/service/LinkService.java"]


@pytest.mark.maven
@needs_build
async def test_coverage_passes_the_workflows_thresholds_and_names_each_changed_file(service):
    args, stage = gate_args("lifecycle", "test", "coverage")
    ctx = GateContext(stage, service, artifact(), {"implement": artifact(f"{SERVICE}/service/DestinationUrls.java")})
    ok = await CoverageGate(**args).check(ctx)
    assert ok.passed, ok.evidence
    assert "overall line" in ok.evidence and "DestinationUrls.java" in ok.evidence

    strict = await CoverageGate(project="url-shortener", min_line=0, min_changed_line=99).check(
        GateContext(stage, service, artifact(), {"x": artifact(f"{SERVICE}/api/ErrorBodies.java")}))
    assert not strict.passed and "ErrorBodies.java line coverage" in strict.evidence


def _listening(port):
    with socket.socket() as s:
        return s.connect_ex(("127.0.0.1", port)) == 0


@pytest.mark.maven
@needs_build
async def test_the_packaged_service_passes_the_release_smoke_steps(service):
    for workflow in ("lifecycle", "bugfix"):
        args, stage = gate_args(workflow, "release", "service_smoke", "entry_gates")
        result = await ServiceSmokeGate(**args).check(GateContext(stage, service, None, {}))
        assert result.passed, result.evidence
        assert "passed 14 HTTP step(s)" in result.evidence


@pytest.mark.maven
@needs_build
async def test_a_failing_step_fails_the_gate_with_evidence_and_the_server_is_stopped(service, monkeypatch):
    import orchestrator.gates.smoke as smoke

    ports = []
    real = smoke._free_port
    monkeypatch.setattr(smoke, "_free_port", lambda: ports.append(real()) or ports[-1])
    steps = [{"name": "create", "method": "POST", "path": "/api/links", "json": {"url": "https://203.0.113.10/"},
              "expect": 201, "save": {"code": "code"}},
             {"name": "metadata", "path": "/api/links/{code}", "expect": 200, "expect_json": {"originalUrl": "https://elsewhere/"}}]
    result = await ServiceSmokeGate(project="url-shortener", steps=steps).check(
        GateContext(load_workflow(ROOT / "workflows" / "lifecycle.yaml").stage("release"), service, None, {}))
    assert not result.passed
    assert "step 'metadata' failed: originalUrl" in result.evidence and "['create']" in result.evidence
    assert not _listening(ports[0]), "the server is always stopped"


@pytest.mark.maven
@needs_build
async def test_excluded_files_are_not_held_to_the_per_file_rule(service):
    """A Spring Boot main class is never executed by tests (33% lines); the workflows exclude it."""
    stage = load_workflow(ROOT / "workflows" / "bugfix.yaml").stage("fix")
    main_class = artifact(f"{SERVICE}/ShortenerApplication.java")
    held = await CoverageGate(project="url-shortener").check(GateContext(stage, service, main_class, {}))
    assert not held.passed and "ShortenerApplication.java line coverage" in held.evidence
    args, _ = gate_args("bugfix", "fix", "coverage")
    assert (await CoverageGate(**args).check(GateContext(stage, service, main_class, {}))).passed
