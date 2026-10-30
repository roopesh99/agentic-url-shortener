"""Agent contract and the scoped workspace handle agents act through.

Agents never touch the filesystem directly: they receive an `AgentContext`
whose `write_file` *proposes* a change, checked against the stage's
`write_scope` (the agent's autonomy boundary). Proposed changes are only
applied by the engine after the policy engine has evaluated them.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from fnmatch import fnmatch
from pathlib import Path
from typing import Callable

from ..engine.models import AgentResult, Artifact, StageSpec
from ..workspace.changes import ChangeSet, ScopeViolation, resolve_in_workspace

__all__ = ["Agent", "AgentContext", "AgentRegistry", "ScopeViolation"]


@dataclass
class AgentContext:
    run_id: str
    stage: StageSpec
    workspace: Path
    requirement: str
    inputs: dict[str, Artifact]  # upstream artifacts keyed by stage id
    attempt: int = 1
    feedback: list[str] = field(default_factory=list)  # gate/policy evidence from failed attempts
    changes: ChangeSet = field(default_factory=ChangeSet)

    def in_scope(self, rel_path: str) -> bool:
        return any(fnmatch(rel_path, pattern) for pattern in self.stage.write_scope)

    def write_file(self, rel_path: str, content: str) -> None:
        """Propose a file write. Nothing touches disk until the engine applies the change set."""
        resolve_in_workspace(self.workspace, rel_path)  # escape / symlink check
        if not self.in_scope(Path(rel_path).as_posix()):
            raise ScopeViolation(
                f"stage '{self.stage.id}' may not write '{rel_path}' (scope: {self.stage.write_scope})"
            )
        self.changes.stage(self.workspace, rel_path, content)

    def read_file(self, rel_path: str) -> str | None:
        """Current view of a file: this stage's pending change if any, else disk."""
        rel = Path(rel_path).as_posix()
        if rel in self.changes.changes:
            return self.changes.changes[rel].content
        target = resolve_in_workspace(self.workspace, rel_path)
        return target.read_text(encoding="utf-8") if target.is_file() else None


class Agent(ABC):
    name: str = "agent"

    @abstractmethod
    async def run(self, ctx: AgentContext) -> AgentResult:
        """Do the stage's work. Raise on failure; the engine handles retries."""


class AgentRegistry:
    def __init__(self) -> None:
        self._factories: dict[str, Callable[[], Agent]] = {}

    def register(self, name: str, factory: Callable[[], Agent]) -> None:
        self._factories[name] = factory

    def create(self, name: str) -> Agent:
        if name not in self._factories:
            raise KeyError(f"unknown agent '{name}' (known: {sorted(self._factories)})")
        return self._factories[name]()

    def __contains__(self, name: str) -> bool:
        return name in self._factories
