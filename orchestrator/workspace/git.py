"""Git checkpoints for a run's workspace.

Each accepted stage becomes one commit containing only that stage's files, so the branch
history is the delivery history: reviewable per stage, and a recovery point after a crash.

Ownership rules (never surprise a person's own repository):
- a directory that is not itself a repository root gets a fresh repository of its own
  (a nested repo is fine: run workspaces live under the git-ignored runs/ directory);
- an existing repository root is used only if its working tree is clean, and only on a new
  `orch/<run-id>` branch; the branch it started from is recorded.
Commits are authored as the orchestrator via `-c` flags; no git config is written.
"""

from __future__ import annotations

import subprocess
from fnmatch import fnmatch
from pathlib import Path

AUTHOR = ["-c", "user.name=orchestrator", "-c", "user.email=orchestrator@localhost"]


class WorkspaceError(RuntimeError):
    pass


class GitWorkspace:
    def __init__(self, path: Path, run_id: str, *, untracked_ok: list[str] = ()) -> None:
        self.path = path.resolve()
        self.run_id = run_id
        self.branch = f"orch/{run_id}"
        # directories the orchestrator itself wrote into before the run began (the workflow selector's
        # recorded exchange): new files there do not make the tree dirty; nothing else is exempt
        self.untracked_ok = [d.rstrip("/") + "/" for d in untracked_ok]

    def _git(self, *args: str, check: bool = True) -> str:
        proc = subprocess.run(["git", *AUTHOR, *args], cwd=self.path, capture_output=True, text=True)
        if check and proc.returncode != 0:
            raise WorkspaceError(f"git {' '.join(args)} failed: {proc.stderr.strip() or proc.stdout.strip()}")
        return proc.stdout.strip()

    def is_repo_root(self) -> bool:
        proc = subprocess.run(["git", "rev-parse", "--show-toplevel"], cwd=self.path, capture_output=True, text=True)
        return proc.returncode == 0 and Path(proc.stdout.strip()).resolve() == self.path

    def prepare(self) -> dict[str, str]:
        """Make the workspace ready for checkpoints; returns facts for the audit log."""
        self.path.mkdir(parents=True, exist_ok=True)
        if not self.is_repo_root():
            self._git("init", "-q", "-b", self.branch)
            self._git("add", "-A")
            self._git("commit", "-q", "--allow-empty", "-m", f"orch({self.run_id}): workspace baseline")
            return {"mode": "initialized", "branch": self.branch, "base_commit": self.head()}
        dirty = [line for line in self._git("status", "--porcelain").splitlines()
                 if not (line.startswith("?? ") and any(line[3:].startswith(d) for d in self.untracked_ok))]
        if dirty:
            raise WorkspaceError(f"{self.path} has uncommitted changes; commit or stash them before a run uses it")
        started_from = self._git("rev-parse", "--abbrev-ref", "HEAD")
        self._git("checkout", "-q", "-b", self.branch)
        return {"mode": "branch", "branch": self.branch, "started_from": started_from, "base_commit": self.head()}

    def head(self) -> str:
        return self._git("rev-parse", "HEAD")

    def checkpoint(self, paths: list[str], message: str) -> str | None:
        """Commit exactly these paths (nothing else that happens to be staged or dirty)."""
        if not paths:
            return None
        self._git("add", "-A", "--", *paths)
        if not self._git("diff", "--cached", "--name-only", "--", *paths):
            return None  # identical to what is already committed
        self._git("commit", "-q", "-m", message, "--", *paths)
        return self.head()

    def discard_uncommitted(self, scopes: list[str]) -> list[str]:
        """Resume support: drop uncommitted changes inside the given write scopes
        (an interrupted stage's half-applied files). Everything else is left alone."""
        dirty = []
        for line in self._git("status", "--porcelain", "--untracked-files=all").splitlines():
            path = line[3:].split(" -> ")[-1]
            if any(fnmatch(path, glob) for glob in scopes):
                dirty.append((line[:2], path))
        for status, path in dirty:
            if status == "??":
                (self.path / path).unlink(missing_ok=True)
            else:
                self._git("checkout", "-q", "HEAD", "--", path)
        return [p for _, p in dirty]
