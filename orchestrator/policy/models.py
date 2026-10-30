"""Policy outcomes and risk tiers."""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class Action(str, Enum):
    """What a violated rule demands, in increasing severity."""

    ALLOW = "allow"
    FLAG = "flag"                          # proceed; recorded for review
    REQUIRE_APPROVAL = "require_approval"  # a human must approve the change before it is applied
    REJECT = "reject"                      # discard the change; agent may retry with the violations as feedback
    BLOCK = "block"                        # stop the stage; never retried

    @property
    def severity(self) -> int:
        return list(Action).index(self)


class RiskTier(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


TIER_FOR_ACTION = {
    Action.ALLOW: RiskTier.LOW,
    Action.FLAG: RiskTier.MEDIUM,
    Action.REQUIRE_APPROVAL: RiskTier.HIGH,
    Action.REJECT: RiskTier.CRITICAL,
    Action.BLOCK: RiskTier.CRITICAL,
}


class Category(str, Enum):
    SECURITY = "security"
    COMPLIANCE = "compliance"
    CHANGE_CONTROL = "change_control"


class Violation(BaseModel):
    rule: str
    category: Category
    action: Action
    message: str
    path: str | None = None
    line: int | None = None

    def describe(self) -> str:
        where = f"{self.path}:{self.line}" if self.line else (self.path or "change set")
        return f"[{self.category.value}/{self.rule}] {where}: {self.message}"


class PolicyDecision(BaseModel):
    action: Action
    tier: RiskTier
    violations: list[Violation] = Field(default_factory=list)
    policy_sha: str

    @property
    def denied(self) -> bool:
        return self.action in (Action.REJECT, Action.BLOCK)

    def at_least(self, action: Action) -> list[Violation]:
        return [v for v in self.violations if v.action.severity >= action.severity]
