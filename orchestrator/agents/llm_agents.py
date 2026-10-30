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
from typing import Any

from pydantic import BaseModel, ValidationError

from ..engine.models import AgentResult, Decision
from ..llm.client import DEFAULT_MODEL, LLMClient, LLMRequest
from ..llm.schema import strict_schema
from .base import Agent, AgentContext, AgentRegistry, FatalAgentError
from .outputs import AnalystOutput, CodeOutput, TestPlanOutput

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

    def __init__(self, llm: LLMClient, model: str = DEFAULT_MODEL) -> None:
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


class AnalystAgent(LLMAgent):
    name = "analyst"
    prompts = ("analyst",)
    output_model = AnalystOutput
    effort = "high"
    max_tokens = 32000

    def task(self, ctx):
        return [_tag("requirement", ctx.requirement)]

    def to_result(self, ctx, out: AnalystOutput):
        decisions = [
            Decision(topic=a.question, choice=a.resolution, rationale=a.rationale, source="assumption")
            for a in out.ambiguities if a.resolution
        ]
        outputs = out.model_dump(exclude={"summary"})
        return AgentResult(summary=out.summary, outputs=outputs, decisions=decisions)


class TestPlannerAgent(LLMAgent):
    name = "test_planner"
    prompts = ("test_planner",)
    output_model = TestPlanOutput
    effort = "medium"
    max_tokens = 32000

    def task(self, ctx):
        return [self.spec_section(ctx)]

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
        return [self.spec_section(ctx), self.files_section(ctx), self.scope_section(ctx)]

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


def llm_agents(llm: LLMClient, model: str = DEFAULT_MODEL) -> AgentRegistry:
    registry = AgentRegistry()
    for agent in (AnalystAgent, TestPlannerAgent, CoderAgent, TesterAgent):
        registry.register(agent.name, lambda a=agent: a(llm, model))
    return registry
