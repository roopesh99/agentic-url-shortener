"""Provider-neutral LLM contract.

An agent turn is one structured-output request: a stable system prompt, one
user message carrying the stage's context, and a JSON schema the response must
satisfy. The orchestrator owns the loop (retries, gates, policy); the model
never drives control flow. Providers (`llm/providers/`) implement `LLMClient`
and normalize their responses into `LLMResponse`.
"""

from __future__ import annotations

import hashlib
import json
from abc import ABC, abstractmethod
from typing import Any

from pydantic import BaseModel, Field


class LLMRequest(BaseModel):
    agent: str
    model: str
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
    """Normalized across providers: `input_tokens` excludes cache reads."""

    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_input_tokens: int = 0
    cache_creation_input_tokens: int = 0


class Pricing(BaseModel):
    """USD per million tokens."""

    input: float
    output: float
    cached_input: float = 0.0
    cache_write: float = 0.0

    def cost(self, usage: Usage) -> float:
        return round(
            (usage.input_tokens * self.input + usage.output_tokens * self.output
             + usage.cache_read_input_tokens * self.cached_input
             + usage.cache_creation_input_tokens * self.cache_write) / 1e6,
            6,
        )


class LLMResponse(BaseModel):
    data: dict[str, Any]
    model: str                       # the model that actually served it (may be a fallback)
    stop_reason: str
    usage: Usage
    cost_usd: float | None = None    # None: the backend has no pricing configured
    request_id: str | None = None
    duration_ms: int = 0
    source: str = "live"             # live | cassette | session
    provider: str = ""

    def telemetry(self, request: LLMRequest) -> dict[str, Any]:
        # Only live calls spend money now; a replayed cassette keeps its recorded cost for reference.
        spent = self.cost_usd or 0.0
        return {
            "agent": request.agent,
            "request_key": request.key(),
            "provider": self.provider,
            "requested_model": request.model,
            "served_model": self.model,
            "effort": request.effort,
            "stop_reason": self.stop_reason,
            "source": self.source,
            "request_id": self.request_id,
            "duration_ms": self.duration_ms,
            **self.usage.model_dump(),
            "cost_usd": spent if self.source == "live" else 0.0,
            "recorded_cost_usd": spent if self.source == "cassette" else None,
            "priced": self.cost_usd is not None,
        }


class LLMTruncated(RuntimeError):
    """Hit the output-token limit: retryable, with feedback asking for a smaller output."""


class LLMClient(ABC):
    @abstractmethod
    async def complete(self, request: LLMRequest) -> LLMResponse: ...
