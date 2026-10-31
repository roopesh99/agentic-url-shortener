"""OpenAI adapter (no network) and the provider registry / backend configuration."""

from pathlib import Path
from types import SimpleNamespace

import httpx2
import openai
import pytest

from orchestrator.agents.base import FatalAgentError
from orchestrator.agents.llm_agents import LLM_AGENT_NAMES
from orchestrator.llm.client import LLMClient, LLMRequest, LLMResponse, LLMTruncated, Pricing, Usage
from orchestrator.llm.factory import (BackendSpec, ConfigError, LLMConfig, build_llm, describe, load_config,
                                      model_for, register_provider)
from orchestrator.llm.providers.openai import OpenAILLM
from orchestrator.llm.session import SessionLLM

ROOT = Path(__file__).resolve().parents[2]


def _request(**overrides):
    fields = {"agent": "analyst", "model": "gpt-test", "system": "sys", "user": "task",
              "schema": {"type": "object"}, "effort": "high", **overrides}
    return LLMRequest(**fields)


class FakeOpenAI:
    def __init__(self, response=None, exc=None):
        self.calls = []
        fake = self

        class Responses:
            async def create(self, **kwargs):
                fake.calls.append(kwargs)
                if exc:
                    raise exc
                return response

        self.responses = Responses()


def _response(text='{"ok": true}', status="completed", reason=None, output=None, cached=300):
    return SimpleNamespace(
        status=status,
        incomplete_details=SimpleNamespace(reason=reason) if reason else None,
        output=output or [SimpleNamespace(type="message", content=[SimpleNamespace(type="output_text", text=text)])],
        output_text=text,
        model="gpt-test-2026",
        usage=SimpleNamespace(input_tokens=1000, output_tokens=400,
                              input_tokens_details=SimpleNamespace(cached_tokens=cached)),
        _request_id="req_oa_1",
    )


# --- OpenAI adapter ----------------------------------------------------------------------

async def test_openai_request_uses_strict_structured_output_and_no_retention():
    fake = FakeOpenAI(_response())
    resp = await OpenAILLM(fake).complete(_request())
    [kw] = fake.calls
    assert kw["model"] == "gpt-test" and kw["instructions"] == "sys" and kw["input"] == "task"
    assert kw["text"]["format"] == {"type": "json_schema", "name": "analyst_output",
                                    "schema": {"type": "object"}, "strict": True}
    assert kw["store"] is False and kw["max_output_tokens"] == 64000
    assert "reasoning" not in kw, "effort is only sent to reasoning models"
    assert resp.data == {"ok": True} and resp.provider == "openai" and resp.request_id == "req_oa_1"


async def test_reasoning_effort_is_opt_in():
    fake = FakeOpenAI(_response())
    await OpenAILLM(fake, reasoning=True).complete(_request(effort="medium"))
    assert fake.calls[0]["reasoning"] == {"effort": "medium"}


async def test_cached_tokens_are_normalized_and_priced():
    pricing = Pricing(input=1.0, output=4.0, cached_input=0.25)
    resp = await OpenAILLM(FakeOpenAI(_response()), pricing=pricing).complete(_request())
    assert resp.usage == Usage(input_tokens=700, output_tokens=400, cache_read_input_tokens=300)
    assert resp.cost_usd == pytest.approx((700 * 1.0 + 400 * 4.0 + 300 * 0.25) / 1e6)


async def test_unpriced_backend_reports_unknown_cost():
    resp = await OpenAILLM(FakeOpenAI(_response())).complete(_request())
    assert resp.cost_usd is None and resp.telemetry(_request())["priced"] is False


async def test_truncation_is_retryable():
    with pytest.raises(LLMTruncated):
        await OpenAILLM(FakeOpenAI(_response(status="incomplete", reason="max_output_tokens"))).complete(_request())


