"""Private helpers for checkpoint.py — not part of the public API."""

from __future__ import annotations

import subprocess
import sys


def create_legacy_branch(task_id: str) -> None:
    """Create an in-repo branch for task_id."""
    try:
        subprocess.run(
            ["git", "checkout", "-b", f"{task_id}/main"],
            check=True, capture_output=True, text=True,
        )
    except subprocess.CalledProcessError as e:
        print(f"Error: Failed to create git branch: {e.stderr}", file=sys.stderr)
        sys.exit(1)
