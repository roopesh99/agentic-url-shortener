"""Design gates: the OpenAPI definition is valid, the code implements exactly what it documents,
and the documentation covers it. The orchestrator runs these; no agent's word is taken for it."""

from __future__ import annotations

import re
from pathlib import Path

import yaml
from openapi_spec_validator import validate

from ..engine.models import GateResult
from .base import Gate, GateContext

HTTP_METHODS = ("get", "put", "post", "delete", "patch", "head", "options")
_MAPPING = re.compile(r"@(Get|Post|Put|Patch|Delete|Request)Mapping\s*(?:\(([^)]*)\))?")
_STRING = re.compile(r'"([^"]*)"')
_CLASS = re.compile(r"\bclass\s+\w+")
_PARAM = re.compile(r"\{(\w+)(?::(?:[^{}]|\{[^{}]*\})*)?\}")  # {name} or {name:regex}, regex may hold {m,n}


def load_spec(workspace: Path, rel: str) -> dict:
    path = workspace / rel
    if not path.is_file():
        raise FileNotFoundError(f"{rel} does not exist")
    spec = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(spec, dict):
        raise ValueError(f"{rel} is not a YAML mapping")
    return spec


def spec_operations(spec: dict) -> set[tuple[str, str]]:
    return {(method.upper(), path) for path, item in (spec.get("paths") or {}).items()
            for method in (item or {}) if method in HTTP_METHODS}


def normalize(path: str) -> str:
    """`/{code:[A-Za-z0-9_-]{3,32}}` -> `/{code}`, collapse slashes, no trailing slash."""
    path = _PARAM.sub(lambda m: "{" + m.group(1) + "}", path)
    path = re.sub(r"/+", "/", path)
    return path.rstrip("/") or "/"


def code_operations(source_root: Path) -> set[tuple[str, str]]:
    """Spring MVC handler mappings found in the source: (METHOD, path), with class-level prefixes."""
    operations = set()
    for java in sorted(source_root.rglob("*.java")):
        text = java.read_text(encoding="utf-8")
        if "@RestController" not in text and "@Controller" not in text:
            continue
        declaration = _CLASS.search(text)
        if declaration is None:
            continue
        head, body = text[:declaration.start()], text[declaration.end():]
        prefix = ""
        for kind, args in _MAPPING.findall(head):
            if kind == "Request":
                values = _STRING.findall(args or "")
                prefix = values[0] if values else ""
        for kind, args in _MAPPING.findall(body):
            values = _STRING.findall(args or "") or [""]
            path = values[0]
            if path.startswith("${"):
                continue  # framework error page (e.g. ${server.error.path:/error}), not part of the API
            method = "GET" if kind == "Request" else kind.upper()
            operations.add((method, normalize(prefix + "/" + path)))
    return operations


class OpenApiValidGate(Gate):
    """args: path — the OpenAPI file, relative to the workspace."""

    name = "openapi_valid"

    async def check(self, ctx: GateContext) -> GateResult:
        rel = self.args.get("path", "openapi.yaml")
        try:
            spec = load_spec(ctx.workspace, rel)
            validate(spec)
        except Exception as exc:  # parse or validation failure: the evidence is the reason
            return self.result(False, f"{rel}: {type(exc).__name__}: {str(exc).splitlines()[0][:400]}")
        ops = spec_operations(spec)
        if not ops:
            return self.result(False, f"{rel} documents no operations")
        return self.result(True, f"{rel}: valid OpenAPI {spec.get('openapi')}, {len(ops)} operation(s)")


class OpenApiConformanceGate(Gate):
    """The implementation and the approved API definition agree, both ways.
    args: spec — OpenAPI file; source — Java source root (both relative to the workspace)."""

    name = "openapi_conformance"

    async def check(self, ctx: GateContext) -> GateResult:
        try:
            spec = load_spec(ctx.workspace, self.args["spec"])
        except Exception as exc:
            return self.result(False, f"cannot read the API definition: {exc}")
        documented = {(m, normalize(p)) for m, p in spec_operations(spec)}
        implemented = code_operations(ctx.workspace / self.args["source"])
        missing = sorted(documented - implemented)
        undocumented = sorted(implemented - documented)
        if missing or undocumented:
            parts = []
            if missing:
                parts.append("documented but not implemented: " + ", ".join(f"{m} {p}" for m, p in missing))
            if undocumented:
                parts.append("implemented but not documented: " + ", ".join(f"{m} {p}" for m, p in undocumented))
            return self.result(False, "; ".join(parts))
        return self.result(True, f"{len(documented)} operation(s) documented and implemented, none undocumented")


class DocsCoverApiGate(Gate):
    """Every path in the API definition is mentioned in the documentation.
    args: spec — OpenAPI file; docs — list of documentation files (relative to the workspace)."""

    name = "docs_cover_api"

    async def check(self, ctx: GateContext) -> GateResult:
        try:
            spec = load_spec(ctx.workspace, self.args["spec"])
        except Exception as exc:
            return self.result(False, f"cannot read the API definition: {exc}")
        docs = self.args.get("docs", [])
        missing_files = [d for d in docs if not (ctx.workspace / d).is_file()]
        if missing_files:
            return self.result(False, f"missing documentation: {missing_files}")
        text = "\n".join((ctx.workspace / d).read_text(encoding="utf-8") for d in docs)
        uncovered = sorted({p for _, p in spec_operations(spec) if p not in text})
        if uncovered:
            return self.result(False, f"paths not documented: {uncovered}")
        return self.result(True, f"{len(spec_operations(spec))} operation(s) covered by {docs}")


class ChecklistPassedGate(Gate):
    """Release readiness: every checklist item in the agent's output is `pass` (or `n/a` with a reason)."""

    name = "release_checklist_passed"

    async def check(self, ctx: GateContext) -> GateResult:
        assert ctx.artifact is not None, "release_checklist_passed is an exit gate"
        items = ctx.artifact.result.outputs.get("checklist", [])
        if not items:
            return self.result(False, "the release checklist is empty")
        failing = [i["item"] for i in items if i.get("status") == "fail"
                   or (i.get("status") == "n/a" and not i.get("evidence"))]
        if failing:
            return self.result(False, f"release blocked by: {failing}")
        return self.result(True, f"{len(items)} checklist item(s), none failing")
