"""Utility functions for autonomous task execution."""

from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)


def get_project_repo_path(project_id: str) -> Path:
    """Get repository path for a project.

    Args:
        project_id: Project ID

    Returns:
        Path to project repository

    Raises:
        ValueError: If project not found
    """
    from app.storage.projects import get_project_root_path

    root_path = get_project_root_path(project_id)
    if not root_path:
        raise ValueError(f"Project {project_id} not found or has no root_path")
    return Path(root_path)
