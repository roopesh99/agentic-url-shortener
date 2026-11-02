"""Workflow selection. Eligibility is decided by rules (does the codebase exist?); among the eligible
workflows a selector agent proposes one, constrained to their names; a person confirms it, or rejects
it with a comment that the selector must follow (bounded). The record goes into RUN_STARTED."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, create_model

from ..agents.base import AgentContext
from ..agents.llm_agents import LLMAgent, _canonical, _tag
from ..approvals.service import ApprovalRequest, Approver
from ..engine.dag import load_workflow
from ..engine.models import AgentResult, StageSpec, WorkflowSpec
from ..llm.client import LLMClient

CODEBASE_MARKER = "url-shortener/pom.xml"  # present: the service exists (brownfield); absent: greenfield
MAX_REVISIONS = 2


class Candidate(BaseModel):
    name: str
    path: str
    description: str
    use_when: str
    codebase: str


class SelectionRejected(Exception):
    pass


def catalog(workflows_dir: Path) -> list[Candidate]:
    """Every workflow that declares how it is selected; others (demos) are never chosen automatically."""
    out = []
    for path in sorted(workflows_dir.glob("*.yaml")):
        wf: WorkflowSpec = load_workflow(path)
        if wf.selection:
            out.append(Candidate(name=wf.name, path=str(path), description=wf.description,
                                 use_when=wf.selection.use_when, codebase=wf.selection.codebase))
    return out


def eligible(candidates: list[Candidate], workspace: Path, marker: str = CODEBASE_MARKER):
    """(eligible, {excluded name: reason}, facts) — a rule, not a model, decides this."""
    exists = (workspace / marker).is_file()
    facts = {"codebase": "existing" if exists else "new", "marker": marker}
    ok = [c for c in candidates if c.codebase == facts["codebase"]]
    excluded = {c.name: f"needs a {c.codebase} codebase; {marker} {'exists' if exists else 'is absent'}"
                for c in candidates if c not in ok}
    return ok, excluded, facts


class SelectorAgent(LLMAgent):
    name = "selector"
    prompts = ("selector",)
    effort = "medium"
    max_tokens = 4000

    def __init__(self, llm: LLMClient, model: str, choices: list[Candidate], facts: dict) -> None:
        super().__init__(llm, model)
        self.choices, self.facts = choices, facts
        names = tuple(c.name for c in choices)
        self.output_model = create_model(  # the schema itself forbids naming anything else
            "SelectorOutput",
            workflow=(Literal[names], ...),
            confidence=(Literal["high", "medium", "low"], ...),
            rationale=(str, ...),
            signals=(list[str], ...),
            runner_up=(Literal[names + ("none",)], ...),
        )

    def task(self, ctx):
        workflows = [{"name": c.name, "description": c.description, "use_when": c.use_when} for c in self.choices]
        return [_tag("requirement", ctx.requirement), _tag("eligible_workflows", _canonical(workflows)),
                _tag("workspace_facts", _canonical(self.facts))]

    def to_result(self, ctx, out):
        return AgentResult(summary=out.rationale, outputs=out.model_dump())


async def propose(requirement: str, workspace: Path, choices: list[Candidate], facts: dict,
                  llm: LLMClient | None, model: str, feedback: list[str]) -> dict:
    """One proposal. A single eligible workflow is proposed by rule, without a model call."""
    if len(choices) == 1:
        return {"workflow": choices[0].name, "confidence": "high", "source": "rule", "signals": [],
                "rationale": f"the only workflow eligible for a {facts['codebase']} codebase", "runner_up": "none"}
    if llm is None:
        raise SelectionRejected("several workflows are eligible and no selector model is configured")
    agent = SelectorAgent(llm, model, choices, facts)
    ctx = AgentContext(run_id="select", stage=StageSpec(id="select", agent="selector"), workspace=workspace,
                       requirement=requirement, inputs={}, attempt=len(feedback) + 1,
                       feedback=[f"The reviewer rejected the previous proposal: {c}" for c in feedback])
    result = await agent.run(ctx)
    return {**result.outputs, "source": "model", "llm": ctx.telemetry}


async def select(requirement: str, workspace: Path, workflows_dir: Path, approver: Approver, run_id: str, *,
                 llm: LLMClient | None, model: str, marker: str = CODEBASE_MARKER) -> tuple[Candidate, dict]:
    candidates = catalog(workflows_dir)
    choices, excluded, facts = eligible(candidates, workspace, marker)
    if not choices:
        raise SelectionRejected(f"no workflow is eligible for a {facts['codebase']} codebase")
    record = {"facts": facts, "eligible": [c.name for c in choices], "excluded": excluded,
              "proposals": [], "decisions": []}
    comments: list[str] = []
    while True:
        proposal = await propose(requirement, workspace, choices, facts, llm, model, comments)
        record["proposals"].append(proposal)
        content = _canonical({k: v for k, v in proposal.items() if k != "llm"} | {"eligible": record["eligible"]})
        request = ApprovalRequest(
            run_id=run_id, stage="select", reason="confirm the workflow this requirement will run through",
            summary=f"{proposal['workflow']} ({proposal['confidence']} confidence): {proposal['rationale']}",
            gate_evidence=[f"eligible: {', '.join(record['eligible'])}"]
                          + [f"excluded {n}: {r}" for n, r in excluded.items()]
                          + [f"signal: {s}" for s in proposal["signals"]],
            files_changed=[], decisions=[f"runner-up: {proposal['runner_up']}"],
            artifact_sha=hashlib.sha256(content.encode()).hexdigest(),
        )
        decision = await approver.decide(request)
        record["decisions"].append({"approved": decision.approved, "approver": decision.approver,
                                    "comment": decision.comment, "artifact_sha": request.artifact_sha})
        if decision.approved:
            chosen = next(c for c in choices if c.name == proposal["workflow"])
            record["chosen"] = chosen.name
            return chosen, record
        if not decision.comment or len(comments) >= MAX_REVISIONS:
            raise SelectionRejected(f"workflow selection rejected by {decision.approver}"
                                    + (f": {decision.comment}" if decision.comment else ""))
        comments.append(decision.comment)
