"""Stub agents + real gates through the real skeleton workflow."""

import shutil
from pathlib import Path

import pytest

from orchestrator.agents.stubs import stub_agents
from orchestrator.approvals.service import AutoApprover
from orchestrator.engine.dag import load_workflow
from orchestrator.engine.scheduler import Engine
from orchestrator.engine.state import NodeState
from orchestrator.gates.builtin import builtin_gates

ROOT = Path(__file__).resolve().parents[2]
REQUIREMENT = (ROOT / "scenarios" / "greenfield.md").read_text()


def _engine(tmp_path, workflow, requirement=REQUIREMENT):
    return Engine(
        workflow, stub_agents(), builtin_gates(), AutoApprover(),
        run_id="e2e", run_dir=tmp_path / "run", workspace=tmp_path / "ws", requirement=requirement,
    )


def _without_test_stage():
    workflow = load_workflow(ROOT / "workflows" / "skeleton.yaml")
    workflow.stages = [s for s in workflow.stages if s.id != "test"]
    return workflow


async def test_analyst_normalizes_spec_and_resolves_known_ambiguities(tmp_path):
    result = await _engine(tmp_path, _without_test_stage()).run()
    assert result.succeeded
    spec = (tmp_path / "run" / "artifacts" / "requirements.v1.json").read_text()
    assert '"FR1"' in spec and "302 Found" in spec
    assert (tmp_path / "ws" / "url-shortener" / "pom.xml").exists()
    assert (tmp_path / "ws" / "docs" / "test-plan.md").exists()


async def test_unresolvable_ambiguity_stops_before_design(tmp_path):
    vague = REQUIREMENT + "- Should links be private to the creator?\n"
    result = await _engine(tmp_path, _without_test_stage(), vague).run()
    assert result.states["requirements"] is NodeState.FAILED
    assert result.states["implement"] is NodeState.SKIPPED


@pytest.mark.maven
@pytest.mark.skipif(shutil.which("mvn") is None, reason="Maven not installed")
async def test_full_skeleton_builds_and_passes_real_tests(tmp_path):
    result = await _engine(tmp_path, load_workflow(ROOT / "workflows" / "skeleton.yaml")).run()
    assert result.succeeded, result.states


@pytest.mark.maven
@pytest.mark.skipif(shutil.which("mvn") is None, reason="Maven not installed")
async def test_maven_gate_fails_on_a_failing_java_test(tmp_path):
    from orchestrator.agents.stubs import TEMPLATES
    from orchestrator.gates.base import GateContext
    from orchestrator.gates.builtin import MavenTestGate

    shutil.copytree(TEMPLATES, tmp_path, dirs_exist_ok=True)
    test_file = next((tmp_path / "url-shortener" / "src" / "test").rglob("*Test.java"))
    test_file.write_text(test_file.read_text().replace("status().isNotFound()", "status().isOk()"))

    stage = load_workflow(ROOT / "workflows" / "skeleton.yaml").stage("test")
    result = await MavenTestGate(project="url-shortener").check(GateContext(stage, tmp_path, None, {}))
    assert not result.passed
    assert "unknownCodeReturns404" in result.evidence, "evidence must name the failing test for retry feedback"
