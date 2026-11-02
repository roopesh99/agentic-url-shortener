"""Claude-backed agents.

Each agent turn is one structured-output call. The agent assembles a
deterministic context message (so identical inputs replay identical cassettes),
validates the response against its Pydantic output model, and proposes files
through the scoped `AgentContext` — the same contract the stub agents honour.
"""

from __future__ import annotations

import json
from functools import cache
from pathlib import Path
from typing import Any, Callable

from pydantic import BaseModel, ValidationError

from ..engine.models import AgentResult, Decision
from ..llm.client import LLMClient, LLMRequest
from ..llm.schema import strict_schema
from .base import Agent, AgentContext, AgentRegistry, FatalAgentError
from .outputs import AnalystOutput, CodeOutput, DesignOutput, ImpactOutput, ReleaseOutput, TestPlanOutput

PROMPTS = Path(__file__).parent / "prompts"
MAX_CONTEXT_CHARS = 400_000  # ~100k tokens; refuse rather than silently truncate


@cache
def _prompt(*names: str) -> str:
    return "\n\n".join((PROMPTS / f"{n}.md").read_text(encoding="utf-8").strip() for n in names)


def _tag(name: str, body: str, **attrs: str) -> str:
    attr = "".join(f' {k}="{v}"' for k, v in attrs.items())
    return f"<{name}{attr}>\n{body.strip()}\n</{name}>"


def _canonical(obj: Any) -> str:
    return json.dumps(obj, indent=2, sort_keys=True)


class LLMAgent(Agent):
    prompts: tuple[str, ...] = ()
    output_model: type[BaseModel]
    effort: str = "high"
    max_tokens: int = 64000

    def __init__(self, llm: LLMClient, model: str) -> None:
        self.llm = llm
        self.model = model

    # -- subclasses ---------------------------------------------------------------

    def task(self, ctx: AgentContext) -> list[str]:
        """Context sections for the user message, most stable first."""
        raise NotImplementedError

    def to_result(self, ctx: AgentContext, out: Any) -> AgentResult:
        raise NotImplementedError

    # -- shared ---------------------------------------------------------------------

    async def run(self, ctx: AgentContext) -> AgentResult:
        sections = self.task(ctx)
        if ctx.feedback:
            sections.append(_tag(
                "previous_attempt_feedback",
                f"Attempt {ctx.attempt - 1} was not accepted. Fix the causes below.\n\n" + "\n\n".join(ctx.feedback),
            ))
        user = "\n\n".join(sections)
        if len(user) > MAX_CONTEXT_CHARS:
            raise FatalAgentError(
                f"context for '{ctx.stage.id}' is {len(user):,} chars (limit {MAX_CONTEXT_CHARS:,}); "
                "narrow the stage's read_scope"
            )

        request = LLMRequest(
            agent=self.name, model=self.model, system=_prompt(*self.prompts), user=user,
            schema=strict_schema(self.output_model), effort=self.effort, max_tokens=self.max_tokens,
        )
        response = await self.llm.complete(request)
        ctx.telemetry.append(response.telemetry(request))
        try:
            out = self.output_model.model_validate(response.data)
        except ValidationError as exc:
            raise RuntimeError(f"output did not match {self.output_model.__name__}: {exc}") from exc
        return self.to_result(ctx, out)

    @staticmethod
    def spec_section(ctx: AgentContext) -> str:
        spec = ctx.inputs["requirements"].result
        return _tag("approved_specification", _canonical(spec.outputs))

    @staticmethod
    def impact_section(ctx: AgentContext) -> list[str]:
        """The approved impact analysis, when the workflow has one (brownfield)."""
        impact = ctx.inputs.get("impact")
        return [_tag("approved_impact_analysis", _canonical(impact.result.outputs))] if impact else []

    @staticmethod
    def design_section(ctx: AgentContext) -> list[str]:
        """The approved API definition and design note, when the workflow has a design stage."""
        design = ctx.inputs.get("design")
        if not design:
            return []
        o = design.result.outputs
        return [_tag("approved_api_definition", o.get("openapi_yaml", "")),
                _tag("approved_design_notes", o.get("design_notes_markdown", ""))]

    @staticmethod
    def files_section(ctx: AgentContext, name: str = "existing_files") -> str:
        files = ctx.context_files()
        if not files:
            return _tag(name, "(none: this is a new codebase)")
        return _tag(name, "\n\n".join(_tag("file", body, path=path) for path, body in files.items()))

    @staticmethod
    def scope_section(ctx: AgentContext) -> str:
        return _tag("write_scope", "\n".join(f"- {g}" for g in ctx.stage.write_scope))

    @staticmethod
    def propose(ctx: AgentContext, out: CodeOutput) -> None:
        for f in out.files:
            ctx.write_file(f.path, f.content)


