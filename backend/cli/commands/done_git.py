"""Git operations for done command.

Handles stashing, working tree checks, and git state verification.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from ..output import output_warning

GIT_TIMEOUT = 60  # seconds


def is_working_tree_clean(path: str | None = None) -> bool:
    """Check if git working tree is clean.

    Args:
        path: Directory to check. If None, checks current directory.

    Returns:
        True if clean (no uncommitted changes), or if path doesn't exist.
        False if there are uncommitted changes.
    """
    if path and not Path(path).exists():
        return True

    cmd = ["git", "status", "--porcelain"]
    if path:
        cmd = ["git", "-C", path, "status", "--porcelain"]

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=True,
            timeout=GIT_TIMEOUT,
        )
        return len(result.stdout.strip()) == 0
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return False


def _get_stash_count() -> int:
    """Get the current count of stash entries."""
    result = subprocess.run(
        ["git", "stash", "list"],
        capture_output=True,
        text=True,
        check=True,
        timeout=GIT_TIMEOUT,
    )
    return len(result.stdout.strip().splitlines()) if result.stdout.strip() else 0


def git_stash_push() -> bool:
    """Stash uncommitted changes on main for merge.

    Returns:
        True if a stash entry was created, False if nothing to stash.
    """
    try:
        before_count = _get_stash_count()

        subprocess.run(
            ["git", "stash", "push", "-m", "st-done-auto"],
            capture_output=True,
            text=True,
            check=True,
            timeout=GIT_TIMEOUT,
        )

        after_count = _get_stash_count()
        return after_count > before_count
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
        raw = e.stderr if hasattr(e, "stderr") else str(e)
        stderr = raw.decode() if isinstance(raw, bytes) else raw
        output_warning(f"git stash push failed: {stderr}")
        return False


def git_stash_pop() -> None:
    """Pop the most recent stash entry."""
    try:
        subprocess.run(
            ["git", "stash", "pop"],
            capture_output=True,
            text=True,
            check=True,
            timeout=GIT_TIMEOUT,
        )
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
        raw = e.stderr if hasattr(e, "stderr") else str(e)
        stderr = raw.decode() if isinstance(raw, bytes) else raw
        output_warning(
            f"git stash pop failed (manual resolve may be needed): {stderr}"
        )
