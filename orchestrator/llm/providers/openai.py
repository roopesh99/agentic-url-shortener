"""OpenAI via the official SDK's Responses API (optional dependency: `pip install -e '.[openai]'`).

No model or price is built in: both change often and belong in configuration
(`config/llm.*.yaml`), not in code.
"""

from __future__ import annotations

import json
import re
import time
from typing import Any

import openai

from ...agents.base import FatalAgentError
from ..client import LLMClient, LLMRequest, LLMResponse, LLMTruncated, Pricing, Usage


class OpenAILLM(LLMClient):
    """Structured output (strict JSON schema), optional reasoning effort, and
    `store=False` so prompts and code are not retained for later retrieval."""

    def __init__(self, client: openai.AsyncOpenAI | None = None, *, pricing: Pricing | None = None,
                 reasoning: bool = False, store: bool = False) -> None:
        self.client = client or openai.AsyncOpenAI()  # OPENAI_API_KEY from the environment
        self.pricing = pricing
        self.reasoning = reasoning  # only reasoning models accept an effort setting
        self.store = store

    async def complete(self, request: LLMRequest) -> LLMResponse:
        kwargs: dict[str, Any] = dict(
            model=request.model,
            instructions=request.system,
            input=request.user,
            max_output_tokens=request.max_tokens,
            text={"format": {
                "type": "json_schema",
                "name": re.sub(r"[^A-Za-z0-9_-]", "_", f"{request.agent}_output"),
                "schema": request.schema_,
                "strict": True,
            }},
            store=self.store,
            prompt_cache_key=f"orch-{request.agent}",  # routes repeat prompts to the same cache
        )
        if self.reasoning:
            kwargs["reasoning"] = {"effort": request.effort}

        started = time.monotonic()
        try:
            response = await self.client.responses.create(**kwargs)
        except (openai.AuthenticationError, openai.PermissionDeniedError,
                openai.NotFoundError, openai.BadRequestError) as exc:
            raise FatalAgentError(f"OpenAI API rejected the request: {exc}") from exc
        # Rate limits / 5xx / connection errors were retried by the SDK; still failing => retryable agent error.

        if response.status == "incomplete":
            reason = getattr(response.incomplete_details, "reason", None)
            if reason == "max_output_tokens":
                raise LLMTruncated(f"output hit max_output_tokens={request.max_tokens}; produce a smaller change")
            raise FatalAgentError(f"response incomplete: {reason}")
        refusal = _refusal(response)
        if refusal is not None:
            raise FatalAgentError(f"model declined the request: {refusal}")

        try:
            data = json.loads(response.output_text)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"response was not valid JSON: {exc}") from exc

        u = response.usage
        cached = (u.input_tokens_details.cached_tokens or 0) if u and u.input_tokens_details else 0
        usage = Usage(
            input_tokens=(u.input_tokens - cached) if u else 0,  # OpenAI counts cached tokens inside input_tokens
            output_tokens=u.output_tokens if u else 0,
            cache_read_input_tokens=cached,
        )
        return LLMResponse(
            data=data,
            model=response.model,
            stop_reason=response.status or "",
            usage=usage,
            cost_usd=self.pricing.cost(usage) if self.pricing else None,
            request_id=getattr(response, "_request_id", None),
            duration_ms=int((time.monotonic() - started) * 1000),
            provider="openai",
        )


def _refusal(response) -> str | None:
    for item in response.output or []:
        for part in getattr(item, "content", None) or []:
            if getattr(part, "type", None) == "refusal":
                return part.refusal
    return None
