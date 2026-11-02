"""Bug-fix gate: the regression tests a stage wrote reproduce the bug. They must compile and run,
at least one of them must fail, and nothing else may fail: a failing pre-existing test means the
workspace is broken, not that the bug was reproduced."""

from __future__ import annotations

import asyncio
import shutil
import xml.etree.ElementTree as ET
from pathlib import Path

from ..engine.models import GateResult
from .base import Gate, GateContext
from .builtin import _failure_excerpt


def failing_tests(reports: Path) -> list[tuple[str, str, str]]:
    """(class, test, message) for every failed or errored test case in the JUnit XML reports."""
    failed = []
    for report in sorted(reports.glob("TEST-*.xml")):
        for case in ET.parse(report).getroot().iter("testcase"):
            problem = case.find("failure")
            if problem is None:
                problem = case.find("error")
            if problem is not None:
                message = (problem.get("message") or problem.get("type") or "").strip().splitlines()
                failed.append((case.get("classname", ""), case.get("name", ""), message[0][:300] if message else ""))
    return failed


def source_file(classname: str, project_rel: str) -> str:
    """`com.x.FooTest$Nested` -> `<project>/src/test/java/com/x/FooTest.java`."""
    top = classname.split("$", 1)[0]
    return f"{project_rel}/src/test/java/{top.replace('.', '/')}.java"


class RegressionReproducesGate(Gate):
    """args: project — the Maven project, relative to the workspace; timeout_seconds."""

    name = "regression_reproduces"

    async def check(self, ctx: GateContext) -> GateResult:
        assert ctx.artifact is not None, "regression_reproduces is an exit gate"
        mvn = shutil.which("mvn")
        if mvn is None:
            return self.result(False, "mvn not found on PATH")
        project_rel = self.args.get("project", ".")
        project = ctx.workspace / project_rel
        reports = project / "target" / "surefire-reports"
        shutil.rmtree(reports, ignore_errors=True)  # stale reports must never count as evidence
        proc = await asyncio.create_subprocess_exec(
            mvn, "-B", "-q", "--no-transfer-progress", "test", cwd=project,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)
        try:
            out, _ = await asyncio.wait_for(proc.communicate(), timeout=self.args.get("timeout_seconds", 900))
        except asyncio.TimeoutError:
            proc.kill()
            return self.result(False, "mvn test timed out")
        log = out.decode(errors="replace")

        if not list(reports.glob("TEST-*.xml")):
            return self.result(False, "the tests did not compile or run, so nothing was reproduced\n"
                               + _failure_excerpt(log))
        written = {Path(p).as_posix() for p in ctx.artifact.result.files_written}
        failed = failing_tests(reports)
        if proc.returncode == 0 or not failed:
            return self.result(False, "the bug was not reproduced: every test passes, including the new ones. "
                                      "A regression test must fail on the current code.")
        outside = sorted({f"{c}.{t}" for c, t, _ in failed if source_file(c, project_rel) not in written})
        if outside:
            return self.result(False, f"tests this stage did not write fail too, so the failure is not a clean "
                                      f"reproduction: {outside}")
        detail = "; ".join(f"{c.rsplit('.', 1)[-1]}.{t}: {m}" for c, t, m in failed)
        return self.result(True, f"reproduced: {len(failed)} new test(s) fail on the current code, every other "
                                 f"test passes. {detail}")
