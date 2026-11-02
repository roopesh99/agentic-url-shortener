"""Bug fixes: reproduce first (a new test must fail on the current code), then fix."""

import shutil
from pathlib import Path

import pytest

from orchestrator.agents.stubs import TEMPLATES
from orchestrator.engine.dag import load_workflow
from orchestrator.engine.models import AgentResult, Artifact
from orchestrator.gates.base import GateContext
from orchestrator.gates.regression import RegressionReproducesGate, source_file

ROOT = Path(__file__).resolve().parents[2]
NEW_TEST = "url-shortener/src/test/java/com/example/shortener/BugReproTest.java"
EXISTING = "url-shortener/src/test/java/com/example/shortener/ShortUrlControllerTest.java"

maven = pytest.mark.skipif(shutil.which("mvn") is None, reason="Maven not installed")


def regression_test(assertion: str) -> str:
    return f"""package com.example.shortener;

import static org.junit.jupiter.api.Assertions.assertEquals;
import org.junit.jupiter.api.Test;

class BugReproTest {{
    @Test
    void reproducesTheReportedBug() {{
        {assertion}
    }}
}}
"""


async def check(tmp_path, files: dict[str, str], written: list[str]):
    shutil.copytree(TEMPLATES, tmp_path, dirs_exist_ok=True)
    for rel, text in files.items():
        (tmp_path / rel).write_text(text)
    stage = load_workflow(ROOT / "workflows" / "bugfix.yaml").stage("reproduce")
    artifact = Artifact(name="reproduce", version=1, sha="x", produced_by="reproducer#1",
                        result=AgentResult(summary="", files_written=written))
    return await RegressionReproducesGate(project="url-shortener").check(GateContext(stage, tmp_path, artifact, {}))


def test_test_classes_map_to_their_source_files():
    assert source_file("com.example.shortener.api.FooTest", "url-shortener") == \
        "url-shortener/src/test/java/com/example/shortener/api/FooTest.java"
    assert source_file("com.example.FooTest$WhenBroken", "svc") == "svc/src/test/java/com/example/FooTest.java"


@pytest.mark.maven
@maven
async def test_a_new_failing_test_with_everything_else_green_reproduces(tmp_path):
    result = await check(tmp_path, {NEW_TEST: regression_test('assertEquals("expected", "actual");')}, [NEW_TEST])
    assert result.passed, result.evidence
    assert "BugReproTest.reproducesTheReportedBug" in result.evidence and "expected" in result.evidence


@pytest.mark.maven
@maven
async def test_a_passing_test_reproduces_nothing(tmp_path):
    result = await check(tmp_path, {NEW_TEST: regression_test("assertEquals(1, 1);")}, [NEW_TEST])
    assert not result.passed and "not reproduced" in result.evidence


@pytest.mark.maven
@maven
async def test_a_failing_existing_test_is_not_a_reproduction(tmp_path):
    shutil.copytree(TEMPLATES, tmp_path, dirs_exist_ok=True)
    broken = (tmp_path / EXISTING).read_text().replace("status().isNotFound()", "status().isOk()")
    result = await check(tmp_path, {NEW_TEST: regression_test('assertEquals("a", "b");'), EXISTING: broken},
                         [NEW_TEST])
    assert not result.passed and "did not write fail too" in result.evidence
    assert "ShortUrlControllerTest" in result.evidence


@pytest.mark.maven
@maven
async def test_a_test_that_does_not_compile_reproduces_nothing_even_with_stale_reports(tmp_path):
    """A failing report left by an earlier run, for the very test class written now, must not
    pass for a reproduction when the new test does not even compile."""
    stale = tmp_path / "url-shortener" / "target" / "surefire-reports"
    stale.mkdir(parents=True)
    (stale / "TEST-com.example.shortener.BugReproTest.xml").write_text(
        '<testsuite><testcase classname="com.example.shortener.BugReproTest" name="old">'
        '<failure message="from an earlier run"/></testcase></testsuite>')
    result = await check(tmp_path, {NEW_TEST: regression_test("assertEquals(undefinedThing, 1);")}, [NEW_TEST])
    assert not result.passed and "did not compile" in result.evidence


def test_bugfix_workflow_orders_reproduction_before_the_fix():
    wf = load_workflow(ROOT / "workflows" / "bugfix.yaml")
    assert [s.id for s in wf.stages] == ["requirements", "impact", "reproduce", "fix", "release"]
    assert wf.stage("fix").needs == ["reproduce"]
    assert [g.name for g in wf.stage("reproduce").exit_gates] == ["regression_reproduces"]
    assert all(p.startswith("url-shortener/src/test/") for p in wf.stage("reproduce").write_scope)
    assert not any("src/test" in p for p in wf.stage("fix").write_scope), "the fix may not change the tests"
    assert {s.id for s in wf.stages if s.approval.value == "required"} == {"requirements", "impact", "release"}
