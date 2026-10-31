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
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

from ..agents.base import AgentContext, AgentRegistry, FatalAgentError, ScopeViolation
from ..approvals.service import (ApprovalDecision, ApprovalRequest, Approver, ClarificationRequest,
                                 ClarificationResponse)
from ..gates.base import GateContext, GateRegistry
from ..policy.engine import PolicyEngine
from ..policy.models import Action, PolicyDecision
from ..workspace.changes import ChangeSet, apply_changes, revert_changes
from ..workspace.git import GitWorkspace
from .dag import topological_order, upstream, validate
from .events import EventStore, EventType, replay_states
from .models import AgentResult, ApprovalMode, Artifact, GateRef, GateResult, StageSpec, WorkflowSpec
from .state import UNSUCCESSFUL, NodeState, check_transition

MAX_EVIDENCE_CHARS = 4000
STOP_FILE = "STOP"


class ResumeError(RuntimeError):
    pass


class _Outcome(Enum):
    SUCCEEDED = "succeeded"
    TERMINAL = "terminal"    # nothing else should be tried (policy block, rejection, safe-stop)
    EXHAUSTED = "exhausted"  # this agent could not get there; a fallback agent may


@dataclass
class _StageProgress:
    """State one stage carries across attempts, including a fallback agent's."""

    attempt: int = 0
    rounds: int = 0
    revisions: int = 0
    feedback: list[str] = field(default_factory=list)         # why the last attempt failed; replaced each time
    change_requests: list[str] = field(default_factory=list)  # reviewer instructions; kept for every later attempt
    clarifications: list[dict[str, str]] = field(default_factory=list)
    reverted: set[str] = field(default_factory=set)

    def agent_feedback(self) -> list[str]:
        return [f"Change request {i} from a human reviewer (binding; apply it exactly): {c}"
                for i, c in enumerate(self.change_requests, start=1)] + self.feedback


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
        max_cost_usd: float | None = None,
        max_minutes: float | None = None,
        git: GitWorkspace | None = None,
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
        self.max_cost_usd = max_cost_usd
        self.max_minutes = max_minutes
        self.git = git
        self.stop_file = run_dir / STOP_FILE
        self._started = time.monotonic()
        self.cost_usd = 0.0
        self._halt_reason: str | None = None  # set => safe-stop: start nothing new
        self.events = EventStore(run_dir / "events.jsonl", run_id)
        self.artifacts_dir = run_dir / "artifacts"
        self.states: dict[str, NodeState] = {s.id: NodeState.PENDING for s in workflow.stages}
        self.artifacts: dict[str, Artifact] = {}  # accepted artifacts only, keyed by stage id
        self._versions: dict[str, int] = {}
        self._order = topological_order(workflow)

    # ------------------------------------------------------------------ run loop

    async def run(self, resume: bool = False) -> RunResult:
        """Execute the workflow, or with `resume=True` continue a stopped run from its event log."""
        self._preflight()
        started = self._started = time.monotonic()
        if resume:
            self._restore()
        else:
            workspace_info = self.git.prepare() if self.git else None
            self.events.append(
                EventType.RUN_STARTED,
                workflow=self.workflow.name,
                workflow_version=self.workflow.version,
                workflow_sha=self._workflow_sha(),
                stages=self._order,
                requirement_sha=_sha(self.requirement),
                policy_sha=self.policy.policy_sha,
                workspace=str(self.workspace),
                git=workspace_info,
                max_cost_usd=self.max_cost_usd,
                max_minutes=self.max_minutes,
            )

        running: dict[asyncio.Task[None], str] = {}
        while True:
            self._check_stop()
            if self._halt_reason:
                self._skip_unstarted(running)
            else:
                self._promote_pending()
            for stage_id in self._order:
                if len(running) >= self.max_parallel or self._halt_reason:
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
            status="SUCCEEDED" if succeeded else ("HALTED" if self._halt_reason else "FAILED"),
            duration_ms=duration_ms,
            cost_usd=round(self.cost_usd, 6),
            halt_reason=self._halt_reason,
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
        # Cross-stage context: every accepted ancestor artifact, not only direct dependencies
        # (the tester needs the approved spec as much as the code it tests).
        ancestors = upstream(self.workflow, stage.id)
        inputs = {d: self.artifacts[d] for d in self._order if d in ancestors and d in self.artifacts}

        for ref in stage.entry_gates:
            res = await self._run_gate(ref, stage, None, inputs, phase="entry")
            if not res.passed:
                self._transition(stage.id, NodeState.BLOCKED, f"entry gate '{ref.name}' failed")
                return

        self._transition(stage.id, NodeState.RUNNING, "attempt 1")
        progress = _StageProgress()
        outcome, reason = await self._attempts(stage, inputs, stage.agent, progress, stage.retry.max_attempts)

        if outcome is _Outcome.EXHAUSTED and stage.fallback and not self._halt_reason:
            # Retries (or the primary agent) could not get past the gates: one attempt with the
            # fallback agent, carrying all feedback and human answers gathered so far.
            self.events.append(EventType.FALLBACK_ENGAGED, stage.id, from_agent=stage.agent,
                               to_agent=stage.fallback, reason=reason)
            self._transition(stage.id, NodeState.RETRYING, f"fallback to agent '{stage.fallback}' after: {reason}")
            outcome, reason = await self._attempts(stage, inputs, stage.fallback, progress, 1)

        if outcome is _Outcome.SUCCEEDED:
            return
        self._transition(stage.id, NodeState.FAILED, reason)
        if progress.reverted:
            self._transition(stage.id, NodeState.ROLLED_BACK,
                             f"workspace restored: {len(progress.reverted)} file(s) from failed attempts reverted")

    async def _attempts(self, stage: StageSpec, inputs: dict[str, Artifact], agent: str,
                        progress: "_StageProgress", budget: int) -> tuple["_Outcome", str]:
        """Run up to `budget` attempts with `agent`. Never sets a terminal state itself:
        returns SUCCEEDED, TERMINAL (do not try anything else) or EXHAUSTED (fallback may help)."""
        allowed = budget  # +1 per clarification round: answers are not failures
        local = retries = 0
        clarified = False

        while local < allowed:
            local += 1
            progress.attempt += 1
            attempt = progress.attempt
            if attempt > 1:
                if not clarified and local > 1:
                    retries += 1
                    await asyncio.sleep(stage.retry.backoff_seconds * 2 ** (retries - 1))
                self._transition(stage.id, NodeState.RUNNING,
                                 f"attempt {attempt}" + (f" (agent '{agent}')" if agent != stage.agent else ""))
            clarified = False
            last = local == allowed
            if self._check_stop():
                return _Outcome.TERMINAL, f"safe-stop: {self._halt_reason}"

            ctx = AgentContext(
                run_id=self.run_id,
                stage=stage,
                workspace=self.workspace,
                requirement=self.requirement,
                inputs=inputs,
                attempt=attempt,
                feedback=progress.agent_feedback(),
                clarifications=list(progress.clarifications),
            )
            result = await self._invoke_agent(stage, ctx, agent)
            if self._charge(ctx.telemetry):
                return _Outcome.TERMINAL, f"safe-stop: {self._halt_reason}"
            if isinstance(result, ScopeViolation):
                # Breaching the autonomy boundary is a policy failure, not a flaky error: no retry.
                return _Outcome.TERMINAL, f"policy: {result}"
            if isinstance(result, FatalAgentError):
                return _Outcome.EXHAUSTED, f"non-retryable agent error: {result}"
            if isinstance(result, Exception):
                progress.feedback = [f"agent error: {result}"]
                if last:
                    return _Outcome.EXHAUSTED, f"agent error on attempt {attempt}; retries exhausted ({budget})"
                self._transition(stage.id, NodeState.RETRYING, f"agent error on attempt {attempt}")
                continue

            artifact = self._record_artifact(stage, attempt, result, ctx.changes, inputs,
                                             progress.clarifications, agent, progress.change_requests)

            policy = self._evaluate_policy(stage, attempt, ctx.changes)
            if policy.action is Action.BLOCK:
                return _Outcome.TERMINAL, f"policy blocked: {_violation_summary(policy)}"
            if policy.action is Action.REJECT:
                progress.feedback = [f"policy violation: {v.describe()}" for v in policy.at_least(Action.REJECT)]
                if last:
                    return _Outcome.EXHAUSTED, f"policy rejected change: {_violation_summary(policy)}; " \
                                               f"retries exhausted ({budget})"
                self._transition(stage.id, NodeState.RETRYING, f"policy rejected change: {_violation_summary(policy)}")
                continue
            if policy.action is Action.REQUIRE_APPROVAL:
                high_risk = policy.at_least(Action.REQUIRE_APPROVAL)
                decision = await self._approve(
                    stage, artifact,
                    reason=f"policy: {policy.tier.value}-risk change ({_violation_summary(policy)})",
                    evidence=[v.describe() for v in high_risk],
                    source="policy",
                )
                if not decision.approved:
                    return _Outcome.TERMINAL, f"rejected by {decision.approver}"
            self._apply(stage, ctx.changes)

            self._transition(stage.id, NodeState.VALIDATING, f"{len(stage.exit_gates)} exit gate(s)")
            gate_results = [
                await self._run_gate(ref, stage, artifact, inputs, phase="exit") for ref in stage.exit_gates
            ]
            failed = [r for r in gate_results if not r.passed]
            if failed:
                # Undo this attempt before anything else happens, so the next attempt (or the next
                # stage) never builds on rejected output.
                self._revert(stage, ctx.changes, progress, f"exit gate(s) failed: {[r.gate for r in failed]}")
            if failed and all(r.questions for r in failed) and progress.rounds < stage.clarification.max_rounds:
                # Only a human can resolve these: ask, then re-run the agent with the answers.
                progress.rounds += 1
                response, why = await self._clarify(stage, artifact, [q for r in failed for q in r.questions],
                                                    progress.rounds)
                if response is None:
                    return _Outcome.TERMINAL, why
                progress.clarifications += response.answers
                progress.feedback = [f"{len(response.answers)} open question(s) were answered by a human "
                                     "(see <clarifications>); treat each answer as a binding decision."]
                allowed += 1
                clarified = True
                self._transition(stage.id, NodeState.RETRYING,
                                 f"clarified by {response.answered_by} (round {progress.rounds}); re-running with answers")
                continue
            if failed:
                progress.feedback = [f"gate '{r.gate}' failed: {r.evidence}" for r in failed]
                reason = f"exit gate(s) failed: {[r.gate for r in failed]}"
                if last:
                    return _Outcome.EXHAUSTED, f"{reason}; retries exhausted ({budget})"
                self._transition(stage.id, NodeState.RETRYING, reason)
                continue

            if stage.approval is ApprovalMode.REQUIRED:
                decision = await self._approve(
                    stage, artifact,
                    reason="workflow declares this stage approval: required",
                    evidence=[f"{r.gate}: {'PASS' if r.passed else 'FAIL'}" for r in gate_results],
                    source="workflow",
                )
                if not decision.approved:
                    self._revert(stage, ctx.changes, progress, f"rejected by {decision.approver}")
                    comment = decision.comment.strip()
                    if comment and progress.revisions < stage.max_revisions:
                        progress.revisions += 1
                        progress.change_requests.append(comment)
                        progress.feedback = []
                        self.events.append(EventType.CHANGES_REQUESTED, stage.id, revision=progress.revisions,
                                           requested_by=decision.approver, comment=comment,
                                           artifact=artifact.ref().model_dump())
                        allowed += 1  # a revision is not a failure: it does not consume the retry budget
                        clarified = True
                        self._transition(stage.id, NodeState.RETRYING,
                                         f"changes requested by {decision.approver} (revision {progress.revisions})")
                        continue
                    return _Outcome.TERMINAL, f"rejected by {decision.approver}"
            self._accept(stage, artifact, ctx.changes)
            return _Outcome.SUCCEEDED, ""

        return _Outcome.EXHAUSTED, f"retries exhausted ({budget})"

    def _accept(self, stage: StageSpec, artifact: Artifact, changes: ChangeSet) -> None:
        self.artifacts[stage.id] = artifact
        self.events.append(EventType.ARTIFACT_ACCEPTED, stage.id, artifact=artifact.ref().model_dump())
        if self.git is not None and changes.paths:
            commit = self.git.checkpoint(
                changes.paths,
                f"orch({self.run_id}): {stage.id} {artifact.name}@v{artifact.version}\n\n"
                f"produced-by: {artifact.produced_by}\nartifact-sha: {artifact.sha}\n",
            )
            if commit:
                self.events.append(EventType.CHECKPOINT_COMMITTED, stage.id, commit=commit, files=changes.paths)
        self._transition(stage.id, NodeState.SUCCEEDED, f"accepted {artifact.name}@v{artifact.version}")

    def _revert(self, stage: StageSpec, changes: ChangeSet, progress: "_StageProgress", reason: str) -> None:
        if not changes.paths:
            return
        reverted, conflicts = revert_changes(self.workspace, changes)
        progress.reverted.update(reverted)
        self.events.append(EventType.CHANGES_REVERTED, stage.id, reason=reason, reverted=reverted,
                           conflicts=conflicts)

    async def _invoke_agent(self, stage: StageSpec, ctx: AgentContext, agent: str) -> AgentResult | Exception:
        self.events.append(
            EventType.AGENT_INVOKED,
            stage.id,
            agent=agent,
            attempt=ctx.attempt,
            inputs=[a.ref().model_dump() for a in ctx.inputs.values()],
            feedback=ctx.feedback,
        )
        started = time.monotonic()
        try:
            result = await self.agents.create(agent).run(ctx)
        except Exception as exc:  # agent failures are data, not crashes
            self.events.append(
                EventType.AGENT_ERROR, stage.id, agent=agent, attempt=ctx.attempt,
                error=f"{type(exc).__name__}: {exc}", llm_calls=ctx.telemetry,
            )
            return exc
        self.events.append(
            EventType.AGENT_COMPLETED,
            stage.id,
            agent=agent,
            attempt=ctx.attempt,
            summary=result.summary,
            files_proposed=ctx.changes.paths,
            llm_calls=ctx.telemetry,
            duration_ms=int((time.monotonic() - started) * 1000),
        )
        return result

    def _charge(self, telemetry: list[dict]) -> bool:
        """Add an attempt's LLM spend; returns True when the run must safe-stop."""
        self.cost_usd += sum(call.get("cost_usd", 0.0) for call in telemetry)
        if self.max_cost_usd is not None and self.cost_usd >= self.max_cost_usd:
            self._halt(f"cost budget reached (${self.cost_usd:.2f} of ${self.max_cost_usd:.2f})")
        return self._halt_reason is not None

    def _check_stop(self) -> bool:
        """Kill switch (`orch stop` writes the STOP file) and wall-clock budget. Both safe-stop:
        nothing new starts, state is preserved, and the run can be resumed."""
        if not self._halt_reason:
            if self.stop_file.exists():
                self._halt("stop requested")
            elif self.max_minutes is not None and time.monotonic() - self._started > self.max_minutes * 60:
                self._halt(f"time budget reached ({self.max_minutes:g} min)")
        return self._halt_reason is not None

    def _halt(self, reason: str) -> None:
        if not self._halt_reason:
            self._halt_reason = reason
            self.events.append(EventType.RUN_HALTED, reason=reason, cost_usd=round(self.cost_usd, 6))

    def _skip_unstarted(self, running: dict) -> None:
        for stage_id in self._order:
            if self.states[stage_id] in (NodeState.PENDING, NodeState.READY) and stage_id not in running.values():
                self._transition(stage_id, NodeState.SKIPPED, f"run halted: {self._halt_reason}")

    async def _approve(
        self, stage: StageSpec, artifact: Artifact, *, reason: str, evidence: list[str], source: str
    ) -> ApprovalDecision:
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
            artifact_sha=artifact.sha,  # a decision applies to exactly this content
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
        return decision

    async def _clarify(self, stage: StageSpec, artifact: Artifact, questions: list[dict[str, str]],
                       round_: int) -> tuple[ClarificationResponse | None, str]:
        self._transition(stage.id, NodeState.AWAITING_APPROVAL,
                         f"awaiting human answers to {len(questions)} question(s) (round {round_})")
        request = ClarificationRequest(run_id=self.run_id, stage=stage.id, round=round_, questions=questions)
        self.events.append(EventType.CLARIFICATION_REQUESTED, stage.id, round=round_, questions=questions,
                           artifact=artifact.ref().model_dump())
        response = await self.approver.clarify(request)
        if response is None:
            return None, "open questions need a human, and none was available"
        missing = response.missing(request)
        if missing:
            return None, f"clarification incomplete: {len(missing)} unanswered"
        self.events.append(EventType.CLARIFICATION_ANSWERED, stage.id, round=round_, answers=response.answers,
                           answered_by=response.answered_by, source=response.source)
        for a in response.answers:
            self.events.append(EventType.DECISION_RECORDED, stage.id, topic=a["question"], choice=a["answer"],
                               rationale=f"answered by {response.answered_by}", source=response.source)
        return response, ""

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
        self, stage: StageSpec, attempt: int, result: AgentResult, changes: ChangeSet, inputs: dict[str, Artifact],
        clarifications: list[dict[str, str]] = (), agent: str | None = None, change_requests: list[str] = (),
    ) -> Artifact:
        # The proposed change set is authoritative, not the agent's claim about what it wrote.
        result = result.model_copy(update={"files_written": changes.paths})
        if clarifications:
            # Human answers travel with the artifact verbatim, so downstream stages see them
            # even if the agent paraphrased or dropped one.
            result = result.model_copy(update={"outputs": {**result.outputs, "clarifications": list(clarifications)}})
        if change_requests:
            result = result.model_copy(update={"outputs": {**result.outputs, "change_requests": list(change_requests)}})
        version = self._versions.get(stage.id, 0) + 1
        self._versions[stage.id] = version
        file_hashes = changes.file_hashes()
        sha = _sha(json.dumps({"result": result.model_dump(), "files": file_hashes}, sort_keys=True))
        artifact = Artifact(
            name=stage.id,
            version=version,
            sha=sha,
            produced_by=f"{stage.id}/{agent or stage.agent}#{attempt}",
            inputs=[a.ref() for a in inputs.values()],
            result=result,
        )
        self.artifacts_dir.mkdir(parents=True, exist_ok=True)
        body = artifact.model_dump_json(indent=2)
        (self.artifacts_dir / f"{stage.id}.v{version}.json").write_text(body, encoding="utf-8")
        self.events.append(
            EventType.ARTIFACT_RECORDED,
            stage.id,
            artifact=artifact.ref().model_dump(),
            produced_by=artifact.produced_by,
            inputs=[r.model_dump() for r in artifact.inputs],
            file_hashes=file_hashes,
            artifact_file_sha=_sha(body),  # lets a resume detect a tampered artifact file
        )
        for d in result.decisions:
            self.events.append(
                EventType.DECISION_RECORDED, stage.id, artifact=artifact.ref().model_dump(), **d.model_dump()
            )
        return artifact

    def _restore(self) -> None:
        """Rebuild run state from the (verified) event log, keep accepted stages, and reset the rest."""
        ok, message = EventStore.verify(self.events.path)
        if not ok:
            raise ResumeError(f"refusing to resume: audit log failed verification ({message})")
        events = EventStore.load(self.events.path)
        started = next((e for e in events if e.type == EventType.RUN_STARTED), None)
        if started is None:
            raise ResumeError("refusing to resume: the event log has no RUN_STARTED")
        if started.payload["workflow"] != self.workflow.name or set(started.payload["stages"]) != set(self._order):
            raise ResumeError("refusing to resume: the workflow differs from the one this run started with")

        previous = replay_states(events)
        file_shas: dict[tuple[str, int], str] = {}
        accepted: dict[str, dict] = {}
        for e in events:
            if e.type == EventType.ARTIFACT_RECORDED:
                ref = e.payload["artifact"]
                self._versions[e.stage] = max(self._versions.get(e.stage, 0), ref["version"])
                file_shas[(e.stage, ref["version"])] = e.payload.get("artifact_file_sha", "")
            elif e.type == EventType.ARTIFACT_ACCEPTED:
                accepted[e.stage] = e.payload["artifact"]
            elif e.type in (EventType.AGENT_COMPLETED, EventType.AGENT_ERROR):
                self.cost_usd += sum(c.get("cost_usd", 0.0) for c in e.payload.get("llm_calls", []))

        kept, reset = [], {}
        for stage_id in self._order:
            if previous.get(stage_id) is NodeState.SUCCEEDED:
                self.artifacts[stage_id] = self._load_accepted(stage_id, accepted.get(stage_id), file_shas)
                self.states[stage_id] = NodeState.SUCCEEDED
                kept.append(stage_id)
            else:
                reset[stage_id] = previous.get(stage_id, NodeState.PENDING).value

        discarded = []
        if self.git is not None and reset:
            scopes = [g for s in reset for g in self.workflow.stage(s).write_scope]
            discarded = self.git.discard_uncommitted(scopes)
        stop_cleared = self.stop_file.exists()
        self.stop_file.unlink(missing_ok=True)
        self.events.append(
            EventType.RUN_RESUMED, kept=kept, reset=reset, discarded_uncommitted=discarded,
            stop_cleared=stop_cleared, cost_usd_so_far=round(self.cost_usd, 6),
            policy_sha=self.policy.policy_sha, policy_changed=self.policy.policy_sha != started.payload["policy_sha"],
            workflow_sha=self._workflow_sha(),
            workflow_changed=self._workflow_sha() != started.payload.get("workflow_sha"),
        )
        for stage_id, was in reset.items():
            if was != NodeState.PENDING.value:  # a sanctioned reset, recorded like any other transition
                self.events.append(EventType.STAGE_STATE, stage_id, **{"from": was, "to": NodeState.PENDING.value},
                                   reason=f"resume: was {was}")

    def _workflow_sha(self) -> str:
        """Hash of the parsed workflow (not the file, so comments and formatting don't count):
        which stages, gates, scopes and limits governed the run is part of its audit trail."""
        return _sha(self.workflow.model_dump_json())

    def _load_accepted(self, stage_id: str, ref: dict | None, file_shas: dict) -> Artifact:
        if ref is None:
            raise ResumeError(f"refusing to resume: no accepted artifact recorded for '{stage_id}'")
        path = self.artifacts_dir / f"{stage_id}.v{ref['version']}.json"
        body = path.read_text(encoding="utf-8") if path.exists() else ""
        if not body or _sha(body) != file_shas.get((stage_id, ref["version"])):
            raise ResumeError(f"refusing to resume: artifact {path.name} is missing or was modified")
        artifact = Artifact.model_validate_json(body)
        if artifact.sha != ref["sha"]:
            raise ResumeError(f"refusing to resume: artifact {path.name} does not match its recorded hash")
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