def _decisions(items) -> list[Decision]:
    return [Decision(topic=d.topic, choice=d.choice, rationale=d.rationale, source="agent") for d in items]


CLARIFICATION_NOTE = (
    "A human answered your earlier open questions. These answers are binding decisions. For each, "
    "keep the original question wording, set `resolution` to the answer, set `source` to \"assumption\" "
    "and start `rationale` with \"Decided by a human:\". Make the requirements and acceptance criteria "
    "consistent with every answer. Raise a new open question only if an answer itself leaves something "
    "genuinely undecided."
)


class AnalystAgent(LLMAgent):
    name = "analyst"
    prompts = ("analyst",)
    output_model = AnalystOutput
    effort = "high"
    max_tokens = 32000

    def task(self, ctx):
        sections = [_tag("requirement", ctx.requirement)]
        if ctx.clarifications:
            # Instructions live here, not in the system prompt: the first request stays
            # byte-identical (cacheable, replayable) and only re-runs carry the answers.
            sections.append(_tag("clarifications", CLARIFICATION_NOTE + "\n\n" + _canonical(ctx.clarifications)))
        return sections

    def to_result(self, ctx, out: AnalystOutput):
        human = {c["question"] for c in ctx.clarifications}
        decisions = [
            Decision(topic=a.question, choice=a.resolution, rationale=a.rationale, source="assumption")
            for a in out.ambiguities if a.resolution and a.question not in human
        ]  # human answers are recorded by the engine, verbatim, from the clarification itself
        outputs = out.model_dump(exclude={"summary"})
        return AgentResult(summary=out.summary, outputs=outputs, decisions=decisions)


DOWNSTREAM_NOTE = ("Where each later stage of this workflow may write. These locations are fixed: every file you "
                   "list as impacted must fall within one of them, and documentation, API definition and release "
                   "files must use exactly these locations.")


class ImpactAgent(LLMAgent):
    name = "impact_analyst"
    prompts = ("impact",)
    output_model = ImpactOutput
    effort = "high"
    max_tokens = 32000

    def task(self, ctx):
        sections = [self.spec_section(ctx), self.files_section(ctx)]
        if ctx.downstream_scopes:  # the workflow fixes where later stages write; plan within it
            sections.append(_tag("downstream_write_scopes", DOWNSTREAM_NOTE + "\n" + _canonical(ctx.downstream_scopes)))
        return sections

    def to_result(self, ctx, out: ImpactOutput):
        return AgentResult(summary=out.summary, outputs=out.model_dump(exclude={"summary", "decisions"}),
                           decisions=_decisions(out.decisions))


class ArchitectAgent(LLMAgent):
    name = "architect"
    prompts = ("architect",)
    output_model = DesignOutput
    effort = "high"
    max_tokens = 48000
    OPENAPI = "url-shortener/openapi.yaml"
    NOTES = "url-shortener/docs/design.md"

    def task(self, ctx):
        return [self.spec_section(ctx), *self.impact_section(ctx), self.files_section(ctx), self.scope_section(ctx)]

    def to_result(self, ctx, out: DesignOutput):
        ctx.write_file(self.OPENAPI, out.openapi_yaml.strip() + "\n")
        ctx.write_file(self.NOTES, out.design_notes_markdown.strip() + "\n")
        return AgentResult(summary=out.summary,
                           outputs={"openapi_yaml": out.openapi_yaml, "design_notes_markdown": out.design_notes_markdown},
                           decisions=_decisions(out.decisions))


class WriterAgent(LLMAgent):
    name = "writer"
    prompts = ("writer",)
    output_model = CodeOutput
    effort = "medium"

    def task(self, ctx):
        return [self.spec_section(ctx), *self.design_section(ctx), self.files_section(ctx), self.scope_section(ctx)]

    def to_result(self, ctx, out: CodeOutput):
        self.propose(ctx, out)
        return AgentResult(summary=out.summary, outputs={"files": [f.path for f in out.files]},
                           decisions=_decisions(out.decisions))


