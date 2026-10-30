"""Human approval checkpoints.

An `Approver` is asked to decide on a stage's verified output. The CLI approver
prompts a human; `AutoApprover` exists for CI and tests and records itself as
the approver so the audit log never pretends a human signed off.
"""

from __future__ import annotations

import asyncio
import getpass
from abc import ABC, abstractmethod

from pydantic import BaseModel, Field


class ApprovalRequest(BaseModel):
    run_id: str
    stage: str
    reason: str                      # why approval is required
    summary: str                     # agent's summary of its output
    gate_evidence: list[str] = Field(default_factory=list)
    files_changed: list[str] = Field(default_factory=list)
    decisions: list[str] = Field(default_factory=list)


class ApprovalDecision(BaseModel):
    approved: bool
    approver: str
    comment: str = ""


class Approver(ABC):
    @abstractmethod
    async def decide(self, request: ApprovalRequest) -> ApprovalDecision: ...


class AutoApprover(Approver):
    def __init__(self, approve: bool = True, identity: str = "auto-approver(non-human)"):
        self.approve = approve
        self.identity = identity

    async def decide(self, request: ApprovalRequest) -> ApprovalDecision:
        return ApprovalDecision(approved=self.approve, approver=self.identity, comment="automatic")


class CLIApprover(Approver):
    """Interactive terminal approval. Serialized so parallel stages don't interleave prompts."""

    def __init__(self) -> None:
        self._lock = asyncio.Lock()

    async def decide(self, request: ApprovalRequest) -> ApprovalDecision:
        async with self._lock:
            return await asyncio.to_thread(self._prompt, request)

    @staticmethod
    def _prompt(req: ApprovalRequest) -> ApprovalDecision:
        bar = "=" * 72
        lines = [
            "",
            bar,
            f"APPROVAL REQUIRED  run={req.run_id}  stage={req.stage}",
            f"Reason : {req.reason}",
            f"Summary: {req.summary}",
        ]
        if req.decisions:
            lines.append("Decisions:")
            lines += [f"  - {d}" for d in req.decisions]
        if req.files_changed:
            lines.append("Files changed:")
            lines += [f"  - {f}" for f in req.files_changed]
        if req.gate_evidence:
            lines.append("Gate evidence:")
            lines += [f"  - {g}" for g in req.gate_evidence]
        lines.append(bar)
        print("\n".join(lines))
        while True:
            answer = input("Approve? [y]es / [n]o: ").strip().lower()
            if answer in {"y", "yes", "n", "no"}:
                break
        comment = input("Comment (optional): ").strip()
        return ApprovalDecision(
            approved=answer.startswith("y"), approver=getpass.getuser(), comment=comment
        )
