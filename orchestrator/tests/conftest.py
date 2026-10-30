"""Test doubles: scriptable agents and gates, plus an engine factory."""

from __future__ import annotations

import asyncio
import time
from pathlib import Path
from typing import Callable

import pytest

from orchestrator.agents.base import Agent, AgentContext, AgentRegistry
from orchestrator.approvals.service import AutoApprover
from orchestrator.engine.models import AgentResult, GateResult, WorkflowSpec
from orchestrator.engine.scheduler import Engine
from orchestrator.gates.base import Gate, GateContext, GateRegistry


class Recorder:
    """Shared log of agent calls: (stage, attempt, start, end, feedback)."""

    def __init__(self) -> None:
        self.calls: list[dict] = []

    def window(self, stage: str) -> tuple[float, float]:
        call = [c for c in self.calls if c["stage"] == stage][-1]
        return call["start"], call["end"]

    def attempts(self, stage: str) -> list[dict]:
        return [c for c in self.calls if c["stage"] == stage]


def make_agent(recorder: Recorder, *, delay: float = 0.0,
               behaviour: Callable[[AgentContext], AgentResult | None] | None = None) -> Callable[[], Agent]:
    class ScriptedAgent(Agent):
        name = "scripted"

        async def run(self, ctx: AgentContext) -> AgentResult:
            start = time.monotonic()
            await asyncio.sleep(delay)
            call = {"stage": ctx.stage.id, "attempt": ctx.attempt, "start": start, "feedback": ctx.feedback}
            recorder.calls.append(call)
            try:
                result = behaviour(ctx) if behaviour else None
            finally:
                call["end"] = time.monotonic()
            return result or AgentResult(summary=f"{ctx.stage.id} done", outputs={"ok": True})

    return ScriptedAgent


class PassGate(Gate):
    name = "pass"

    async def check(self, ctx: GateContext) -> GateResult:
        return self.result(True, "ok")


class FailUntilGate(Gate):
    """Fails until the artifact's attempt number reaches `pass_on` (0 = always fail)."""

    name = "fail_until"

    async def check(self, ctx: GateContext) -> GateResult:
        attempt = int(ctx.artifact.produced_by.rsplit("#", 1)[1])
        pass_on = self.args.get("pass_on", 0)
        if pass_on and attempt >= pass_on:
            return self.result(True, f"passed on attempt {attempt}")
        return self.result(False, f"assertion failed on attempt {attempt}")


class FailGate(Gate):
    name = "fail"

    async def check(self, ctx: GateContext) -> GateResult:
        return self.result(False, "precondition not met")


@pytest.fixture
def recorder() -> Recorder:
    return Recorder()


@pytest.fixture
def gates() -> GateRegistry:
    registry = GateRegistry()
    for g in (PassGate, FailUntilGate, FailGate):
        registry.register(g.name, g)
    return registry


@pytest.fixture
def build_engine(tmp_path: Path, gates: GateRegistry):
    def _build(workflow: dict, agents: dict[str, Callable[[], Agent]], approver=None, **kwargs) -> Engine:
        registry = AgentRegistry()
        for name, factory in agents.items():
            registry.register(name, factory)
        return Engine(
            WorkflowSpec.model_validate(workflow),
            registry,
            gates,
            approver or AutoApprover(),
            run_id="test-run",
            run_dir=tmp_path / "run",
            workspace=tmp_path / "ws",
            requirement="test requirement",
            **kwargs,
        )

    (tmp_path / "ws").mkdir()
    return _build
