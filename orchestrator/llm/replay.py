"""Record/replay cassettes for deterministic, offline, zero-cost runs.

A cassette is keyed by the full request content (model, prompt, schema,
effort). In `replay` mode a miss is fatal — CI and demos never silently fall
through to a paid live call. Cassettes store the request too, so the exact
prompt behind every recorded output is reviewable in the repo.
"""

from __future__ import annotations

import json
from enum import Enum
from pathlib import Path

from ..agents.base import FatalAgentError
from .client import LLMClient, LLMRequest, LLMResponse


class Mode(str, Enum):
    LIVE = "live"      # call the API, keep nothing
    RECORD = "record"  # call the API, save the exchange
    REPLAY = "replay"  # serve saved exchanges only


class CassetteLLM(LLMClient):
    def __init__(self, directory: Path, mode: Mode, inner: LLMClient | None = None) -> None:
        if mode is not Mode.REPLAY and inner is None:
            raise ValueError(f"{mode.value} mode needs a live client")
        self.directory = directory
        self.mode = mode
        self.inner = inner

    def _path(self, request: LLMRequest) -> Path:
        return self.directory / f"{request.agent}-{request.key()[:16]}.json"

    async def complete(self, request: LLMRequest) -> LLMResponse:
        path = self._path(request)
        if self.mode is Mode.REPLAY:
            if not path.exists():
                raise FatalAgentError(
                    f"no cassette for {request.agent} request {request.key()[:16]} in {self.directory} "
                    "(inputs changed since recording; re-record with --llm record)"
                )
            recorded = json.loads(path.read_text(encoding="utf-8"))
            return LLMResponse.model_validate({**recorded["response"], "source": "cassette"})

        response = await self.inner.complete(request)
        if self.mode is Mode.RECORD:
            self.directory.mkdir(parents=True, exist_ok=True)
            path.write_text(
                json.dumps(
                    {"request": request.model_dump(by_alias=True), "response": response.model_dump()},
                    indent=2, sort_keys=True,
                ),
                encoding="utf-8",
            )
        return response
