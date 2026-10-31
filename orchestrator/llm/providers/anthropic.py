"""Claude via the official Anthropic SDK (optional dependency: `pip install -e '.[anthropic]'`)."""

from __future__ import annotations

import json
import time
from typing import Any

import anthropic

from ...agents.base import FatalAgentError
from ..client import LLMClient, LLMRequest, LLMResponse, LLMTruncated, Pricing, Usage

DEFAULT_MODEL = "claude-opus-5-5"

PRICING: dict[str, Pricing] = {
    "claude-opus-5-5": Pricing(input=4.00, output=20.00, cached_input=0.20, cache_write=5.00),
    "claude-sonnet-5-5": Pricing(input=2.00, output=10.00, cached_input=0.20, cache_write=2.50),
    "claude-haiku-5-5": Pricing(input=0.10, output=0.50, cached_input=0.01, cache_write=0.125),
}


class AnthropicLLM(LLMClient):
    """Streaming (long code outputs), structured output, cached system prompt,
    explicit effort, and server-side refusal fallback."""

    FALLBACK_BETA = "server-side-fallback-2026-07-01"

    def __init__(self, client: anthropic.AsyncAnthropic | None = None, *, refusal_fallback: bool = True,
                 pricing: dict[str, Pricing] | None = None) -> None:
        self.client = client or anthropic.AsyncAnthropic()  # credentials from env / `ant auth login`
        self.refusal_fallback = refusal_fallback
        self.pricing = {**PRICING, **(pricing or {})}

    async def complete(self, request: LLMRequest) -> LLMResponse:
        kwargs: dict[str, Any] = dict(
            model=request.model,
            max_tokens=request.max_tokens,
            system=[{"type": "text", "text": request.system, "cache_control": {"type": "ephemeral"}}],
            messages=[{"role": "user", "content": request.user}],
            output_config={
                "effort": request.effort,
                "format": {"type": "json_schema", "schema": request.schema_},
            },
        )
        if self.refusal_fallback:
            kwargs.update(betas=[self.FALLBACK_BETA], fallbacks="default")

        started = time.monotonic()
        try:
            async with self.client.beta.messages.stream(**kwargs) as stream:
                message = await stream.get_final_message()
        except (anthropic.AuthenticationError, anthropic.PermissionDeniedError,
                anthropic.NotFoundError, anthropic.BadRequestError) as exc:
            raise FatalAgentError(f"Claude API rejected the request: {exc}") from exc
        # RateLimitError / 5xx / connection errors were already retried by the SDK;
        # if they still surface, they propagate as ordinary (retryable) agent errors.

        if message.stop_reason == "refusal":
            category = getattr(message.stop_details, "category", None) if message.stop_details else None
            raise FatalAgentError(f"model declined the request (category: {category})")
        if message.stop_reason == "max_tokens":
            raise LLMTruncated(f"output hit max_tokens={request.max_tokens}; produce a smaller change")

        text = "".join(b.text for b in message.content if b.type == "text")
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"response was not valid JSON: {exc}") from exc

        u = message.usage
        usage = Usage(
            input_tokens=u.input_tokens or 0,
            output_tokens=u.output_tokens or 0,
            cache_read_input_tokens=u.cache_read_input_tokens or 0,
            cache_creation_input_tokens=u.cache_creation_input_tokens or 0,
        )
        pricing = self.pricing.get(message.model)
        return LLMResponse(
            data=data,
            model=message.model,
            stop_reason=message.stop_reason or "",
            usage=usage,
            cost_usd=pricing.cost(usage) if pricing else None,
            request_id=getattr(message, "_request_id", None),
            duration_ms=int((time.monotonic() - started) * 1000),
            provider="anthropic",
        )
