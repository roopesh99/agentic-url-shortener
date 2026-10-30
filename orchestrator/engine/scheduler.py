"""DAG execution engine.

Scheduling model: a stage becomes READY when all of its `needs` have
SUCCEEDED, and is SKIPPED as soon as any of them ends unsuccessfully. Every
READY stage runs concurrently (bounded by `max_parallel`); a stage with several
`needs` is therefore a synchronization point (join). Within a stage:

    entry gates -> agent proposes changes -> policy -> (policy approval) -> apply
                         ^                       | reject                     |
                         +------ RETRYING <------+---------- exit gates <-----+
                    (bounded; policy/gate evidence fed back)     | pass
                                                     (workflow approval) -> SUCCEEDED

Agents only propose a change set; the engine writes it to disk, and only after
the policy engine allows it. A policy BLOCK or a scope breach is never retried.

Every transition, agent call, gate result, artifact and approval is written to
the hash-chained event log, which is the run's source of truth.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import time
from dataclasses import dataclass
from pathlib import Path

from ..agents.base import AgentContext, AgentRegistry, ScopeViolation
from ..approvals.service import ApprovalRequest, Approver
from ..gates.base import GateContext, GateRegistry
from ..policy.engine import PolicyEngine
from ..policy.models import Action, PolicyDecision
from ..workspace.changes import ChangeSet, apply_changes
from .dag import topological_order, validate
from .events import EventStore, EventType
from .models import AgentResult, ApprovalMode, Artifact, GateRef, GateResult, StageSpec, WorkflowSpec
from .state import UNSUCCESSFUL, NodeState, check_transition

MAX_EVIDENCE_CHARS = 4000


@dataclass
class RunResult:
    run_id: str
    succeeded: bool
    states: dict[str, NodeState]
    duration_ms: int
    run_dir: Path


class Engine:
    def __init__(
        self,
        workflow: WorkflowSpec,
        agents: AgentRegistry,
        gates: GateRegistry,
        approver: Approver,
        *,
        policy: PolicyEngine,
        run_id: str,
        run_dir: Path,
        workspace: Path,
        requirement: str,
        max_parallel: int = 4,
    ) -> None:
        self.workflow = workflow
        self.agents = agents
        self.gates = gates
        self.approver = approver
        self.policy = policy
        self.run_id = run_id
        self.run_dir = run_dir
        self.workspace = workspace
        self.requirement = requirement
        self.max_parallel = max_parallel
        self.events = EventStore(run_dir / "events.jsonl", run_id)
        self.artifacts_dir = run_dir / "artifacts"
        self.states: dict[str, NodeState] = {s.id: NodeState.PENDING for s in workflow.stages}
        self.artifacts: dict[str, Artifact] = {}  # accepted artifacts only, keyed by stage id
        self._versions: dict[str, int] = {}
        self._order = topological_order(workflow)

    # ------------------------------------------------------------------ run loop

    async def run(self) -> RunResult:
        self._preflight()
        started = time.monotonic()
        self.events.append(
            EventType.RUN_STARTED,
            workflow=self.workflow.name,
            workflow_version=self.workflow.version,
            stages=self._order,
            requirement_sha=_sha(self.requirement),
            policy_sha=self.policy.policy_sha,
            workspace=str(self.workspace),
        )

        running: dict[asyncio.Task[None], str] = {}
        while True:
            self._promote_pending()
            for stage_id in self._order:
                if len(running) >= self.max_parallel:
                    break
                if self.states[stage_id] is NodeState.READY and stage_id not in running.values():
                    task = asyncio.create_task(self._execute(self.workflow.stage(stage_id)))
                    running[task] = stage_id
            if not running:
                break
            done, _ = await asyncio.wait(running, return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                stage_id = running.pop(task)
                if task.exception() is not None:  # engine defect: contain it to the stage
                    self.events.append(
                        EventType.AGENT_ERROR, stage_id, error=f"engine: {task.exception()!r}"
                    )
                    self._force_failed(stage_id, "internal engine error")

        succeeded = all(s is NodeState.SUCCEEDED for s in self.states.values())
        duration_ms = int((time.monotonic() - started) * 1000)
        self.events.append(
            EventType.RUN_COMPLETED,
            status="SUCCEEDED" if succeeded else "FAILED",
            duration_ms=duration_ms,
            states={k: v.value for k, v in self.states.items()},
        )
        return RunResult(self.run_id, succeeded, dict(self.states), duration_ms, self.run_dir)

    def _preflight(self) -> None:
        """Fail fast, before any side effects, if the workflow references unknown parts."""
        validate(self.workflow)
        problems = []
        for s in self.workflow.stages:
            for name in [s.agent] + ([s.fallback] if s.fallback else []):
                if name not in self.agents:
                    problems.append(f"stage '{s.id}': unknown agent '{name}'")
            for g in s.entry_gates + s.exit_gates:
                if g.name not in self.gates:
                    problems.append(f"stage '{s.id}': unknown gate '{g.name}'")
        if problems:
            raise ValueError("workflow preflight failed:\n  " + "\n  ".join(problems))

    def _promote_pending(self) -> None:
        for stage_id in self._order:
            if self.states[stage_id] is not NodeState.PENDING:
                continue
            needs = self.workflow.stage(stage_id).needs
            blocked_by = [d for d in needs if self.states[d] in UNSUCCESSFUL]
            if blocked_by:
                d = blocked_by[0]
                self._transition(stage_id, NodeState.SKIPPED, f"upstream '{d}' {self.states[d].value}")
            elif all(self.states[d] is NodeState.SUCCEEDED for d in needs):
                self._transition(stage_id, NodeState.READY, "all dependencies succeeded")

    # ------------------------------------------------------------- stage execution

    async def _execute(self, stage: StageSpec) -> None:
        inputs = {d: self.artifacts[d] for d in stage.needs if d in self.artifacts}

        for ref in stage.entry_gates:
            res = await self._run_gate(ref, stage, None, inputs, phase="entry")
            if not res.passed:
                self._transition(stage.id, NodeState.BLOCKED, f"entry gate '{ref.name}' failed")
                return

        self._transition(stage.id, NodeState.RUNNING, "attempt 1")
        feedback: list[str] = []
        max_attempts = stage.retry.max_attempts

        for attempt in range(1, max_attempts + 1):
            if attempt > 1:
                await asyncio.sleep(stage.retry.backoff_seconds * 2 ** (attempt - 2))
                self._transition(stage.id, NodeState.RUNNING, f"attempt {attempt}")
            last = attempt == max_attempts

            ctx = AgentContext(
                run_id=self.run_id,
                stage=stage,
                workspace=self.workspace,
                requirement=self.requirement,
                inputs=inputs,
                attempt=attempt,
                feedback=list(feedback),
            )
            result = await self._invoke_agent(stage, ctx)
            if isinstance(result, ScopeViolation):
                # Breaching the autonomy boundary is a policy failure, not a flaky error: no retry.
                self._transition(stage.id, NodeState.FAILED, f"policy: {result}")
                return
            if isinstance(result, Exception):
                feedback = [f"agent error: {result}"]
                self._retry_or_fail(stage, last, f"agent error on attempt {attempt}")
                if last:
                    return
                continue

            artifact = self._record_artifact(stage, attempt, result, ctx.changes, inputs)

            policy = self._evaluate_policy(stage, attempt, ctx.changes)
            if policy.action is Action.BLOCK:
                self._transition(stage.id, NodeState.FAILED, f"policy blocked: {_violation_summary(policy)}")
                return
            if policy.action is Action.REJECT:
                feedback = [f"policy violation: {v.describe()}" for v in policy.at_least(Action.REJECT)]
                self._retry_or_fail(stage, last, f"policy rejected change: {_violation_summary(policy)}")
                if last:
                    return
                continue
            if policy.action is Action.REQUIRE_APPROVAL:
                high_risk = policy.at_least(Action.REQUIRE_APPROVAL)
                if not await self._approve(
                    stage, artifact,
                    reason=f"policy: {policy.tier.value}-risk change ({_violation_summary(policy)})",
                    evidence=[v.describe() for v in high_risk],
                    source="policy",
                ):
                    return
            self._apply(stage, ctx.changes)

            self._transition(stage.id, NodeState.VALIDATING, f"{len(stage.exit_gates)} exit gate(s)")
            gate_results = [
                await self._run_gate(ref, stage, artifact, inputs, phase="exit") for ref in stage.exit_gates
            ]
            failed = [r for r in gate_results if not r.passed]
            if failed:
                feedback = [f"gate '{r.gate}' failed: {r.evidence}" for r in failed]
                self._retry_or_fail(stage, last, f"exit gate(s) failed: {[r.gate for r in failed]}")
                if last:
                    return
                continue

            if stage.approval is ApprovalMode.REQUIRED and not await self._approve(
                stage, artifact,
                reason="workflow declares this stage approval: required",
                evidence=[f"{r.gate}: {'PASS' if r.passed else 'FAIL'}" for r in gate_results],
                source="workflow",
            ):
                return
            self.artifacts[stage.id] = artifact
            self._transition(stage.id, NodeState.SUCCEEDED, f"accepted {artifact.name}@v{artifact.version}")
            return

    async def _invoke_agent(self, stage: StageSpec, ctx: AgentContext) -> AgentResult | Exception:
        self.events.append(
            EventType.AGENT_INVOKED,
            stage.id,
            agent=stage.agent,
            attempt=ctx.attempt,
            inputs=[a.ref().model_dump() for a in ctx.inputs.values()],
            feedback=ctx.feedback,
        )
        started = time.monotonic()
        try:
            result = await self.agents.create(stage.agent).run(ctx)
        except Exception as exc:  # agent failures are data, not crashes
            self.events.append(
                EventType.AGENT_ERROR, stage.id, agent=stage.agent, attempt=ctx.attempt,
                error=f"{type(exc).__name__}: {exc}",
            )
            return exc
        self.events.append(
            EventType.AGENT_COMPLETED,
            stage.id,
            agent=stage.agent,
            attempt=ctx.attempt,
            summary=result.summary,
            files_proposed=ctx.changes.paths,
            duration_ms=int((time.monotonic() - started) * 1000),
        )
        return result

    def _retry_or_fail(self, stage: StageSpec, last: bool, reason: str) -> None:
        if last:
            self._transition(
                stage.id, NodeState.FAILED, f"{reason}; retries exhausted ({stage.retry.max_attempts})"
            )
        else:
            self._transition(stage.id, NodeState.RETRYING, reason)

    async def _approve(
        self, stage: StageSpec, artifact: Artifact, *, reason: str, evidence: list[str], source: str
    ) -> bool:
        """Pause for a human. `source` is 'policy' (before changes are applied) or
        'workflow' (after gates have verified them)."""
        self._transition(stage.id, NodeState.AWAITING_APPROVAL, f"{source} requires human approval")
        request = ApprovalRequest(
            run_id=self.run_id,
            stage=stage.id,
            reason=reason,
            summary=artifact.result.summary,
            gate_evidence=evidence,
            files_changed=artifact.result.files_written,
            decisions=[f"{d.topic}: {d.choice} ({d.source})" for d in artifact.result.decisions],
        )
        self.events.append(
            EventType.APPROVAL_REQUESTED, stage.id, artifact=artifact.ref().model_dump(),
            reason=reason, source=source, evidence=evidence,
        )
        decision = await self.approver.decide(request)
        self.events.append(
            EventType.APPROVAL_DECIDED,
            stage.id,
            approved=decision.approved,
            approver=decision.approver,
            comment=decision.comment,
            artifact=artifact.ref().model_dump(),
        )
        if not decision.approved:
            self._transition(stage.id, NodeState.FAILED, f"rejected by {decision.approver}")
        return decision.approved

    def _evaluate_policy(self, stage: StageSpec, attempt: int, changes: ChangeSet) -> PolicyDecision:
        decision = self.policy.evaluate(changes, stage)
        self.events.append(
            EventType.POLICY_EVALUATED,
            stage.id,
            attempt=attempt,
            action=decision.action.value,
            tier=decision.tier.value,
            policy_sha=decision.policy_sha,
            files=changes.paths,
            violations=[v.model_dump(mode="json") for v in decision.violations],
        )
        return decision

    def _apply(self, stage: StageSpec, changes: ChangeSet) -> None:
        """The only place agent output reaches disk: after policy (and any approval)."""
        paths = apply_changes(self.workspace, changes)
        self.events.append(EventType.CHANGES_APPLIED, stage.id, files=changes.file_hashes(), count=len(paths))

    # ------------------------------------------------------------------- helpers

    async def _run_gate(
        self, ref: GateRef, stage: StageSpec, artifact: Artifact | None, inputs: dict[str, Artifact], *, phase: str
    ) -> GateResult:
        started = time.monotonic()
        try:
            gate = self.gates.create(ref.name, ref.args)
            res = await gate.check(GateContext(stage, self.workspace, artifact, inputs))
        except Exception as exc:  # a crashing gate is a failing gate
            res = GateResult(gate=ref.name, passed=False, evidence=f"gate error: {type(exc).__name__}: {exc}")
        res.duration_ms = int((time.monotonic() - started) * 1000)
        res.evidence = res.evidence[-MAX_EVIDENCE_CHARS:]
        self.events.append(
            EventType.GATE_RESULT,
            stage.id,
            phase=phase,
            gate=res.gate,
            passed=res.passed,
            evidence=res.evidence,
            duration_ms=res.duration_ms,
            artifact=artifact.ref().model_dump() if artifact else None,
        )
        return res

    def _record_artifact(
        self, stage: StageSpec, attempt: int, result: AgentResult, changes: ChangeSet, inputs: dict[str, Artifact]
    ) -> Artifact:
        # The proposed change set is authoritative, not the agent's claim about what it wrote.
        result = result.model_copy(update={"files_written": changes.paths})
        version = self._versions.get(stage.id, 0) + 1
        self._versions[stage.id] = version
        file_hashes = changes.file_hashes()
        sha = _sha(json.dumps({"result": result.model_dump(), "files": file_hashes}, sort_keys=True))
        artifact = Artifact(
            name=stage.id,
            version=version,
            sha=sha,
            produced_by=f"{stage.id}/{stage.agent}#{attempt}",
            inputs=[a.ref() for a in inputs.values()],
            result=result,
        )
        self.artifacts_dir.mkdir(parents=True, exist_ok=True)
        (self.artifacts_dir / f"{stage.id}.v{version}.json").write_text(
            artifact.model_dump_json(indent=2), encoding="utf-8"
        )
        self.events.append(
            EventType.ARTIFACT_RECORDED,
            stage.id,
            artifact=artifact.ref().model_dump(),
            produced_by=artifact.produced_by,
            inputs=[r.model_dump() for r in artifact.inputs],
            file_hashes=file_hashes,
        )
        for d in result.decisions:
            self.events.append(
                EventType.DECISION_RECORDED, stage.id, artifact=artifact.ref().model_dump(), **d.model_dump()
            )
        return artifact

    def _transition(self, stage_id: str, target: NodeState, reason: str) -> None:
        current = self.states[stage_id]
        check_transition(current, target)
        self.states[stage_id] = target
        self.events.append(EventType.STAGE_STATE, stage_id, **{"from": current.value, "to": target.value}, reason=reason)

    def _force_failed(self, stage_id: str, reason: str) -> None:
        current = self.states[stage_id]
        if current in UNSUCCESSFUL or current is NodeState.SUCCEEDED:
            return
        self.states[stage_id] = NodeState.FAILED
        self.events.append(
            EventType.STAGE_STATE, stage_id, **{"from": current.value, "to": NodeState.FAILED.value}, reason=reason
        )


def _violation_summary(decision: PolicyDecision) -> str:
    rules = sorted({v.rule for v in decision.at_least(decision.action)})
    return f"{len(decision.violations)} violation(s); {decision.action.value} by {', '.join(rules)}"


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()
