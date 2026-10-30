"""Policy engine: evaluates every rule against a proposed change set.

The strictest action across all violations decides the outcome. Workflows
cannot opt out: policy runs on every stage that proposes changes, and a stage's
`approval: none` does not waive a policy-required approval.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import yaml

from ..engine.models import StageSpec
from ..workspace.changes import ChangeSet
from .models import TIER_FOR_ACTION, Action, PolicyDecision
from .rules import RULE_TYPES, Rule


class PolicyConfigError(ValueError):
    pass


class PolicyEngine:
    def __init__(self, rules: list[Rule], policy_sha: str = "none") -> None:
        self.rules = rules
        self.policy_sha = policy_sha

    @classmethod
    def load(cls, path: Path) -> "PolicyEngine":
        text = path.read_text(encoding="utf-8")
        config = yaml.safe_load(text) or {}
        rules = []
        for name, spec in (config.get("rules") or {}).items():
            spec = dict(spec or {})
            if not spec.pop("enabled", True):
                continue
            if name not in RULE_TYPES:
                raise PolicyConfigError(f"unknown policy rule '{name}' (known: {sorted(RULE_TYPES)})")
            action = spec.pop("action", None)
            try:
                rules.append(RULE_TYPES[name](action=Action(action) if action else None, **spec))
            except ValueError as exc:
                raise PolicyConfigError(f"rule '{name}': {exc}") from exc
        # the policy's own hash is recorded on every run: which rules governed it is auditable
        return cls(rules, hashlib.sha256(text.encode()).hexdigest())

    @classmethod
    def permissive(cls) -> "PolicyEngine":
        """No rules. For engine unit tests only; the CLI always loads a policy file."""
        return cls([], "permissive")

    def evaluate(self, changes: ChangeSet, stage: StageSpec) -> PolicyDecision:
        violations = [v for rule in self.rules for v in rule.evaluate(changes, stage)]
        action = max((v.action for v in violations), key=lambda a: a.severity, default=Action.ALLOW)
        return PolicyDecision(action=action, tier=TIER_FOR_ACTION[action], violations=violations,
                              policy_sha=self.policy_sha)
