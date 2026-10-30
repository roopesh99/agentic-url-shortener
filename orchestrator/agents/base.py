"""Agent contract and the scoped workspace handle agents act through.

Agents never touch the filesystem directly: they receive an `AgentContext`
whose `write_file` enforces the stage's `write_scope`. That allowlist is the
agent's autonomy boundary — an out-of-scope write fails the attempt.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from fnmatch import fnmatch
from pathlib import Path
from typing import Callable

from ..engine.models import AgentResult, Artifact, StageSpec


class ScopeViolation(PermissionError):
    pass


@dataclass
class AgentContext:
    run_id: str
    stage: StageSpec
    workspace: Path
    requirement: str
    inputs: dict[str, Artifact]  # upstream artifacts keyed by stage id
    attempt: int = 1
    feedback: list[str] = field(default_factory=list)  # gate evidence from failed attempts
    _written: list[str] = field(default_factory=list)

    def in_scope(self, rel_path: str) -> bool:
        return any(fnmatch(rel_path, pattern) for pattern in self.stage.write_scope)

    def write_file(self, rel_path: str, content: str) -> Path:
        rel = Path(rel_path)
        if rel.is_absolute() or ".." in rel.parts:
            raise ScopeViolation(f"path escapes workspace: {rel_path}")
        if not self.in_scope(rel.as_posix()):
            raise ScopeViolation(
                f"stage '{self.stage.id}' may not write '{rel_path}' (scope: {self.stage.write_scope})"
            )
        target = self.workspace / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        self._written.append(rel.as_posix())
        return target

    @property
    def written(self) -> list[str]:
        return list(self._written)


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
