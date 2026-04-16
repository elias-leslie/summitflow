"""Shared execution-context helpers for CLI commands.

Keeps project/worktree detection logic in one place for CLI consumers.
"""

from __future__ import annotations

import subprocess
from pathlib import Path


def _resolve_git_path(args: list[str], cwd: Path | None = None) -> Path | None:
    """Resolve a git-derived absolute path for the current checkout."""
    target = cwd or Path.cwd()
    try:
        result = subprocess.run(
            args,
            cwd=target,
            capture_output=True,
            text=True,
            check=True,
        )
    except subprocess.CalledProcessError:
        return None

    value = result.stdout.strip()
    return Path(value).resolve() if value else None


def resolve_git_common_dir(cwd: Path | None = None) -> Path | None:
    """Return the common git dir for the current checkout, if available."""
    return _resolve_git_path(["git", "rev-parse", "--path-format=absolute", "--git-common-dir"], cwd)


def resolve_checkout_root(cwd: Path | None = None) -> Path | None:
    """Return the root directory for the current checkout/worktree."""
    return _resolve_git_path(["git", "rev-parse", "--path-format=absolute", "--show-toplevel"], cwd)


def canonical_repo_root(cwd: Path | None = None) -> Path | None:
    """Resolve the canonical repo root backing the current checkout."""
    common_dir = resolve_git_common_dir(cwd)
    if common_dir is None:
        return None
    if common_dir.name == ".git":
        return common_dir.parent.resolve()
    return common_dir.resolve()
