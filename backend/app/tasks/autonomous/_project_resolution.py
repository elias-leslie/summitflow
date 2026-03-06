"""Shared task project-resolution helpers for autonomous flows."""

from __future__ import annotations

from ...workflows._model_constants import DEFAULT_PROJECT_ID


def resolve_task_project_id(
    task: dict[str, object] | None,
    project_id: str | None = None,
) -> str:
    """Resolve project scope from explicit input or a loaded task record."""
    if project_id:
        return project_id
    if task and task.get("project_id"):
        return str(task["project_id"])
    return DEFAULT_PROJECT_ID


__all__ = ["resolve_task_project_id"]
