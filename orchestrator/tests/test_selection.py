"""`orch run auto`: rules decide eligibility, the selector proposes, a person confirms."""

from pathlib import Path

import pytest

from orchestrator.approvals.service import AutoApprover
from orchestrator.engine.events import EventStore, EventType
from orchestrator.observability.metrics import compute
from orchestrator.observability.report import render_run
from orchestrator.planner.select import CODEBASE_MARKER, SelectionRejected, catalog, eligible, select

from .test_llm_agents import ScriptedLLM
from .test_resilience import ScriptedApprover

ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = ROOT / "workflows"


def proposal(workflow, confidence="high", runner_up="none"):
    return {"workflow": workflow, "confidence": confidence, "rationale": f"it is a {workflow} request",
            "signals": ["observed vs expected"], "runner_up": runner_up}


@pytest.fixture
def existing(tmp_path):
    (tmp_path / CODEBASE_MARKER).parent.mkdir(parents=True)
    (tmp_path / CODEBASE_MARKER).write_text("<project/>")
    return tmp_path


def test_only_workflows_that_declare_selection_are_offered_and_the_codebase_rule_filters_them(tmp_path, existing):
    names = {c.name for c in catalog(WORKFLOWS)}
    assert names == {"skeleton", "brownfield", "lifecycle", "bugfix"}, "fault-demo is never chosen automatically"
    ok, excluded, facts = eligible(catalog(WORKFLOWS), tmp_path / "empty")
    assert [c.name for c in ok] == ["skeleton"] and facts["codebase"] == "new"
    ok, excluded, facts = eligible(catalog(WORKFLOWS), existing)
    assert {c.name for c in ok} == {"brownfield", "lifecycle", "bugfix"} and "skeleton" in excluded


async def test_a_single_eligible_workflow_is_proposed_by_rule_without_a_model_call(tmp_path):
    llm = ScriptedLLM({})
    chosen, record = await select("build a URL shortener", tmp_path, WORKFLOWS, AutoApprover(), "r", llm=llm, model="m")
    assert chosen.name == "skeleton" and record["proposals"][0]["source"] == "rule"
    assert llm.requests == []


async def test_the_schema_only_allows_eligible_workflows(existing):
    llm = ScriptedLLM({"selector": [proposal("bugfix", runner_up="brownfield")]})
    chosen, record = await select("links fail with a 400", existing, WORKFLOWS, AutoApprover(), "r",
                                  llm=llm, model="m")
    assert chosen.name == "bugfix" and record["chosen"] == "bugfix"
    schema = llm.requests[0].schema_["properties"]
    assert set(schema["workflow"]["enum"]) == {"brownfield", "lifecycle", "bugfix"}
    assert "skeleton" not in schema["runner_up"]["enum"] and "none" in schema["runner_up"]["enum"]
    assert record["decisions"][0]["approver"].endswith("(non-human)"), "an automatic confirmation says so"


async def test_a_rejection_with_a_comment_is_followed_on_the_next_proposal(existing):
    llm = ScriptedLLM({"selector": [proposal("brownfield", "medium", "bugfix"), proposal("bugfix")]})
    approver = ScriptedApprover((False, "this is a bug report: reproduce it first"), (True, ""))
    chosen, record = await select("links fail", existing, WORKFLOWS, approver, "r", llm=llm, model="m")
    assert chosen.name == "bugfix" and len(record["proposals"]) == 2
    assert "reproduce it first" in llm.prompts("selector")[1]
    assert [d["approved"] for d in record["decisions"]] == [False, True]
    assert record["decisions"][0]["artifact_sha"] != record["decisions"][1]["artifact_sha"]


async def test_a_rejection_without_a_comment_or_beyond_the_revision_limit_starts_nothing(existing):
    llm = ScriptedLLM({"selector": [proposal("lifecycle")]})
    with pytest.raises(SelectionRejected, match="rejected by reviewer"):
        await select("x", existing, WORKFLOWS, ScriptedApprover((False, "")), "r", llm=llm, model="m")
    llm = ScriptedLLM({"selector": [proposal("lifecycle")] * 3})
    with pytest.raises(SelectionRejected):
        await select("x", existing, WORKFLOWS, ScriptedApprover(*[(False, "no")] * 3), "r", llm=llm, model="m")
    assert len(llm.requests) == 3, "two revisions after the first proposal, then stop"


async def test_without_a_model_several_eligible_workflows_are_refused(existing):
    with pytest.raises(SelectionRejected, match="no selector model"):
        await select("x", existing, WORKFLOWS, AutoApprover(), "r", llm=None, model="")


async def test_the_selection_is_recorded_in_run_started_and_reported(build_engine, recorder, existing):
    from .conftest import make_agent

    llm = ScriptedLLM({"selector": [proposal("bugfix")]})
    _, record = await select("x", existing, WORKFLOWS, AutoApprover(), "test-run", llm=llm, model="m")
    engine = build_engine({"name": "bugfix", "stages": [{"id": "s", "agent": "x"}]}, {"x": make_agent(recorder)},
                          selection=record)
    assert (await engine.run()).succeeded
    started = EventStore.load(engine.events.path)[0]
    assert started.type == EventType.RUN_STARTED and started.payload["selection"]["chosen"] == "bugfix"
    assert EventStore.verify(engine.events.path)[0]
    report = render_run(compute(EventStore.load(engine.events.path)))
    assert "Workflow chosen by `orch run auto`: proposed `bugfix` (high confidence, by model)" in report


async def test_the_selector_eval_replays_offline_with_every_case_correct(monkeypatch):
    """The recorded live eval (scenarios/selection/eval.yaml): 9 requirements with known workflows."""
    from orchestrator.llm.replay import CassetteLLM, Mode
    from orchestrator.planner.eval import evaluate

    monkeypatch.chdir(ROOT)
    llm = CassetteLLM(ROOT / "scenarios" / "cassettes" / "selector-eval", Mode.REPLAY)
    results = await evaluate(ROOT / "scenarios" / "selection" / "eval.yaml", WORKFLOWS, llm, "gpt-6-luna")
    assert len(results) == 9
    assert [r["requirement"] for r in results if not r["correct"]] == []
    assert {r["source"] for r in results} == {"rule", "model"}


def test_orch_run_auto_proposes_records_and_runs_the_chosen_workflow(tmp_path, monkeypatch):
    """The real CLI path in an empty workspace: only skeleton is eligible, so the rule proposes it,
    the (non-human) approver confirms, and the run's first event records how it was chosen."""
    from orchestrator.cli import main as orch

    monkeypatch.chdir(ROOT)
    runs = tmp_path / "runs"
    code = orch(["--env-file", "/dev/null", "--runs-dir", str(runs), "run", "auto", "--requirement",
                 "scenarios/greenfield.md", "--agents", "stub", "--auto-approve", "--run-id", "auto-1",
                 "--no-git"])
    started = EventStore.load(runs / "auto-1" / "events.jsonl")[0]
    assert started.payload["workflow"] == "skeleton"
    assert started.payload["selection"]["proposals"][0]["source"] == "rule"
    assert started.payload["selection"]["excluded"].keys() == {"brownfield", "lifecycle", "bugfix"}
    import json
    assert json.loads((runs / "auto-1" / "run.json").read_text())["workflow"].endswith("workflows/skeleton.yaml"), \
        "resume continues the chosen workflow"
    import shutil
    if shutil.which("mvn"):
        assert code == 0, "the chosen skeleton workflow runs to completion"
