"""Clarification checkpoints: open questions pause for a human, answers are binding and audited."""

import asyncio
import getpass
from pathlib import Path

import pytest
import yaml

from orchestrator.agents.stubs import stub_agents
from orchestrator.agents.base import AgentRegistry
from orchestrator.agents.stubs import StubAnalyst
from orchestrator.approvals.service import (AutoApprover, ClarificationRequest, ClarificationResponse, FileApprover,
                                            PresetAnswers, pending_clarifications, record_answers, record_decision)
from orchestrator.cli import main as orch
from orchestrator.engine.dag import load_workflow
from orchestrator.engine.events import EventStore, EventType
from orchestrator.engine.scheduler import Engine
from orchestrator.engine.state import NodeState
from orchestrator.gates.builtin import builtin_gates
from orchestrator.llm.client import LLMRequest, LLMResponse, Usage
from orchestrator.llm.replay import CassetteLLM, Mode
from orchestrator.policy.engine import PolicyEngine

ROOT = Path(__file__).resolve().parents[2]
QUESTION = "Should links be private to the creator?"
REQUIREMENT = (ROOT / "scenarios" / "greenfield.md").read_text() + f"- {QUESTION}\n"


def requirements_only():
    wf = load_workflow(ROOT / "workflows" / "skeleton.yaml")
    wf.stages = [s for s in wf.stages if s.id == "requirements"]
    return wf


def engine(tmp_path, approver, workflow=None):
    return Engine(workflow or requirements_only(), stub_agents(), builtin_gates(), approver,
                  policy=PolicyEngine.load(ROOT / "policies" / "default.yaml"), run_id="c",
                  run_dir=tmp_path / "run", workspace=tmp_path / "ws", requirement=REQUIREMENT)


def events(e, type_):
    return [x for x in EventStore.load(e.events.path) if x.type == type_]


async def _wait_for(path: Path, timeout=5.0) -> Path:
    """Waits for a file; `path` may contain a glob in its name (checkpoint ids include content hashes)."""
    for _ in range(int(timeout / 0.02)):
        matches = sorted(path.parent.glob(path.name)) if path.parent.exists() else []
        if matches:
            return matches[0]
        await asyncio.sleep(0.02)
    raise AssertionError(f"{path} never appeared")


async def test_open_question_pauses_writes_readable_file_and_resumes_with_answer(tmp_path):
    approvals = tmp_path / "run" / "approvals"
    e = engine(tmp_path, FileApprover(approvals, poll_seconds=0.02))
    run = asyncio.create_task(e.run())

    answers_file = await _wait_for(approvals / "requirements-clarify-1-*.answers.yaml")
    clarify_name = answers_file.name.removesuffix(".answers.yaml")
    assert not run.done(), "the run waits for a human"
    text = answers_file.read_text()
    assert f"orch answer c {clarify_name}" in text, "the file says how to submit"
    items = yaml.safe_load(text)
    assert items == [{"question": QUESTION, "why": "", "answer": ""}]
    [(clarify_id, _)] = pending_clarifications(approvals)

    items[0]["answer"] = "No: links are public; only deletion is restricted."
    answers_file.write_text(yaml.safe_dump(items))
    record_answers(approvals, clarify_id)
    # re-run passes the gates, then the workflow's own approval checkpoint still applies
    request = await _wait_for(approvals / "requirements-*.request.json")
    approval_id = request.name.removesuffix(".request.json")
    record_decision(approvals, approval_id, approved=True)
    result = await asyncio.wait_for(run, 5)

    assert result.states["requirements"] is NodeState.SUCCEEDED
    spec = e.artifacts["requirements"].result.outputs
    assert spec["clarifications"] == [{"question": QUESTION, "answer": items[0]["answer"]}]
    [answered] = events(e, EventType.CLARIFICATION_ANSWERED)
    assert answered.payload["answered_by"] == getpass.getuser() and answered.payload["source"] == "human"
    human = [d for d in events(e, EventType.DECISION_RECORDED) if d.payload["source"] == "human"]
    assert [d.payload["choice"] for d in human] == [items[0]["answer"]]
    invoked = events(e, EventType.AGENT_INVOKED)
    assert len(invoked) == 2, "one re-run with the answers, outside the retry budget of 1"
    assert e.workflow.stage("requirements").retry.max_attempts == 1


async def test_incomplete_answers_are_refused(tmp_path):
    approvals = tmp_path / "run" / "approvals"
    e = engine(tmp_path, FileApprover(approvals, poll_seconds=0.02))
    run = asyncio.create_task(e.run())
    answers_file = await _wait_for(approvals / "requirements-clarify-1-*.answers.yaml")
    with pytest.raises(ValueError, match="still need an answer"):
        record_answers(approvals, answers_file.name.removesuffix(".answers.yaml"))
    assert not run.done()
    run.cancel()


async def test_non_human_approver_never_answers_product_questions(tmp_path):
    result = await engine(tmp_path, AutoApprover()).run()
    assert result.states["requirements"] is NodeState.FAILED


async def test_preset_answers_file_answers_and_is_attributed_to_the_file(tmp_path):
    answers = tmp_path / "answers.yaml"
    answers.write_text(yaml.safe_dump([{"question": QUESTION, "answer": "Public."}]))
    e = engine(tmp_path, PresetAnswers(answers, AutoApprover()))
    assert (await e.run()).states["requirements"] is NodeState.SUCCEEDED
    [answered] = events(e, EventType.CLARIFICATION_ANSWERED)
    assert answered.payload["source"] == "answers-file"
    assert answered.payload["answered_by"].startswith("answers-file:answers.yaml@")


