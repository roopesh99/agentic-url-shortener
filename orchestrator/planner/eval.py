"""Workflow-selection eval: run the selector on requirements whose correct workflow is known."""

from __future__ import annotations

import tempfile
from pathlib import Path

import yaml

from .select import CODEBASE_MARKER, catalog, eligible, propose


async def evaluate(cases_file: Path, workflows_dir: Path, llm, model: str) -> list[dict]:
    cases = yaml.safe_load(cases_file.read_text(encoding="utf-8"))["cases"]
    candidates = catalog(workflows_dir)
    results = []
    with tempfile.TemporaryDirectory() as tmp:
        for state in ("new", "existing"):  # the only workspace fact the selector sees
            (Path(tmp) / state).mkdir()
        marker = Path(tmp) / "existing" / CODEBASE_MARKER
        marker.parent.mkdir(parents=True)
        marker.write_text("<project/>")
        for case in cases:
            workspace = Path(tmp) / case["codebase"]
            choices, _, facts = eligible(candidates, workspace)
            p = await propose(Path(case["requirement"]).read_text(encoding="utf-8"), workspace, choices, facts,
                              llm, model, feedback=[])
            results.append({"requirement": case["requirement"], "accept": case["accept"], "chosen": p["workflow"],
                            "confidence": p["confidence"], "source": p["source"], "runner_up": p["runner_up"],
                            "correct": p["workflow"] in case["accept"], "rationale": p["rationale"]})
    return results


def render(results: list[dict]) -> str:
    lines = ["| Requirement | Accept | Chosen | Confidence | By | Runner-up | |", "|---|---|---|---|---|---|---|"]
    for r in results:
        lines.append(f"| `{Path(r['requirement']).name}` | {', '.join(r['accept'])} | {r['chosen']} | "
                     f"{r['confidence']} | {r['source']} | {r['runner_up']} | {'✓' if r['correct'] else '✗'} |")
    correct = sum(r["correct"] for r in results)
    lines += ["", f"{correct} of {len(results)} correct"]
    return "\n".join(lines)
