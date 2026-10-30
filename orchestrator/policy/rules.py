"""Policy rules. Each inspects a proposed `ChangeSet` and returns violations.

Rules are configured (and can be tightened) in `policies/*.yaml`; the action a
rule demands is part of that configuration, not hard-coded, so changing what
is blocked vs. approved is itself a reviewable change.
"""

from __future__ import annotations

import math
import re
import xml.etree.ElementTree as ET
from abc import ABC, abstractmethod
from collections import Counter
from fnmatch import fnmatch
from typing import Any

from ..engine.models import StageSpec
from ..workspace.changes import ChangeSet, FileChange
from .models import Action, Category, Violation


class Rule(ABC):
    name: str
    category: Category
    default_action: Action

    def __init__(self, action: Action | None = None, include: list[str] | None = None,
                 exclude: list[str] | None = None, **params: Any) -> None:
        self.action = action or self.default_action
        self.include = include or ["*"]
        self.exclude = exclude or []
        self.params = params

    def applies_to(self, path: str) -> bool:
        return any(fnmatch(path, p) for p in self.include) and not any(fnmatch(path, p) for p in self.exclude)

    def files(self, changes: ChangeSet) -> list[FileChange]:
        return [c for c in changes if self.applies_to(c.path)]

    def violation(self, message: str, path: str | None = None, line: int | None = None) -> Violation:
        return Violation(rule=self.name, category=self.category, action=self.action,
                         message=message, path=path, line=line)

    @abstractmethod
    def evaluate(self, changes: ChangeSet, stage: StageSpec) -> list[Violation]: ...


class _LinePatternRule(Rule):
    """Flags added lines matching any configured pattern. Only *added* lines are
    checked, so pre-existing code doesn't fail every later stage."""

    patterns: dict[str, str] = {}

    def evaluate(self, changes: ChangeSet, stage: StageSpec) -> list[Violation]:
        compiled = {label: re.compile(rx) for label, rx in {**self.patterns, **self.params.get("patterns", {})}.items()}
        out = []
        for change in self.files(changes):
            for lineno, text in change.added_lines():
                for label, rx in compiled.items():
                    if rx.search(text):
                        out.append(self.violation(label, change.path, lineno))
        return out


class SecretsRule(_LinePatternRule):
    name = "secrets"
    category = Category.SECURITY
    default_action = Action.REJECT
    patterns = {
        "AWS access key id": r"\bAKIA[0-9A-Z]{16}\b",
        "private key block": r"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----",
        "Anthropic API key": r"\bsk-ant-[A-Za-z0-9_-]{20,}",
        "GitHub token": r"\bgh[pousr]_[A-Za-z0-9]{36,}\b",
        "Slack token": r"\bxox[baprs]-[A-Za-z0-9-]{10,}",
        "hard-coded credential assignment":
            r"(?i)\b(password|passwd|secret|api[_-]?key|access[_-]?token|client[_-]?secret)\b"
            r"\s*[:=]\s*[\"'](?!\$\{)[^\"'\s]{6,}[\"']",
    }

    def evaluate(self, changes: ChangeSet, stage: StageSpec) -> list[Violation]:
        out = super().evaluate(changes, stage)
        threshold = self.params.get("entropy_threshold", 4.5)
        min_len = self.params.get("entropy_min_length", 32)
        for change in self.files(changes):
            for lineno, text in change.added_lines():
                for token in re.findall(r"[\"']([A-Za-z0-9+/=_\-]{%d,})[\"']" % min_len, text):
                    if _entropy(token) >= threshold and not _is_charset(token):
                        out.append(self.violation(f"high-entropy string literal (entropy {_entropy(token):.1f})",
                                                  change.path, lineno))
        return out


class DangerousCodeRule(_LinePatternRule):
    name = "dangerous_code"
    category = Category.SECURITY
    default_action = Action.REJECT
    patterns = {
        "OS command execution": r"Runtime\.getRuntime\(\)\.exec|new\s+ProcessBuilder\s*\(",
        "SQL built by string concatenation":
            r"(?i)(execute(Query|Update)?|prepareStatement|createQuery|createNativeQuery)\s*\(\s*\"[^\"]*\"\s*\+",
        "Java native deserialization": r"new\s+ObjectInputStream\s*\(",
        "wildcard CORS": r"@CrossOrigin\s*(\(\s*\)|\([^)]*\"\*\")|allowedOrigins\s*\(\s*\"\*\"",
        "TLS verification disabled": r"TrustAllCerts|NoopHostnameVerifier|setHostnameVerifier\s*\(\s*\(.*\)\s*->\s*true",
    }


