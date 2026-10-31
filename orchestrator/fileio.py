"""Small filesystem helpers shared across layers."""

from __future__ import annotations

import os
from pathlib import Path


def load_env_file(path: Path) -> list[str]:
    """Load `KEY=value` lines into the environment; variables already set win.

    Returns the names loaded (never values). Supports comments, blank lines,
    an optional `export ` prefix and matching single/double quotes.
    """
    if not path.is_file():
        return []
    loaded = []
    for lineno, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        line = line.removeprefix("export ").strip()
        key, sep, value = line.partition("=")
        key, value = key.strip(), value.strip()
        if not sep or not key.isidentifier():
            raise ValueError(f"{path}:{lineno}: expected KEY=value")
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
            value = value[1:-1]
        if key not in os.environ:
            os.environ[key] = value
            loaded.append(key)
    return loaded


def is_private(path: Path) -> bool:
    """True when only the owner can read the file (no group/other permissions)."""
    return path.stat().st_mode & 0o077 == 0


def write_atomic(path: Path, text: str) -> None:
    """Other processes poll for these files, so they must never observe a partial write."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)
