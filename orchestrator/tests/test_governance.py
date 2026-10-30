"""Policy enforcement inside the engine: nothing reaches disk until policy allows it."""

import os
from pathlib import Path

import pytest

from orchestrator.agents.base import AgentContext
from orchestrator.approvals.service import ApprovalDecision, ApprovalRequest, Approver, AutoApprover
from orchestrator.engine.events import EventStore, EventType
from orchestrator.engine.state import NodeState
from orchestrator.policy.engine import PolicyEngine
from orchestrator.workspace.changes import ScopeViolation

from .conftest import make_agent

ROOT = Path(__file__).resolve().parents[2]
POLICY = PolicyEngine.load(ROOT / "policies" / "default.yaml")
SRC = "src/main/App.java"
MIGRATION = "src/main/resources/db/migration/V2__clicks.sql"


def one_stage(**overrides):
    stage = {"id": "implement", "agent": "x", "write_scope": ["src/main/**"], **overrides}
    return {"name": "w", "stages": [stage]}


def events(engine, type_=None):
    return [e for e in EventStore.load(engine.events.path) if type_ is None or e.type == type_]


class RecordingApprover(Approver):
    def __init__(self, approve: bool):
        self.approve = approve
        self.requests: list[ApprovalRequest] = []

    async def decide(self, request):
        self.requests.append(request)
        return ApprovalDecision(approved=self.approve, approver="reviewer", comment="")


async def test_secret_is_rejected_fed_back_and_fixed_on_retry(build_engine, recorder, tmp_path):
    def coder(ctx: AgentContext):
        if ctx.attempt == 1:
            ctx.write_file(SRC, 'class App { String API_KEY = "s3cr3t-value-123"; }')
        else:
            ctx.write_file(SRC, 'class App { String apiKey = System.getenv("API_KEY"); }')

    engine = build_engine(one_stage(retry={"max_attempts": 2}), {"x": make_agent(recorder, behaviour=coder)},
                          policy=POLICY)
    assert (await engine.run()).succeeded

    feedback = recorder.attempts("implement")[1]["feedback"]
    assert any("secrets" in f and f"{SRC}:1" in f for f in feedback), feedback
    assert "getenv" in (tmp_path / "ws" / SRC).read_text()
    applied = events(engine, EventType.CHANGES_APPLIED)
    assert len(applied) == 1, "the rejected attempt must never be written"


async def test_rejected_change_leaves_workspace_untouched(build_engine, recorder, tmp_path):
    def coder(ctx):
        ctx.write_file("src/main/Good.java", "class Good {}")
        ctx.write_file(SRC, "Runtime.getRuntime().exec(cmd);")

    engine = build_engine(one_stage(), {"x": make_agent(recorder, behaviour=coder)}, policy=POLICY)
    result = await engine.run()
    assert result.states["implement"] is NodeState.FAILED
    assert not (tmp_path / "ws" / "src").exists(), "change sets are all-or-nothing"


async def test_high_risk_change_pauses_for_approval_before_it_is_applied(build_engine, recorder, tmp_path):
    approver = RecordingApprover(approve=True)
    seen_on_disk = {}

    class CheckingApprover(Approver):
        async def decide(self, request):
            seen_on_disk["migration"] = (tmp_path / "ws" / MIGRATION).exists()
            return await approver.decide(request)

    def coder(ctx):
        ctx.write_file(MIGRATION, "CREATE TABLE clicks(id BIGINT PRIMARY KEY);")

    # stage declares approval: none — policy still requires a human
    engine = build_engine(one_stage(exit_gates=["pass"]), {"x": make_agent(recorder, behaviour=coder)},
                          approver=CheckingApprover(), policy=POLICY)
    assert (await engine.run()).succeeded

    assert seen_on_disk["migration"] is False, "human approves the change before it is applied"
    assert (tmp_path / "ws" / MIGRATION).exists()
    [req] = approver.requests
    assert req.reason.startswith("policy: high-risk") and any("high_impact_paths" in e for e in req.gate_evidence)
    requested = events(engine, EventType.APPROVAL_REQUESTED)[0]
    assert requested.payload["source"] == "policy"
    order = [e.type for e in events(engine) if e.type in
             (EventType.APPROVAL_DECIDED, EventType.CHANGES_APPLIED, EventType.GATE_RESULT)]
    assert order == [EventType.APPROVAL_DECIDED, EventType.CHANGES_APPLIED, EventType.GATE_RESULT]


async def test_rejected_high_risk_change_is_never_applied(build_engine, recorder, tmp_path):
    def coder(ctx):
        ctx.write_file(MIGRATION, "DROP TABLE urls;")

    engine = build_engine(one_stage(), {"x": make_agent(recorder, behaviour=coder)},
                          approver=AutoApprover(approve=False), policy=POLICY)
    result = await engine.run()
    assert result.states["implement"] is NodeState.FAILED
    assert not (tmp_path / "ws" / MIGRATION).exists()


async def test_block_action_is_not_retried(build_engine, recorder, tmp_path):
    strict = tmp_path / "strict.yaml"
    strict.write_text("rules:\n  secrets: {action: block}\n")

    def coder(ctx):
        ctx.write_file(SRC, 'String password = "hunter2-hunter2";')

    engine = build_engine(one_stage(retry={"max_attempts": 3}), {"x": make_agent(recorder, behaviour=coder)},
                          policy=PolicyEngine.load(strict))
    result = await engine.run()
    assert result.states["implement"] is NodeState.FAILED
    assert len(recorder.attempts("implement")) == 1


async def test_flagged_change_proceeds_and_is_audited(build_engine, recorder, tmp_path):
    lenient = tmp_path / "lenient.yaml"
    lenient.write_text("rules:\n  dangerous_code: {action: flag}\n")

    def coder(ctx):
        ctx.write_file(SRC, "new ProcessBuilder(cmd).start();")

    engine = build_engine(one_stage(), {"x": make_agent(recorder, behaviour=coder)},
                          policy=PolicyEngine.load(lenient))
    assert (await engine.run()).succeeded
    [evaluated] = events(engine, EventType.POLICY_EVALUATED)
    assert evaluated.payload["tier"] == "medium" and evaluated.payload["violations"]


async def test_policy_version_is_recorded_on_the_run(build_engine, recorder):
    engine = build_engine(one_stage(), {"x": make_agent(recorder)}, policy=POLICY)
    await engine.run()
    assert events(engine, EventType.RUN_STARTED)[0].payload["policy_sha"] == POLICY.policy_sha


@pytest.mark.skipif(os.name == "nt", reason="symlinks")
async def test_symlink_escape_is_blocked(build_engine, recorder, tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    (tmp_path / "ws" / "src").mkdir()
    (tmp_path / "ws" / "src" / "main").symlink_to(outside)

    def coder(ctx):
        ctx.write_file("src/main/pwn.txt", "x")

    engine = build_engine(one_stage(), {"x": make_agent(recorder, behaviour=coder)}, policy=POLICY)
    result = await engine.run()
    assert result.states["implement"] is NodeState.FAILED
    assert not (outside / "pwn.txt").exists()
    assert "symlink" in events(engine, EventType.STAGE_STATE)[-1].payload["reason"]


def test_scope_violation_type_is_shared():
    from orchestrator.agents.base import ScopeViolation as AgentScopeViolation
    assert AgentScopeViolation is ScopeViolation