async def test_content_filter_and_refusal_are_fatal():
    with pytest.raises(FatalAgentError, match="content_filter"):
        await OpenAILLM(FakeOpenAI(_response(status="incomplete", reason="content_filter"))).complete(_request())
    refused = [SimpleNamespace(type="message", content=[SimpleNamespace(type="refusal", refusal="can't help")])]
    with pytest.raises(FatalAgentError, match="can't help"):
        await OpenAILLM(FakeOpenAI(_response(output=refused))).complete(_request())


async def test_auth_error_is_fatal():
    err = openai.AuthenticationError(
        "bad key", response=httpx2.Response(401, request=httpx2.Request("POST", "https://api")), body=None
    )
    with pytest.raises(FatalAgentError, match="rejected"):
        await OpenAILLM(FakeOpenAI(exc=err)).complete(_request())


# --- registry and configuration ----------------------------------------------------------

HYBRID = LLMConfig(
    default=BackendSpec(provider="openai", model="gpt-test", pricing=Pricing(input=1, output=4)),
    agents={"coder": BackendSpec(provider="session"), "tester": BackendSpec(provider="session")},
)


def test_hybrid_config_routes_agents_to_backends(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    routed = build_llm(HYBRID, LLM_AGENT_NAMES, session_dir=tmp_path)
    assert isinstance(routed.routes["analyst"], OpenAILLM)
    assert routed.routes["analyst"] is routed.routes["test_planner"], "one client per distinct backend"
    assert isinstance(routed.routes["coder"], SessionLLM)
    assert describe(HYBRID, ["analyst", "coder"]) == "analyst=openai/gpt-test, coder=session/claude-code-session"


def test_openai_requires_an_explicit_model():
    config = LLMConfig(default=BackendSpec(provider="openai"))
    with pytest.raises(ConfigError, match="explicit model"):
        model_for(config, "analyst")
    assert model_for(LLMConfig(default=BackendSpec(provider="anthropic")), "analyst") == "claude-opus-5-5"


def test_unknown_provider_is_rejected():
    with pytest.raises(ConfigError, match="unknown provider 'llama'"):
        model_for(LLMConfig(default=BackendSpec(provider="llama", model="x")), "analyst")


def test_budget_requires_pricing_for_api_backends(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    unpriced = LLMConfig(default=BackendSpec(provider="openai", model="gpt-test"),
                         agents={"coder": BackendSpec(provider="session")})
    with pytest.raises(ConfigError, match="needs pricing"):
        build_llm(unpriced, LLM_AGENT_NAMES, session_dir=tmp_path, require_pricing=True)
    build_llm(HYBRID, LLM_AGENT_NAMES, session_dir=tmp_path, require_pricing=True)  # priced: fine


def test_config_file_interpolates_environment(tmp_path, monkeypatch):
    path = tmp_path / "llm.yaml"
    path.write_text('default: {provider: openai, model: "${OPENAI_MODEL}"}\n')
    monkeypatch.delenv("OPENAI_MODEL", raising=False)
    with pytest.raises(ConfigError, match="OPENAI_MODEL is not set"):
        load_config(path)
    monkeypatch.setenv("OPENAI_MODEL", "gpt-from-env")
    assert load_config(path).default.model == "gpt-from-env"


def test_shipped_example_configs_are_valid(monkeypatch):
    monkeypatch.setenv("OPENAI_MODEL", "gpt-test")
    for path in sorted((ROOT / "config").glob("llm.*.yaml")):
        config = load_config(path)
        for agent in LLM_AGENT_NAMES:
            model_for(config, agent)


async def test_new_provider_plugs_in_without_touching_agents(tmp_path):
    class EchoLLM(LLMClient):
        async def complete(self, request):
            return LLMResponse(data={"echo": request.agent}, model="echo-1", stop_reason="end_turn",
                               usage=Usage(), cost_usd=0.0, provider="echo")

    register_provider("echo", lambda spec, ctx: EchoLLM(), default_model="echo-1")
    routed = build_llm(LLMConfig(default=BackendSpec(provider="echo")), ["analyst"], session_dir=tmp_path)
    assert (await routed.complete(_request(model="echo-1"))).data == {"echo": "analyst"}
