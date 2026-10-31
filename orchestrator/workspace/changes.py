"""Proposed file changes and the only code path that writes them to disk.

Agents never write directly: they stage a `ChangeSet`, which the policy engine
inspects as a whole before `apply_changes` touches the workspace. A rejected
attempt therefore leaves no partial writes behind.
"""

from __future__ import annotations

import difflib
import hashlib
from dataclasses import dataclass, field
from pathlib import Path


class ScopeViolation(PermissionError):
    pass


def resolve_in_workspace(workspace: Path, rel_path: str) -> Path:
    """Map a relative path to its real location, refusing anything that escapes the
    workspace — including via `..`, absolute paths, or symlinks inside it."""
    rel = Path(rel_path)
    if rel.is_absolute() or ".." in rel.parts:
        raise ScopeViolation(f"path escapes workspace: {rel_path}")
    root = workspace.resolve()
    target = (root / rel).resolve()
    if not target.is_relative_to(root):
        raise ScopeViolation(f"path resolves outside workspace (symlink?): {rel_path}")
    return target


@dataclass(frozen=True)
class FileChange:
    path: str               # posix, relative to workspace
    content: str
    previous: str | None    # on-disk content when proposed; None = new file

    @property
    def is_new(self) -> bool:
        return self.previous is None

    @property
    def sha(self) -> str:
        return hashlib.sha256(self.content.encode()).hexdigest()

    def changed_lines(self) -> int:
        diff = difflib.unified_diff((self.previous or "").splitlines(), self.content.splitlines(), lineterm="", n=0)
        return sum(1 for l in diff if l[:1] in "+-" and not l.startswith(("+++", "---")))

    def added_lines(self) -> list[tuple[int, str]]:
        """(1-based line number in new content, text) for lines not present before."""
        before = set((self.previous or "").splitlines())
        return [(i, l) for i, l in enumerate(self.content.splitlines(), start=1) if l not in before]


@dataclass
class ChangeSet:
    changes: dict[str, FileChange] = field(default_factory=dict)

    def stage(self, workspace: Path, rel_path: str, content: str) -> None:
        target = resolve_in_workspace(workspace, rel_path)
        previous = target.read_text(encoding="utf-8") if target.is_file() else None
        rel = Path(rel_path).as_posix()
        # re-staging a path keeps the original on-disk baseline
        if rel in self.changes:
            previous = self.changes[rel].previous
        self.changes[rel] = FileChange(rel, content, previous)

    @property
    def paths(self) -> list[str]:
        return sorted(self.changes)

    def __iter__(self):
        return iter(self.changes[p] for p in self.paths)

    def __len__(self) -> int:
        return len(self.changes)

    def file_hashes(self) -> dict[str, str]:
        return {c.path: c.sha for c in self}


def apply_changes(workspace: Path, changes: ChangeSet) -> list[str]:
    for change in changes:
        target = resolve_in_workspace(workspace, change.path)  # re-checked at apply time
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(change.content, encoding="utf-8")
    return changes.paths


def revert_changes(workspace: Path, changes: ChangeSet) -> tuple[list[str], list[str]]:
    """Undo an applied change set, file by file: restore each file's previous content, or
    remove it if the change created it.

    Only files whose current content is still exactly what the change wrote are touched, so a
    concurrent stage's (or a person's) later edit is never clobbered. Returns (reverted, conflicts).
    File-level rather than whole-workspace, because parallel stages share the workspace.
    """
    reverted, conflicts = [], []
    for change in changes:
        target = resolve_in_workspace(workspace, change.path)
        current = target.read_text(encoding="utf-8") if target.is_file() else None
        if current != change.content:
            conflicts.append(change.path)
            continue
        if change.previous is None:
            target.unlink()
            _prune_empty_dirs(target.parent, workspace.resolve())
        else:
            target.write_text(change.previous, encoding="utf-8")
        reverted.append(change.path)
    return reverted, conflicts


def _prune_empty_dirs(directory: Path, root: Path) -> None:
    while directory != root and directory.is_relative_to(root) and not any(directory.iterdir()):
        directory.rmdir()
        directory = directory.parent
