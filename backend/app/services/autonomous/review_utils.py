"""Shared utilities for review services.

Provides common types and helper functions used across review modules.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

Verdict = Literal["APPROVE", "REJECT", "REQUEST_FIX"]


def get_project_path(task: dict[str, Any], resolved_path: Path | str | None) -> Path:
    """Get project path from explicit param or task's project_id.

    Args:
        task: Task dict (may contain project_id)
        resolved_path: Optional explicit path

    Returns:
        Resolved project path

    Raises:
        ValueError: If path cannot be determined
    """
    if resolved_path:
        return Path(resolved_path)

    project_id = task.get("project_id")
    if not project_id:
        raise ValueError("Task missing project_id and no resolved_path provided")

    from app.storage.projects import get_project_root_path

    root = get_project_root_path(project_id)
    if not root:
        raise ValueError(f"Project {project_id} not found or has no root_path")
    return Path(root)
