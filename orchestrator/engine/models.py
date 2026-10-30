"""Core contracts shared by every layer: workflow spec, artifacts, gate results.

These are deliberately small and declarative. The workflow YAML is parsed into
`WorkflowSpec`; everything the engine produces at runtime is an `Artifact`
(content-addressed, with lineage) or an event in the audit log.
"""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, field_validator


class ApprovalMode(str, Enum):
    NONE = "none"          # agent output is accepted once exit gates pass
    REQUIRED = "required"  # a human must approve after exit gates pass
    POLICY = "policy"      # policy engine decides from the action's risk tier


class RetryPolicy(BaseModel):
    max_attempts: int = Field(default=1, ge=1, le=10)  # bounded by design
    backoff_seconds: float = Field(default=0.0, ge=0)


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
    fallback: str | None = None  # alternate agent name, used after retries are exhausted
    write_scope: list[str] = Field(default_factory=list)  # glob patterns, relative to workspace

    @field_validator("entry_gates", "exit_gates", mode="before")
    @classmethod
    def _normalize_gates(cls, v: Any) -> Any:
        return [_coerce_gate(g) for g in (v or [])]


class WorkflowSpec(BaseModel):
    name: str
    version: str = "1"
    description: str = ""
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
