"""Git operations for worktree management."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

from ..config import get_config


def get_project_root() -> Path:
    """Get the current project's root directory."""
    config = get_config()
    if config.project_root:
        return Path(config.project_root)
    # Fallback: try to find git root from cwd
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            cwd=Path.cwd(),
        )
        if result.returncode == 0:
            return Path(result.stdout.strip())
    except Exception:
        pass
    # Last resort: use cwd
    return Path.cwd()


def get_worktrees_from_git(project_root: Path) -> list[dict[str, Any]]:
    """Get worktrees from git worktree list.

    Args:
        project_root: Root directory of the git repository
    """
    try:
        result = subprocess.run(
            ["git", "worktree", "list", "--porcelain"],
            capture_output=True,
            text=True,
            cwd=str(project_root),
        )
        if result.returncode != 0:
            return []

        worktrees: list[dict[str, Any]] = []
        current: dict[str, Any] = {}
        for line in result.stdout.strip().split("\n"):
            if not line:
                if current:
                    worktrees.append(current)
                    current = {}
                continue
            if line.startswith("worktree "):
                current["path"] = line[9:]
            elif line.startswith("HEAD "):
                current["head"] = line[5:]
            elif line.startswith("branch "):
                current["branch"] = line[7:]

        if current:
            worktrees.append(current)

        return worktrees
    except Exception:
        return []
