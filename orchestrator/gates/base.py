"""Gate contract.

Gates are run by the orchestrator, never by agents: an agent claiming its
tests pass is not evidence; the gate running them is.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from ..engine.models import Artifact, GateResult, StageSpec


@dataclass
class GateContext:
    stage: StageSpec
    workspace: Path
    artifact: Artifact | None            # None for entry gates
    inputs: dict[str, Artifact]          # upstream artifacts keyed by stage id


class Gate(ABC):
    name: str = "gate"

    def __init__(self, **args: Any) -> None:
        self.args = args

    @abstractmethod
    async def check(self, ctx: GateContext) -> GateResult: ...

    def result(self, passed: bool, evidence: str) -> GateResult:
        return GateResult(gate=self.name, passed=passed, evidence=evidence)


class GateRegistry:
    def __init__(self) -> None:
        self._types: dict[str, Callable[..., Gate]] = {}

    def register(self, name: str, factory: Callable[..., Gate]) -> None:
        self._types[name] = factory

    def create(self, name: str, args: dict[str, Any]) -> Gate:
        if name not in self._types:
            raise KeyError(f"unknown gate '{name}' (known: {sorted(self._types)})")
        return self._types[name](**args)

    def __contains__(self, name: str) -> bool:
        return name in self._types
