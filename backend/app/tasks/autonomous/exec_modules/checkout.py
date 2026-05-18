"""Project path resolution for autonomous execution."""

from __future__ import annotations

from ....storage.projects import get_project_root_path


def get_project_path(project_id: str, task_id: str | None = None) -> str:
    """Resolve the project root path for execution.

    Args:
        project_id: Project ID
        task_id: Unused; retained for call-site compatibility.

    Returns:
        Project root path

    Raises:
        ValueError: If project has no root_path configured
    """
    del task_id
    project_root = get_project_root_path(project_id)
    if not project_root:
        raise ValueError(f"Project {project_id} has no root_path configured")
    return project_root