async def test_preset_answers_defer_unknown_questions(tmp_path):
    answers = tmp_path / "answers.yaml"
    answers.write_text(yaml.safe_dump([{"question": "something else?", "answer": "x"}]))
    result = await engine(tmp_path, PresetAnswers(answers, AutoApprover())).run()
    assert result.states["requirements"] is NodeState.FAILED, "unmatched questions go to the (non-human) approver"


async def test_clarification_rounds_are_bounded(tmp_path):
    class ForgetfulAnalyst(StubAnalyst):
        async def run(self, ctx):
            ctx.clarifications = []  # ignores every answer, so the question never closes
            return await super().run(ctx)

    class CountingApprover(AutoApprover):
        rounds = 0

        async def clarify(self, request):
            CountingApprover.rounds += 1
            return ClarificationResponse(answers=[{"question": q["question"], "answer": "yes"}
                                                  for q in request.questions], answered_by="tester")

    agents = AgentRegistry()
    agents.register("analyst", ForgetfulAnalyst)
    wf = requirements_only()
    e = Engine(wf, agents, builtin_gates(), CountingApprover(), policy=PolicyEngine.load(ROOT / "policies" / "default.yaml"),
               run_id="c", run_dir=tmp_path / "run", workspace=tmp_path / "ws", requirement=REQUIREMENT)

    # also drop the engine's verbatim copy of the answers, so the gate cannot see them
    e._record_artifact = lambda stage, attempt, result, changes, inputs, clarifications=(), *args: \
        Engine._record_artifact(e, stage, attempt, result, changes, inputs, (), *args)
    result = await e.run()
    assert CountingApprover.rounds == wf.stage("requirements").clarification.max_rounds == 2
    assert result.states["requirements"] is NodeState.FAILED
    assert len(events(e, EventType.AGENT_INVOKED)) == 3, "1 attempt + 2 clarification re-runs, then stop"


def test_cli_lists_and_submits_answers(tmp_path, capsys):
    approvals = tmp_path / "r1" / "approvals"
    req = ClarificationRequest(run_id="r1", stage="requirements", round=1,
                               questions=[{"question": QUESTION, "why": "privacy"}])
    approvals.mkdir(parents=True)
    (approvals / "requirements-clarify-1.questions.json").write_text(req.model_dump_json())
    answers = tmp_path / "mine.yaml"
    answers.write_text(yaml.safe_dump([{"question": QUESTION, "answer": "Public."}]))
    base = ["--env-file", str(tmp_path / "no.env"), "--runs-dir", str(tmp_path)]

    assert orch(base + ["pending", "r1"]) == 0
    assert QUESTION in capsys.readouterr().out
    assert orch(base + ["answer", "r1", "requirements-clarify-1", "--from", str(answers)]) == 0
    assert orch(base + ["answer", "r1", "requirements-clarify-1", "--from", str(answers)]) == 2, "only once"


def test_shipped_greenfield_answers_cover_the_recorded_questions():
    import json
    open_questions = set()
    for cassette in (ROOT / "scenarios" / "cassettes" / "skeleton-greenfield").glob("analyst-*.json"):
        spec = json.loads(cassette.read_text())["response"]["data"]
        open_questions |= {a["question"] for a in spec["ambiguities"] if not a["resolution"]}
    answered = {a["question"] for a in yaml.safe_load((ROOT / "scenarios" / "greenfield.answers.yaml").read_text())}
    assert open_questions and open_questions <= answered, open_questions - answered


# --- cassette record mode ----------------------------------------------------------------

async def test_record_mode_reuses_saved_exchanges_and_rerecord_does_not(tmp_path):
    class Counting:
        calls = 0

        async def complete(self, request):
            Counting.calls += 1
            return LLMResponse(data={"n": Counting.calls}, model="m", stop_reason="end_turn", usage=Usage())

    req = LLMRequest(agent="analyst", model="m", system="s", user="u", schema={})
    await CassetteLLM(tmp_path, Mode.RECORD, Counting()).complete(req)
    again = await CassetteLLM(tmp_path, Mode.RECORD, Counting()).complete(req)
    assert Counting.calls == 1 and again.source == "cassette"
    await CassetteLLM(tmp_path, Mode.RERECORD, Counting()).complete(req)
    assert Counting.calls == 2


def test_recorded_decisions_seed_only_decisions_and_answers(tmp_path):
    from orchestrator.cli import _seed_decisions

    recorded = tmp_path / "recorded"
    recorded.mkdir()
    (recorded / "requirements-abc123.request.json").write_text("{}")         # requests are not copied
    (recorded / "requirements-abc123.decision.json").write_text('{"approved": true}')
    (recorded / "requirements-clarify-1-def456.answered.json").write_text("{}")
    (recorded / "requirements-clarify-1-def456.answers.yaml").write_text("[]")
    target = tmp_path / "run" / "approvals"
    _seed_decisions(recorded, target)
    assert sorted(p.name for p in target.iterdir()) == [
        "requirements-abc123.decision.json", "requirements-clarify-1-def456.answered.json"]
    with pytest.raises(FileNotFoundError):
        _seed_decisions(tmp_path / "missing", target)
