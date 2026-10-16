"""Git operations for done command.

Working tree checks for the done command.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

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

    cmd = ["git", "--no-optional-locks", "status", "--porcelain"]
    if path:
        cmd = ["git", "--no-optional-locks", "-C", path, "status", "--porcelain"]

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

