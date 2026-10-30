"""Workflow loading and dependency-graph validation."""

from __future__ import annotations

from graphlib import CycleError, TopologicalSorter
from pathlib import Path

import yaml

from .models import WorkflowSpec


class WorkflowError(ValueError):
    pass


def load_workflow(path: Path) -> WorkflowSpec:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    workflow = WorkflowSpec.model_validate(data)
    validate(workflow)
    return workflow


def validate(workflow: WorkflowSpec) -> None:
    ids = [s.id for s in workflow.stages]
    dupes = {i for i in ids if ids.count(i) > 1}
    if dupes:
        raise WorkflowError(f"duplicate stage ids: {sorted(dupes)}")
    known = set(ids)
    for s in workflow.stages:
        missing = [d for d in s.needs if d not in known]
        if missing:
            raise WorkflowError(f"stage '{s.id}' needs unknown stage(s): {missing}")
    try:
        topological_order(workflow)
    except CycleError as exc:
        raise WorkflowError(f"dependency cycle: {' -> '.join(exc.args[1])}") from exc


def topological_order(workflow: WorkflowSpec) -> list[str]:
    graph = {s.id: set(s.needs) for s in workflow.stages}
    return list(TopologicalSorter(graph).static_order())


def upstream(workflow: WorkflowSpec, stage_id: str) -> set[str]:
    """All stages `stage_id` transitively depends on (excluding itself)."""
    out: set[str] = set()
    stack = list(workflow.stage(stage_id).needs)
    while stack:
        dep = stack.pop()
        if dep not in out:
            out.add(dep)
            stack.extend(workflow.stage(dep).needs)
    return out


def downstream(workflow: WorkflowSpec, stage_id: str) -> set[str]:
    """All stages that transitively depend on `stage_id` (excluding itself)."""
    children: dict[str, set[str]] = {s.id: set() for s in workflow.stages}
    for s in workflow.stages:
        for d in s.needs:
            children[d].add(s.id)
    out: set[str] = set()
    stack = [stage_id]
    while stack:
        for child in children[stack.pop()]:
            if child not in out:
                out.add(child)
                stack.append(child)
    return out
