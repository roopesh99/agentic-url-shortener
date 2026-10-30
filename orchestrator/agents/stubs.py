"""Deterministic stub agents for the walking skeleton.

They honour the same contract as the LLM-backed agents (structured
`AgentResult`, writes only through the scoped `AgentContext`), so the engine,
gates and approvals can be exercised end to end without an API key.
"""

from __future__ import annotations

import re
from pathlib import Path

from ..engine.models import AgentResult, Decision
from .base import Agent, AgentContext, AgentRegistry

TEMPLATES = Path(__file__).parent / "templates" / "skeleton"

# Default resolutions the analyst may apply as explicit, reviewable assumptions.
DEFAULT_ASSUMPTIONS: list[tuple[str, str, str]] = [
    (r"length|alphabet", "Base62 alphabet, 7 characters (~3.5e12 codes)", "short, URL-safe, low collision odds"),
    (r"301|302|redirect status", "302 Found", "keeps links expirable/deletable; 301 is cached by browsers"),
    (r"alias.*taken|taken.*alias", "409 Conflict", "never silently reassign or overwrite a user's alias"),
    (r"rate.?limit", "20 creates/min per client IP", "conservative default; configurable"),
]


def _section_text(markdown: str, heading: str) -> str:
    match = re.search(rf"^##\s+{re.escape(heading)}.*?$(.*?)(?=^##\s|\Z)", markdown, re.M | re.S | re.I)
    return match.group(1).strip() if match else ""


def _section(markdown: str, heading: str) -> list[str]:
    """Bullet items under a `## heading`."""
    lines = _section_text(markdown, heading).splitlines()
    return [l.strip()[2:].strip() for l in lines if l.strip().startswith("- ")]


def _ids(items: list[str]) -> list[dict[str, str]]:
    out = []
    for item in items:
        m = re.match(r"(\w+\d+)\s+(.*)", item)
        out.append({"id": m.group(1), "text": m.group(2)} if m else {"id": "", "text": item})
    return out


class StubAnalyst(Agent):
    """Normalizes the requirement into a structured spec and surfaces ambiguities."""

    name = "analyst"

    async def run(self, ctx: AgentContext) -> AgentResult:
        goal = " ".join(_section_text(ctx.requirement, "Goal").split())
        functional = _ids(_section(ctx.requirement, "Functional requirements"))
        non_functional = _ids(_section(ctx.requirement, "Non-functional requirements"))
        ambiguities, decisions = [], []
        for question in _section(ctx.requirement, "Known open points"):
            resolution = next(
                ((choice, why) for pattern, choice, why in DEFAULT_ASSUMPTIONS if re.search(pattern, question, re.I)),
                None,
            )
            ambiguities.append(
                {"question": question, "resolution": resolution[0] if resolution else None,
                 "source": "assumption" if resolution else "unresolved"}
            )
            if resolution:
                decisions.append(Decision(topic=question, choice=resolution[0], rationale=resolution[1],
                                          source="assumption"))
        return AgentResult(
            summary=f"{len(functional)} functional, {len(non_functional)} non-functional requirements; "
                    f"{len(ambiguities)} ambiguities ({sum(1 for a in ambiguities if a['resolution'])} resolved)",
            outputs={
                "goal": goal,
                "functional": functional,
                "non_functional": non_functional,
                "ambiguities": ambiguities,
            },
            decisions=decisions,
        )


class StubTestPlanner(Agent):
    """Derives test cases from the normalized spec, in parallel with implementation."""

    name = "test_planner"
    SKELETON_SCOPE = {"FR1", "FR3", "NFR2"}

    async def run(self, ctx: AgentContext) -> AgentResult:
        spec = ctx.inputs["requirements"].result.outputs
        reqs = [r for r in spec["functional"] + spec["non_functional"] if r["id"] in self.SKELETON_SCOPE]
        cases = [{"id": f"TC-{r['id']}-01", "covers": r["id"], "check": r["text"]} for r in reqs]
        lines = ["# Test plan (skeleton scope)", ""] + [f"- **{c['id']}** ({c['covers']}): {c['check']}" for c in cases]
        ctx.write_file("docs/test-plan.md", "\n".join(lines) + "\n")
        return AgentResult(
            summary=f"{len(cases)} test cases for skeleton scope {sorted(self.SKELETON_SCOPE)}",
            outputs={"test_cases": cases},
            decisions=[Decision(topic="skeleton scope", choice=", ".join(sorted(self.SKELETON_SCOPE)),
                                rationale="walking skeleton proves the pipeline; full scope comes with LLM agents")],
        )


class _TemplateAgent(Agent):
    """Copies a slice of the skeleton template into the workspace (through the scope check)."""

    subtree: str = ""

    async def run(self, ctx: AgentContext) -> AgentResult:
        written = []
        for src in sorted(TEMPLATES.rglob("*")):
            rel = src.relative_to(TEMPLATES).as_posix()
            if src.is_file() and self.include(rel):
                ctx.write_file(rel, src.read_text(encoding="utf-8"))
                written.append(rel)
        return AgentResult(summary=f"{self.name}: wrote {len(written)} file(s)", outputs={"files": written})

    def include(self, rel: str) -> bool:
        raise NotImplementedError


class StubCoder(_TemplateAgent):
    name = "coder"

    def include(self, rel: str) -> bool:
        return rel == "url-shortener/pom.xml" or rel.startswith("url-shortener/src/main/")


class StubTester(_TemplateAgent):
    name = "tester"

    def include(self, rel: str) -> bool:
        return rel.startswith("url-shortener/src/test/")


def stub_agents() -> AgentRegistry:
    registry = AgentRegistry()
    for agent in (StubAnalyst, StubTestPlanner, StubCoder, StubTester):
        registry.register(agent.name, agent)
    return registry
