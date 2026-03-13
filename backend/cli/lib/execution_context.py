"""Shared execution-context helpers for CLI commands.

Keeps project/worktree detection logic in one place for CLI consumers.
"""

from __future__ import annotations

import subprocess
from pathlib import Path


def resolve_git_common_dir(cwd: Path | None = None) -> Path | None:
    """Return the common git dir for the current checkout, if available."""
    target = cwd or Path.cwd()
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--path-format=absolute", "--git-common-dir"],
            cwd=target,
            capture_output=True,
            text=True,
            check=True,
        )
    except subprocess.CalledProcessError:
        return None

    value = result.stdout.strip()
    return Path(value).resolve() if value else None


def canonical_repo_root(cwd: Path | None = None) -> Path | None:
    """Resolve the canonical repo root backing the current checkout."""
    common_dir = resolve_git_common_dir(cwd)
    if common_dir is None:
        return None
    if common_dir.name == ".git":
        return common_dir.parent.resolve()
    return common_dir.resolve()


