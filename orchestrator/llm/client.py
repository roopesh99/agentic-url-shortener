"""LLM contract and the Claude implementation.

An agent turn is one structured-output request: a stable system prompt, one
user message carrying the stage's context, and a JSON schema the response must
satisfy. The orchestrator owns the loop (retries, gates, policy); the model
never drives control flow.
"""

from __future__ import annotations

import hashlib
import json
import time
from abc import ABC, abstractmethod
from typing import Any

import anthropic
from pydantic import BaseModel, Field

from ..agents.base import FatalAgentError

DEFAULT_MODEL = "claude-opus-5-5"

# USD per million tokens: (input, output, cache read, cache write 5m)
PRICING: dict[str, tuple[float, float, float, float]] = {
    "claude-opus-5-5": (4.00, 20.00, 0.20, 5.00),
    "claude-sonnet-5-5": (2.00, 10.00, 0.20, 2.50),
    "claude-haiku-5-5": (0.10, 0.50, 0.01, 0.125),
}


class LLMRequest(BaseModel):
    agent: str
    model: str = DEFAULT_MODEL
    system: str
    user: str
    schema_: dict[str, Any] = Field(alias="schema")
    effort: str = "high"
    max_tokens: int = 64000

    model_config = {"populate_by_name": True}

    def key(self) -> str:
        """Content address of the request: identical inputs replay identical outputs."""
        body = self.model_dump(by_alias=True)
        return hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()


class Usage(BaseModel):
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_input_tokens: int = 0
    cache_creation_input_tokens: int = 0

    def cost_usd(self, model: str) -> float:
        p_in, p_out, p_read, p_write = PRICING.get(model, PRICING[DEFAULT_MODEL])
        return round(
            (self.input_tokens * p_in + self.output_tokens * p_out
             + self.cache_read_input_tokens * p_read + self.cache_creation_input_tokens * p_write) / 1e6,
            6,
        )


class LLMResponse(BaseModel):
    data: dict[str, Any]
    model: str                       # the model that actually served it (may be a fallback)
    stop_reason: str
    usage: Usage
    request_id: str | None = None
    duration_ms: int = 0
    source: str = "live"             # live | cassette

    def telemetry(self, request: LLMRequest) -> dict[str, Any]:
        return {
            "agent": request.agent,
            "request_key": request.key(),
            "requested_model": request.model,
            "served_model": self.model,
            "effort": request.effort,
            "stop_reason": self.stop_reason,
            "source": self.source,
            "request_id": self.request_id,
            "duration_ms": self.duration_ms,
            **self.usage.model_dump(),
            "cost_usd": self.usage.cost_usd(self.model),
        }


class LLMTruncated(RuntimeError):
    """Hit max_tokens: retryable, with feedback asking for a smaller output."""


class LLMClient(ABC):
    @abstractmethod
    async def complete(self, request: LLMRequest) -> LLMResponse: ...


class AnthropicLLM(LLMClient):
    """Claude via the official SDK: streaming (long code outputs), structured output,
    cached system prompt, explicit effort, and server-side refusal fallback."""

    FALLBACK_BETA = "server-side-fallback-2026-07-01"

    def __init__(self, client: anthropic.AsyncAnthropic | None = None, *, refusal_fallback: bool = True) -> None:
        self.client = client or anthropic.AsyncAnthropic()  # credentials from env / `ant auth login`
        self.refusal_fallback = refusal_fallback

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
        return LLMResponse(
            data=data,
            model=message.model,
            stop_reason=message.stop_reason or "",
            usage=Usage(
                input_tokens=u.input_tokens or 0,
                output_tokens=u.output_tokens or 0,
                cache_read_input_tokens=u.cache_read_input_tokens or 0,
                cache_creation_input_tokens=u.cache_creation_input_tokens or 0,
            ),
            request_id=getattr(message, "_request_id", None),
            duration_ms=int((time.monotonic() - started) * 1000),
        )
