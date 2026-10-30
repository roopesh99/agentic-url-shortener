"""Derive structured-output JSON schemas from Pydantic models.

The Pydantic model is the single source of truth: it generates the schema sent
to the API and validates what comes back (including replayed cassettes, which
are files in the repo and could be hand-edited).
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

_DROP = {"title", "default", "description", "examples"}


def strict_schema(model: type[BaseModel]) -> dict[str, Any]:
    raw = model.model_json_schema()
    defs = raw.pop("$defs", {})

    def walk(node: Any) -> Any:
        if isinstance(node, list):
            return [walk(n) for n in node]
        if not isinstance(node, dict):
            return node
        if "$ref" in node:
            return walk(defs[node["$ref"].rsplit("/", 1)[1]])
        out = {k: walk(v) for k, v in node.items() if k not in _DROP}
        if out.get("type") == "object" and "properties" in out:
            out["additionalProperties"] = False
            out["required"] = list(out["properties"])  # optional fields are expressed as nullable
        return out

    return walk(raw)
