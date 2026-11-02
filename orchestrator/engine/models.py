"""Core contracts shared by every layer: workflow spec, artifacts, gate results.

These are deliberately small and declarative. The workflow YAML is parsed into
`WorkflowSpec`; everything the engine produces at runtime is an `Artifact`
(content-addressed, with lineage) or an event in the audit log.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator


class ApprovalMode(str, Enum):
    """Workflow-declared checkpoint. Independent of, and never a waiver for,
    approvals the policy engine requires for high-risk changes."""

    NONE = "none"          # accepted once exit gates pass (unless policy requires approval)
    REQUIRED = "required"  # a human must approve the verified output


class RetryPolicy(BaseModel):
    max_attempts: int = Field(default=1, ge=1, le=10)  # bounded by design
    backoff_seconds: float = Field(default=0.0, ge=0)


class ClarificationPolicy(BaseModel):
    """How many times a stage may pause for human answers to open questions a gate raised.
    Each round adds one agent attempt that does not consume the retry budget."""

    max_rounds: int = Field(default=0, ge=0, le=5)


class GateRef(BaseModel):
    """A gate invocation in the workflow: registry name plus arguments."""

    name: str
    args: dict[str, Any] = Field(default_factory=dict)


def _coerce_gate(value: Any) -> Any:
    # YAML allows `- maven_test` or `- {name: files_exist, args: {...}}`
    if isinstance(value, str):
        return {"name": value}
    return value


class StageSpec(BaseModel):
    id: str
    agent: str
    description: str = ""
    needs: list[str] = Field(default_factory=list)
    entry_gates: list[GateRef] = Field(default_factory=list)
    exit_gates: list[GateRef] = Field(default_factory=list)
    approval: ApprovalMode = ApprovalMode.NONE
    retry: RetryPolicy = Field(default_factory=RetryPolicy)
    clarification: ClarificationPolicy = Field(default_factory=ClarificationPolicy)
    # A workflow-approval rejection *with a comment* sends the comment back to the agent as a binding
    # change request and re-runs the stage, up to this many times. Without a comment it is final.
    max_revisions: int = Field(default=0, ge=0, le=5)
    fallback: str | None = None  # alternate agent name, used after retries are exhausted
    write_scope: list[str] = Field(default_factory=list)  # glob patterns, relative to workspace
    read_scope: list[str] = Field(default_factory=list)   # files the agent is shown as context
    downstream_context: bool = False  # also show the agent where each later stage may write
    gate_context: bool = False  # also show the agent the exit-gate results of its accepted upstream artifacts

    @field_validator("entry_gates", "exit_gates", mode="before")
    @classmethod
    def _normalize_gates(cls, v: Any) -> Any:
        return [_coerce_gate(g) for g in (v or [])]


class WorkflowSelection(BaseModel):
    """How `orch run auto` decides whether this workflow fits a requirement."""

    use_when: str                            # what kind of requirement this workflow is for
    codebase: Literal["new", "existing"]     # eligible only when the codebase is absent / present


class WorkflowSpec(BaseModel):
    name: str
    version: str = "1"
    description: str = ""
    selection: WorkflowSelection | None = None  # absent: never chosen automatically (e.g. fault-demo)
    stages: list[StageSpec]

    def stage(self, stage_id: str) -> StageSpec:
        for s in self.stages:
            if s.id == stage_id:
                return s
        raise KeyError(stage_id)


class Decision(BaseModel):
    """A recorded choice, made by an agent or a human, with its rationale."""

    topic: str
    choice: str
    rationale: str = ""
    source: str = "agent"  # agent | assumption | human


class AgentResult(BaseModel):
    """What an agent returns. Structured, so gates can verify it mechanically."""

    summary: str
    outputs: dict[str, Any] = Field(default_factory=dict)
    files_written: list[str] = Field(default_factory=list)
    decisions: list[Decision] = Field(default_factory=list)


class ArtifactRef(BaseModel):
    name: str
    version: int
    sha: str


class Artifact(BaseModel):
    """Versioned, content-addressed output of a stage, with input lineage."""

    name: str
    version: int
    sha: str
    produced_by: str  # "<stage>/<agent>#attempt"
    inputs: list[ArtifactRef] = Field(default_factory=list)
    result: AgentResult

    def ref(self) -> ArtifactRef:
        return ArtifactRef(name=self.name, version=self.version, sha=self.sha)


class GateResult(BaseModel):
    gate: str
    passed: bool
    evidence: str = ""  # human-readable proof; fed back to the agent on retry
    duration_ms: int = 0
    # Open questions only a human can answer. A failure carrying questions can be
    # resolved by clarification instead of a blind retry.
    questions: list[dict[str, str]] = Field(default_factory=list)
