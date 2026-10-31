"""Session-served LLM backend, and per-agent routing between backends.

`SessionLLM` hands an agent's request to an interactive assistant session
(e.g. Claude Code) through files: it writes the exact prompt, context and
schema the API would receive, then waits for a response file. The response
then goes through the same schema validation, policy and gates as an API
response. Calls are recorded as served by the session, at zero API cost —
never disguised as API calls.
"""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path

from ..agents.base import FatalAgentError
from ..fileio import write_atomic
from .client import LLMClient, LLMRequest, LLMResponse, Usage

SESSION_MODEL = "claude-code-session"


def request_paths(directory: Path, request: LLMRequest) -> tuple[Path, Path, Path]:
    stem = f"{request.agent}-{request.key()[:16]}"
    return (directory / f"{stem}.request.json", directory / f"{stem}.prompt.md",
            directory / f"{stem}.response.json")


class SessionLLM(LLMClient):
    def __init__(self, directory: Path, *, poll_seconds: float = 1.0, timeout_seconds: float = 3600) -> None:
        self.directory = directory
        self.poll_seconds = poll_seconds
        self.timeout_seconds = timeout_seconds

    async def complete(self, request: LLMRequest) -> LLMResponse:
        req_path, prompt_path, resp_path = request_paths(self.directory, request)
        if not req_path.exists():
            write_atomic(req_path, json.dumps(request.model_dump(by_alias=True), indent=2))
            write_atomic(prompt_path, _readable(request, resp_path))
            print(f"[session] {request.agent}: awaiting response -> {resp_path}", flush=True)

        started = time.monotonic()
        while not resp_path.exists():
            if time.monotonic() - started > self.timeout_seconds:
                raise FatalAgentError(f"no session response for {request.agent} within {self.timeout_seconds:.0f}s")
            await asyncio.sleep(self.poll_seconds)
        try:
            data = json.loads(resp_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"session response is not valid JSON: {exc}") from exc
        return LLMResponse(
            data=data, model=SESSION_MODEL, stop_reason="end_turn", usage=Usage(),
            duration_ms=int((time.monotonic() - started) * 1000), source="session", provider="session",
            cost_usd=0.0,
        )


class RoutedLLM(LLMClient):
    """Sends each agent's requests to its configured backend."""

    def __init__(self, routes: dict[str, LLMClient], default: LLMClient | None) -> None:
        self.routes = routes
        self.default = default

    async def complete(self, request: LLMRequest) -> LLMResponse:
        backend = self.routes.get(request.agent, self.default)
        if backend is None:
            raise FatalAgentError(f"no LLM backend configured for agent '{request.agent}'")
        return await backend.complete(request)


def _readable(request: LLMRequest, resp_path: Path) -> str:
    return "\n\n".join([
        f"# Session request: {request.agent}",
        f"Write the response as JSON matching the schema to:\n`{resp_path}`\n"
        f"(or use `orch respond {resp_path.with_name(resp_path.name.replace('.response.json', '.request.json'))} ...`)",
        "## System prompt", request.system,
        "## Task", request.user,
        "## Output schema", "```json\n" + json.dumps(request.schema_, indent=2) + "\n```",
    ])
