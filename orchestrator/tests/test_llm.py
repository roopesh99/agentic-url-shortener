"""LLM layer without the network: request shape, failure handling, cassettes, schemas."""

import json
from types import SimpleNamespace

import anthropic
import httpx2
import pytest

from orchestrator.agents.base import FatalAgentError
from orchestrator.agents.outputs import AnalystOutput, CodeOutput
from orchestrator.llm.client import AnthropicLLM, LLMRequest, LLMResponse, LLMTruncated, Usage
from orchestrator.llm.replay import CassetteLLM, Mode
from orchestrator.llm.schema import strict_schema


def _request(**overrides) -> LLMRequest:
    fields = {"agent": "coder", "system": "sys", "user": "task", "schema": {"type": "object"}, **overrides}
    return LLMRequest(**fields)


class _Stream:
    def __init__(self, message, exc=None):
        self.message, self.exc = message, exc

    async def __aenter__(self):
        if self.exc:
            raise self.exc
        return self

    async def __aexit__(self, *a):
        return False

    async def get_final_message(self):
        return self.message


class FakeSDK:
    """Stands in for AsyncAnthropic: records kwargs, returns a canned message."""

    def __init__(self, message=None, exc=None):
        self.calls: list[dict] = []
        sdk = self

        class Messages:
            def stream(self, **kwargs):
                sdk.calls.append(kwargs)
                return _Stream(message, exc)

        self.beta = SimpleNamespace(messages=Messages())


def _message(text='{"ok": true}', stop_reason="end_turn", stop_details=None, model="claude-opus-5-5"):
    return SimpleNamespace(
        content=[SimpleNamespace(type="thinking", thinking=""), SimpleNamespace(type="text", text=text)],
        stop_reason=stop_reason,
        stop_details=stop_details,
        model=model,
        usage=SimpleNamespace(input_tokens=1000, output_tokens=500,
                              cache_read_input_tokens=200, cache_creation_input_tokens=None),
        _request_id="req_123",
    )


async def test_request_shape_structured_output_effort_caching_and_fallback():
    sdk = FakeSDK(_message())
    resp = await AnthropicLLM(sdk).complete(_request(effort="medium"))

    [kw] = sdk.calls
    assert kw["model"] == "claude-opus-5-5"
    assert kw["output_config"] == {"effort": "medium", "format": {"type": "json_schema", "schema": {"type": "object"}}}
    assert kw["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert kw["fallbacks"] == "default" and kw["betas"] == ["server-side-fallback-2026-07-01"]
    assert "thinking" not in kw and "temperature" not in kw
    assert resp.data == {"ok": True} and resp.request_id == "req_123"
    assert resp.usage.cache_creation_input_tokens == 0  # None normalized


async def test_fallback_can_be_disabled():
    sdk = FakeSDK(_message())
    await AnthropicLLM(sdk, refusal_fallback=False).complete(_request())
    assert "fallbacks" not in sdk.calls[0] and "betas" not in sdk.calls[0]


async def test_refusal_is_fatal():
    sdk = FakeSDK(_message(text="", stop_reason="refusal", stop_details=SimpleNamespace(category="cyber")))
    with pytest.raises(FatalAgentError, match="cyber"):
        await AnthropicLLM(sdk).complete(_request())


async def test_truncation_is_retryable_not_fatal():
    with pytest.raises(LLMTruncated):
        await AnthropicLLM(FakeSDK(_message(stop_reason="max_tokens"))).complete(_request())


async def test_auth_error_is_fatal():
    err = anthropic.AuthenticationError(
        "invalid x-api-key", response=httpx2.Response(401, request=httpx2.Request("POST", "https://api")), body=None
    )
    with pytest.raises(FatalAgentError, match="rejected"):
        await AnthropicLLM(FakeSDK(exc=err)).complete(_request())


def test_cost_accounting():
    usage = Usage(input_tokens=1_000_000, output_tokens=100_000, cache_read_input_tokens=1_000_000)
    assert usage.cost_usd("claude-opus-5-5") == pytest.approx(4.00 + 2.00 + 0.20)


# --- cassettes ---------------------------------------------------------------------------

class CountingLLM:
    def __init__(self):
        self.calls = 0

    async def complete(self, request):
        self.calls += 1
        return LLMResponse(data={"n": self.calls}, model=request.model, stop_reason="end_turn", usage=Usage())


async def test_record_then_replay_offline(tmp_path):
    live = CountingLLM()
    recorded = await CassetteLLM(tmp_path, Mode.RECORD, live).complete(_request())
    replayed = await CassetteLLM(tmp_path, Mode.REPLAY).complete(_request())
    assert live.calls == 1
    assert replayed.data == recorded.data and replayed.source == "cassette"
    saved = json.loads(next(tmp_path.glob("coder-*.json")).read_text())
    assert saved["request"]["user"] == "task", "the prompt behind every output is reviewable"


async def test_replay_miss_is_fatal_when_inputs_change(tmp_path):
    await CassetteLLM(tmp_path, Mode.RECORD, CountingLLM()).complete(_request())
    with pytest.raises(FatalAgentError, match="no cassette"):
        await CassetteLLM(tmp_path, Mode.REPLAY).complete(_request(user="different task"))


def test_request_key_covers_every_input():
    base = _request().key()
    assert _request(effort="low").key() != base
    assert _request(model="claude-sonnet-5-5").key() != base
    assert _request(schema={"type": "array"}).key() != base


# --- schemas -----------------------------------------------------------------------------

@pytest.mark.parametrize("model", [AnalystOutput, CodeOutput])
def test_strict_schema_is_api_compatible(model):
    schema = strict_schema(model)
    text = json.dumps(schema)
    assert "$ref" not in text and "$defs" not in text and '"title"' not in text

    def check(node):
        if isinstance(node, dict):
            if node.get("type") == "object":
                assert node["additionalProperties"] is False
                assert set(node["required"]) == set(node["properties"])
            for v in node.values():
                check(v)
        elif isinstance(node, list):
            for v in node:
                check(v)

    check(schema)
