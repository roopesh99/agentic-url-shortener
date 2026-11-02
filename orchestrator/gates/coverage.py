"""Coverage gate: how much of the code the tests execute, overall and in the files this change touched.
JaCoCo is run by its plugin coordinates, so the project's build file does not need to know about it."""

from __future__ import annotations

import asyncio
import shutil
from fnmatch import fnmatch
import xml.etree.ElementTree as ET
from pathlib import Path

from ..engine.models import GateResult
from .base import Gate, GateContext
from .builtin import _failure_excerpt

JACOCO = "org.jacoco:jacoco-maven-plugin:0.8.12"


def _ratio(element, kind: str) -> tuple[int, int] | None:
    counter = next((c for c in element.findall("counter") if c.get("type") == kind), None)
    if counter is None:
        return None
    covered, missed = int(counter.get("covered")), int(counter.get("missed"))
    return covered, covered + missed


def _pct(r: tuple[int, int] | None) -> float | None:
    return None if not r or not r[1] else 100.0 * r[0] / r[1]


def per_file(report: Path) -> tuple[dict, dict[str, dict]]:
    """Overall {line, branch} and per source file ('com/x/Foo.java' -> {line, branch})."""
    root = ET.parse(report).getroot()
    files = {}
    for package in root.findall("package"):
        for source in package.findall("sourcefile"):
            files[f"{package.get('name')}/{source.get('name')}"] = {
                "line": _ratio(source, "LINE"), "branch": _ratio(source, "BRANCH")}
    return {"line": _ratio(root, "LINE"), "branch": _ratio(root, "BRANCH")}, files


def changed_sources(ctx: GateContext, project: str) -> list[str]:
    """Production sources this stage and its inputs wrote, as JaCoCo names them ('com/x/Foo.java')."""
    prefix = f"{project}/src/main/java/"
    written = set(ctx.artifact.result.files_written if ctx.artifact else [])
    for artifact in ctx.inputs.values():
        written |= set(artifact.result.files_written)
    return sorted(p[len(prefix):] for p in written if p.startswith(prefix) and p.endswith(".java"))


class CoverageGate(Gate):
    """args: project; min_line (overall %, default 85); min_changed_line (each changed file %, default 80);
    exclude (globs of changed files not held to the per-file rule, e.g. a bootstrap main class)."""

    name = "coverage"

    async def check(self, ctx: GateContext) -> GateResult:
        mvn = shutil.which("mvn")
        if mvn is None:
            return self.result(False, "mvn not found on PATH")
        project_rel = self.args.get("project", ".")
        project = ctx.workspace / project_rel
        report = project / "target" / "site" / "jacoco" / "jacoco.xml"
        report.unlink(missing_ok=True)  # never judge a stale report
        proc = await asyncio.create_subprocess_exec(
            mvn, "-B", "-q", "--no-transfer-progress", f"{JACOCO}:prepare-agent", "test", f"{JACOCO}:report",
            cwd=project, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)
        try:
            out, _ = await asyncio.wait_for(proc.communicate(), timeout=self.args.get("timeout_seconds", 900))
        except asyncio.TimeoutError:
            proc.kill()
            return self.result(False, "coverage run timed out")
        if proc.returncode != 0 or not report.is_file():
            return self.result(False, "coverage could not be measured (tests failing?)\n"
                               + _failure_excerpt(out.decode(errors="replace")))

        overall, files = per_file(report)
        min_line, min_changed = self.args.get("min_line", 85), self.args.get("min_changed_line", 80)
        problems, details = [], []
        line = _pct(overall["line"])
        if line is None or line < min_line:
            problems.append(f"overall line coverage {line:.1f}% < {min_line}%")
        for source in changed_sources(ctx, project_rel):
            if any(fnmatch(source, g) for g in self.args.get("exclude", [])):
                continue
            counts = files.get(source)
            if counts is None or counts["line"] is None:
                continue  # no executable lines (an interface, a constants class)
            pct, branch = _pct(counts["line"]), _pct(counts["branch"])
            details.append(f"{source.rsplit('/', 1)[-1]} {pct:.1f}%" + (f" (branch {branch:.1f}%)" if branch is not None else ""))
            if pct < min_changed:
                problems.append(f"{source} line coverage {pct:.1f}% < {min_changed}%")
        summary = (f"overall line {line:.1f}%, branch {_pct(overall['branch']):.1f}%; changed files: "
                   + (", ".join(details) or "none"))
        if problems:
            return self.result(False, "; ".join(problems) + f". {summary}")
        return self.result(True, summary)