class ReleaseAgent(LLMAgent):
    name = "release"
    prompts = ("release",)
    output_model = ReleaseOutput
    effort = "high"
    max_tokens = 32000
    CHANGELOG = "url-shortener/CHANGELOG.md"
    REPORT_DIR = "url-shortener/docs/releases"

    def task(self, ctx):
        stages = {name: {"artifact": f"{a.name}@v{a.version}", "produced_by": a.produced_by,
                         "summary": a.result.summary,
                         "decisions": [d.model_dump() for d in a.result.decisions],
                         "files": a.result.files_written}
                  for name, a in ctx.inputs.items()}
        return [self.spec_section(ctx), _tag("accepted_stages", _canonical(stages)),
                self.files_section(ctx, "existing_release_files"), self.scope_section(ctx)]

    def to_result(self, ctx, out: ReleaseOutput):
        ctx.write_file(self.CHANGELOG, out.changelog_markdown.strip() + "\n")
        lines = [f"# Release {out.version}: readiness", "", out.summary, "", "## Checklist", "",
                 "| Item | Status | Evidence |", "|---|---|---|"]
        lines += [f"| {c.item} | {c.status} | {c.evidence.replace('|', '/')} |" for c in out.checklist]
        lines += ["", "## Residual risks", ""] + [f"- **{r.risk}**: {r.mitigation}" for r in out.risks]
        lines += ["", "## Rollback plan", "", out.rollback_plan]
        ctx.write_file(f"{self.REPORT_DIR}/{out.version}.md", "\n".join(lines) + "\n")
        return AgentResult(
            summary=out.summary,
            outputs={"version": out.version, "checklist": [c.model_dump() for c in out.checklist],
                     "risks": [r.model_dump() for r in out.risks], "rollback_plan": out.rollback_plan},
            decisions=_decisions(out.decisions))


class TestPlannerAgent(LLMAgent):
    name = "test_planner"
    prompts = ("test_planner",)
    output_model = TestPlanOutput
    effort = "medium"
    max_tokens = 32000

    def task(self, ctx):
        return [self.spec_section(ctx), *self.impact_section(ctx), *self.design_section(ctx)]

    def to_result(self, ctx, out: TestPlanOutput):
        lines = ["# Test plan", "", f"_{out.summary}_", "", "| Id | Covers | Level | Check |", "|---|---|---|---|"]
        lines += [f"| {c.id} | {c.covers} | {c.level} | {c.check.replace('|', '/')} |" for c in out.test_cases]
        ctx.write_file("docs/test-plan.md", "\n".join(lines) + "\n")
        return AgentResult(
            summary=out.summary,
            outputs={"test_cases": [c.model_dump() for c in out.test_cases]},
            decisions=_decisions(out.decisions),
        )


class CoderAgent(LLMAgent):
    name = "coder"
    prompts = ("coder", "engineering_standards")
    output_model = CodeOutput
    effort = "high"

    def task(self, ctx):
        return [self.spec_section(ctx), *self.impact_section(ctx), *self.design_section(ctx),
                self.files_section(ctx), self.scope_section(ctx)]

    def to_result(self, ctx, out: CodeOutput):
        self.propose(ctx, out)
        return AgentResult(summary=out.summary, outputs={"files": [f.path for f in out.files]},
                           decisions=_decisions(out.decisions))


class TesterAgent(LLMAgent):
    name = "tester"
    prompts = ("tester", "engineering_standards")
    output_model = CodeOutput
    effort = "high"

    def task(self, ctx):
        plan = ctx.inputs["test_plan"].result.outputs
        return [
            self.spec_section(ctx),
            *self.impact_section(ctx),
            *self.design_section(ctx),
            _tag("test_plan", _canonical(plan)),
            self.files_section(ctx, "implementation_and_existing_tests"),
            self.scope_section(ctx),
        ]

    def to_result(self, ctx, out: CodeOutput):
        self.propose(ctx, out)
        defects = [d for d in out.decisions if d.topic.lower() == "implementation defect"]
        return AgentResult(
            summary=out.summary,
            outputs={"files": [f.path for f in out.files], "implementation_defects": [d.choice for d in defects]},
            decisions=_decisions(out.decisions),
        )


AGENT_TYPES = (AnalystAgent, ImpactAgent, ArchitectAgent, TestPlannerAgent, CoderAgent, TesterAgent,
               WriterAgent, ReleaseAgent)
LLM_AGENT_NAMES = [a.name for a in AGENT_TYPES]


def llm_agents(llm: LLMClient, model: str | Callable[[str], str]) -> AgentRegistry:
    """`model`: one model for every agent, or a resolver from agent name to model."""
    resolve = model if callable(model) else (lambda _agent: model)
    registry = AgentRegistry()
    for agent in AGENT_TYPES:
        registry.register(agent.name, lambda a=agent: a(llm, resolve(a.name)))
    return registry
