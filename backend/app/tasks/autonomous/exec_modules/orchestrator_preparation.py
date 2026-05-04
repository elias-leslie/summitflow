"""Checkout and closeout preparation helpers for autonomous execution."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any


def prepare_execution(
    task_id: str,
    project_id: str,
    *,
    task_store: Any,
    emit_error: Callable[..., None],
    validate_pristine_codebase: Callable[[str, str], bool],
    setup_task_checkout: Callable[[str, str], str | None],
) -> tuple[dict[str, Any] | None, str | None, str | None, str | None]:
    """Validate task and set up shared checkout."""
    task = task_store.get_task(task_id)
    if not task:
        emit_error(task_id, "Task not found", recoverable=False, project_id=project_id)
        return {"task_id": task_id, "status": "error", "message": "Task not found"}, None, None, None

    if not validate_pristine_codebase(task_id, project_id):
        return _setup_failed_result(task_id, "Pristine validation failed", "pristine_self_heal_failed"), None, None, None

    project_path = setup_task_checkout(task_id, project_id)
    if not project_path:
        return _setup_failed_result(task_id, "Task branch setup failed", "task_branch_setup_failed"), None, None, None

    return None, project_path, task.get("task_type"), task.get("agent_override")


def active_task_checkpoint(task_id: str, project_id: str, *, load_snapshot_meta: Callable[[str], Any]) -> bool:
    """Return whether task still has active checkpoint metadata to clean up."""
    meta = load_snapshot_meta(task_id)
    return meta is not None and meta.project_id == project_id


def prepare_completed_task_closeout(
    task_id: str,
    project_id: str,
    *,
    validate_pristine_codebase: Callable[[str, str], bool],
    has_active_task_checkpoint: Callable[[str, str], bool],
    get_task_checkout: Callable[[str, str], Any],
    setup_task_checkout: Callable[[str, str], str | None],
    emit_log: Callable[..., None],
) -> dict[str, Any] | None:
    """Run safety checks before early-completing a task whose subtasks already passed."""
    if not validate_pristine_codebase(task_id, project_id):
        return _setup_failed_result(task_id, "Pristine validation failed", "pristine_self_heal_failed")

    if not has_active_task_checkpoint(task_id, project_id):
        emit_log(task_id, "info", "All subtasks already complete; skipping checkout setup", project_id=project_id)
        return None

    if not get_task_checkout(task_id, project_id):
        emit_log(
            task_id,
            "warning",
            "All subtasks already complete; active checkpoint metadata remains but no task branch exists, skipping checkout recovery",
            project_id=project_id,
        )
        return None

    emit_log(
        task_id,
        "info",
        "All subtasks already complete; reusing existing task branch to recover residue before closeout",
        project_id=project_id,
    )
    if setup_task_checkout(task_id, project_id):
        return None
    return _setup_failed_result(task_id, "Task branch setup failed", "task_branch_setup_failed")


def _setup_failed_result(task_id: str, error: str, reason: str) -> dict[str, Any]:
    return {"task_id": task_id, "status": "failed", "error": error, "reason": reason}
