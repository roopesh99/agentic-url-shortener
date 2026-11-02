"""Built-in gates used by the workflows."""

from __future__ import annotations

import asyncio
import re
import shutil
from typing import Any

from ..engine.models import GateResult
from .base import Gate, GateContext, GateRegistry


class FilesExistGate(Gate):
    """args: paths: [relative paths that must exist in the workspace]"""

    name = "files_exist"

    async def check(self, ctx: GateContext) -> GateResult:
        missing = [p for p in self.args.get("paths", []) if not (ctx.workspace / p).exists()]
        if missing:
            return self.result(False, f"missing files: {missing}")
        return self.result(True, f"{len(self.args.get('paths', []))} file(s) present")


class OutputsPresentGate(Gate):
    """Structural check of the agent's output. args: keys: [required top-level output keys]"""

    name = "outputs_present"

    async def check(self, ctx: GateContext) -> GateResult:
        assert ctx.artifact is not None, "outputs_present is an exit gate"
        outputs = ctx.artifact.result.outputs
        missing = [k for k in self.args.get("keys", []) if not outputs.get(k)]
        if missing:
            return self.result(False, f"output missing or empty: {missing}")
        return self.result(True, f"outputs present: {self.args.get('keys', [])}")


class AmbiguitiesResolvedGate(Gate):
    """Every open question the analyst surfaced must carry a resolution
    (an explicit assumption or a human answer) before design may proceed."""

    name = "ambiguities_resolved"

    async def check(self, ctx: GateContext) -> GateResult:
        assert ctx.artifact is not None, "ambiguities_resolved is an exit gate"
        outputs = ctx.artifact.result.outputs
        items: list[dict[str, Any]] = outputs.get("ambiguities", [])
        answered = {c["question"] for c in outputs.get("clarifications", [])}  # human answers are binding
        open_items = [a for a in items if not a.get("resolution") and a["question"] not in answered]
        if open_items:
            result = self.result(False, f"{len(open_items)} unresolved: {[a['question'] for a in open_items]}")
            result.questions = [{"question": a["question"], "why": a.get("rationale", "")} for a in open_items]
            return result
        return self.result(True, f"{len(items)} ambiguity(ies), all resolved ({len(answered)} by a human)")


class MavenTestGate(Gate):
    """Runs the real build. args: project: dir relative to workspace; goal: default 'test';
    timeout_seconds: default 600; min_tests: fail unless at least this many tests ran (guards a
    brownfield change against deleting or skipping the existing suite)."""

    name = "maven_test"

    async def check(self, ctx: GateContext) -> GateResult:
        mvn = shutil.which("mvn")
        if mvn is None:
            return self.result(False, "mvn not found on PATH")
        project = ctx.workspace / self.args.get("project", ".")
        if not (project / "pom.xml").exists():
            return self.result(False, f"no pom.xml in {project}")
        goal = self.args.get("goal", "test")
        runs_tests = goal not in ("compile", "test-compile")
        if runs_tests:
            # reports from earlier builds must not count: a deleted test class would still meet the floor
            shutil.rmtree(project / "target" / "surefire-reports", ignore_errors=True)
        proc = await asyncio.create_subprocess_exec(
            mvn, "-B", "-q", "--no-transfer-progress", goal,
            cwd=project,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        try:
            out, _ = await asyncio.wait_for(proc.communicate(), timeout=self.args.get("timeout_seconds", 600))
        except asyncio.TimeoutError:
            proc.kill()
            return self.result(False, f"mvn {goal} timed out")
        log = out.decode(errors="replace")
        if proc.returncode != 0:
            return self.result(False, f"mvn {goal} exit {proc.returncode}\n{_failure_excerpt(log)}")
        ran = _tests_run(project)
        minimum = self.args.get("min_tests")
        if minimum is not None and ran < minimum:
            return self.result(False, f"mvn {goal} passed but only {ran} tests ran; at least {minimum} required "
                                      "(existing tests must not be removed or skipped)")
        return self.result(True, f"mvn {goal} passed{_surefire_summary(project) if runs_tests else ''}")


def _failure_excerpt(log: str, limit: int = 60) -> str:
    """Keep the lines an engineer (or a retrying agent) needs: errors and failures."""
    interesting = [l for l in log.splitlines() if re.search(r"ERROR|FAIL|Tests run|expected|Exception", l)]
    return "\n".join((interesting or log.splitlines())[-limit:])


def _tests_run(project) -> int:
    total = 0
    for report in (project / "target" / "surefire-reports").glob("*.txt"):
        m = re.search(r"Tests run: (\d+)", report.read_text(errors="replace"))
        total += int(m.group(1)) if m else 0
    return total


def _surefire_summary(project) -> str:
    reports = list((project / "target" / "surefire-reports").glob("*.txt"))
    total = 0
    for r in reports:
        m = re.search(r"Tests run: (\d+)", r.read_text(errors="replace"))
        total += int(m.group(1)) if m else 0
    return f" ({total} tests in {len(reports)} class(es))" if reports else ""


def builtin_gates() -> GateRegistry:
    from .api import ChecklistPassedGate, DocsCoverApiGate, OpenApiConformanceGate, OpenApiValidGate
    from .coverage import CoverageGate
    from .regression import RegressionReproducesGate
    from .smoke import ServiceSmokeGate

    registry = GateRegistry()
    for gate in (FilesExistGate, OutputsPresentGate, AmbiguitiesResolvedGate, MavenTestGate,
                 OpenApiValidGate, OpenApiConformanceGate, DocsCoverApiGate, ChecklistPassedGate,
                 RegressionReproducesGate, CoverageGate, ServiceSmokeGate):
        registry.register(gate.name, gate)
    return registry
