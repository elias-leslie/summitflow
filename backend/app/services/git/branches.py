"""Git branch operations."""

from __future__ import annotations

from pathlib import Path

from ...logging_config import get_logger
from ...utils import safe_subprocess  # noqa: F401  # retained patch surface
from ...utils.agent_execution import run_source_git

logger = get_logger(__name__)


def get_current_branch(project_path: str | Path) -> str:
    """Get the current git branch name.

    Args:
        project_path: Path to the git repository

    Returns:
        Current branch name
    """
    project_path = Path(project_path)

    result = run_source_git(
        ["git", "-C", str(project_path), "rev-parse", "--abbrev-ref", "HEAD"],
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        raise RuntimeError(f"Failed to get current branch: {result.stderr}")

    return result.stdout.strip()
