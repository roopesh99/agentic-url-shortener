"""Structured outputs the LLM agents must return."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


class RequirementItem(BaseModel):
    id: str
    text: str


class Ambiguity(BaseModel):
    question: str
    resolution: str | None  # null when no safe default exists: a human must answer
    source: Literal["assumption", "unresolved"]
    rationale: str


class AnalystOutput(BaseModel):
    summary: str
    goal: str
    functional: list[RequirementItem]
    non_functional: list[RequirementItem]
    ambiguities: list[Ambiguity]
    acceptance_criteria: list[str]


class DecisionOut(BaseModel):
    topic: str
    choice: str
    rationale: str


class FileOut(BaseModel):
    path: str      # relative to the workspace
    content: str   # complete file content (no diffs, no placeholders)


class CodeOutput(BaseModel):
    summary: str
    files: list[FileOut]
    decisions: list[DecisionOut]


class ImpactedFile(BaseModel):
    path: str
    kind: Literal["modify", "create"]
    reason: str


class ApiChange(BaseModel):
    method: str
    path: str
    change: str    # request, response and status codes, or "unchanged" guarantees


class Risk(BaseModel):
    risk: str
    mitigation: str
    detection: str  # which test catches it if the mitigation fails


class ImpactOutput(BaseModel):
    summary: str
    impacted: list[ImpactedFile]
    api_changes: list[ApiChange]
    data_changes: list[str]
    data_flows: list[str]
    risks: list[Risk]
    test_strategy: list[str]
    decisions: list[DecisionOut]


class TestCase(BaseModel):
    id: str
    covers: str    # requirement id
    level: Literal["unit", "integration"]
    check: str


class TestPlanOutput(BaseModel):
    summary: str
    test_cases: list[TestCase]
    decisions: list[DecisionOut]