class PiiLoggingRule(_LinePatternRule):
    name = "pii_logging"
    category = Category.COMPLIANCE
    default_action = Action.REJECT
    patterns = {
        "sensitive field written to logs":
            r"(?i)\b(log|logger)\.(trace|debug|info|warn|error)\s*\(.*\b(password|email|ssn|"
            r"credit_?card|phone(number)?|access_?token|ip_?address|remoteaddr)\b",
    }


class DependencyAllowlistRule(Rule):
    """New Maven dependencies must be pre-approved; anything else needs a human."""

    name = "dependency_allowlist"
    category = Category.CHANGE_CONTROL
    default_action = Action.REQUIRE_APPROVAL

    def evaluate(self, changes: ChangeSet, stage: StageSpec) -> list[Violation]:
        allowed = self.params.get("allowed", [])
        out = []
        for change in changes:
            if not change.path.endswith("pom.xml"):
                continue
            try:
                added = _maven_deps(change.content) - (_maven_deps(change.previous) if change.previous else set())
            except ET.ParseError as exc:
                out.append(self.violation(f"pom.xml is not well-formed: {exc}", change.path))
                continue
            for dep in sorted(added):
                if not any(fnmatch(dep, pattern) for pattern in allowed):
                    out.append(self.violation(f"new dependency not on allowlist: {dep}", change.path))
        return out


class HighImpactPathsRule(Rule):
    """Changes to sensitive areas need a human. `paths`: any change (create or modify);
    `modify_only`: only changes to files that already exist (e.g. config)."""

    name = "high_impact_paths"
    category = Category.CHANGE_CONTROL
    default_action = Action.REQUIRE_APPROVAL

    def evaluate(self, changes: ChangeSet, stage: StageSpec) -> list[Violation]:
        out = []
        for change in changes:
            patterns = self.params.get("paths", []) + ([] if change.is_new else self.params.get("modify_only", []))
            hit = next((p for p in patterns if fnmatch(change.path, p)), None)
            if hit:
                verb = "creates" if change.is_new else "modifies"
                out.append(self.violation(f"{verb} high-impact path (matches '{hit}')", change.path))
        return out


class DiffSizeRule(Rule):
    """Large changes are hard to review; above the limit a human must look."""

    name = "diff_size"
    category = Category.CHANGE_CONTROL
    default_action = Action.REQUIRE_APPROVAL

    def evaluate(self, changes: ChangeSet, stage: StageSpec) -> list[Violation]:
        max_lines = self.params.get("max_changed_lines", 1500)
        max_files = self.params.get("max_files", 40)
        lines = sum(c.changed_lines() for c in changes)
        out = []
        if lines > max_lines:
            out.append(self.violation(f"{lines} changed lines exceeds limit of {max_lines}"))
        if len(changes) > max_files:
            out.append(self.violation(f"{len(changes)} files exceeds limit of {max_files}"))
        return out


RULE_TYPES: dict[str, type[Rule]] = {
    r.name: r for r in (SecretsRule, DangerousCodeRule, PiiLoggingRule,
                        DependencyAllowlistRule, HighImpactPathsRule, DiffSizeRule)
}


def _entropy(s: str) -> float:
    counts = Counter(s)
    return -sum(n / len(s) * math.log2(n / len(s)) for n in counts.values())


def _is_charset(s: str) -> bool:
    """Alphabet constants like "0123...XYZabc...z" are high-entropy but are runs of
    consecutive characters; random secrets essentially never are."""
    sequential = sum(1 for x, y in zip(s, s[1:]) if ord(y) - ord(x) == 1)
    return sequential / (len(s) - 1) > 0.8


def _maven_deps(pom: str) -> set[str]:
    root = ET.fromstring(pom)
    ns = {"m": root.tag[1:].split("}")[0]} if root.tag.startswith("{") else {}
    prefix = "m:" if ns else ""
    # only <dependencies> (not <dependencyManagement>, which declares versions, not usage)
    deps = root.findall(f"{prefix}dependencies/{prefix}dependency", ns)
    return {
        f"{d.findtext(f'{prefix}groupId', '', ns).strip()}:{d.findtext(f'{prefix}artifactId', '', ns).strip()}"
        for d in deps
    }
