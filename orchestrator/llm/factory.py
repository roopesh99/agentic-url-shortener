"""Backend configuration and the provider registry.

Which backend serves which agent is configuration, not code:

    default: {provider: openai, model: "${OPENAI_MODEL}", options: {reasoning: true}}
    agents:
      coder:  {provider: session}
      tester: {provider: session}

A new provider is one `LLMClient` class plus one `register_provider` call;
agents, engine, policy and gates are unaffected. Provider SDKs are imported
only when a configured backend uses them, so each is an optional dependency.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any, Callable

import yaml
from pydantic import BaseModel, Field

from .client import LLMClient, Pricing
from .session import SESSION_MODEL, RoutedLLM, SessionLLM


class BackendSpec(BaseModel):
    provider: str
    model: str | None = None
    pricing: Pricing | None = None          # USD per 1M tokens; required for a cost budget
    options: dict[str, Any] = Field(default_factory=dict)


class LLMConfig(BaseModel):
    default: BackendSpec
    agents: dict[str, BackendSpec] = Field(default_factory=dict)

    def for_agent(self, agent: str) -> BackendSpec:
        return self.agents.get(agent, self.default)


class ConfigError(ValueError):
    pass


# provider name -> (factory, default model). The factory receives the spec and a build context.
_Factory = Callable[[BackendSpec, dict[str, Any]], LLMClient]
_PROVIDERS: dict[str, tuple[_Factory, str | None]] = {}


def register_provider(name: str, factory: _Factory, default_model: str | None = None) -> None:
    _PROVIDERS[name] = (factory, default_model)


def _anthropic(spec: BackendSpec, ctx: dict[str, Any]) -> LLMClient:
    from .providers.anthropic import AnthropicLLM
    pricing = {spec.model: spec.pricing} if spec.pricing and spec.model else None
    return AnthropicLLM(pricing=pricing, **spec.options)


def _openai(spec: BackendSpec, ctx: dict[str, Any]) -> LLMClient:
    from .providers.openai import OpenAILLM
    return OpenAILLM(pricing=spec.pricing, **spec.options)


def _session(spec: BackendSpec, ctx: dict[str, Any]) -> LLMClient:
    return SessionLLM(ctx["session_dir"], **spec.options)


register_provider("anthropic", _anthropic, default_model="claude-opus-5-5")
register_provider("openai", _openai, default_model=None)  # models change often: configure explicitly
register_provider("session", _session, default_model=SESSION_MODEL)


def load_config(path: Path) -> LLMConfig:
    """Parse first, then expand `${VAR}` inside string values only (never in comments or keys)."""

    def env(match: re.Match) -> str:
        name = match.group(1)
        if name not in os.environ:
            raise ConfigError(f"{path}: environment variable {name} is not set")
        return os.environ[name]

    def expand(node: Any) -> Any:
        if isinstance(node, str):
            return re.sub(r"\$\{(\w+)\}", env, node)
        if isinstance(node, dict):
            return {k: expand(v) for k, v in node.items()}
        if isinstance(node, list):
            return [expand(v) for v in node]
        return node

    return LLMConfig.model_validate(expand(yaml.safe_load(path.read_text(encoding="utf-8"))))


def model_for(config: LLMConfig, agent: str) -> str:
    spec = config.for_agent(agent)
    if spec.provider not in _PROVIDERS:
        raise ConfigError(f"agent '{agent}': unknown provider '{spec.provider}' (known: {sorted(_PROVIDERS)})")
    model = spec.model or _PROVIDERS[spec.provider][1]
    if not model:
        raise ConfigError(f"agent '{agent}': provider '{spec.provider}' needs an explicit model")
    return model


def build_llm(config: LLMConfig, agents: list[str], *, session_dir: Path,
              require_pricing: bool = False) -> RoutedLLM:
    """One client per distinct backend, routed per agent. Fails fast on bad config
    (unknown provider, missing model, missing credentials, unpriced backend under a budget)."""
    clients: dict[str, LLMClient] = {}
    routes: dict[str, LLMClient] = {}
    for agent in agents:
        spec = config.for_agent(agent)
        model_for(config, agent)
        if require_pricing and spec.provider != "session" and not _priced(spec):
            raise ConfigError(
                f"agent '{agent}': a cost budget needs pricing for {spec.provider}/{spec.model}; "
                "add `pricing: {input: ..., output: ...}` (USD per 1M tokens) to its backend"
            )
        key = spec.model_dump_json()
        if key not in clients:
            clients[key] = _PROVIDERS[spec.provider][0](spec, {"session_dir": session_dir})
        routes[agent] = clients[key]
    return RoutedLLM(routes, default=None)


def describe(config: LLMConfig, agents: list[str]) -> str:
    return ", ".join(f"{a}={config.for_agent(a).provider}/{model_for(config, a)}" for a in agents)


def _priced(spec: BackendSpec) -> bool:
    if spec.pricing:
        return True
    if spec.provider == "anthropic":
        from .providers.anthropic import PRICING
        return (spec.model or "claude-opus-5-5") in PRICING
    return False
