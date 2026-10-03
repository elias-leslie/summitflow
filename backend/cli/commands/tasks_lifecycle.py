"""Task lifecycle management commands."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import typer

from ..client import APIError, STClient
from ..context import require_task_id
from ..output import handle_api_error, output_error, output_success, output_task, output_warning


def _cleanup_safe_pause_residue(task_id: str, project_id: str | None) -> str | None:
    """Drop only clean direct-to-main pause metadata; preserve legacy task refs."""
    if not project_id:
        return None
    from app.storage.projects import get_project_root_path
    from app.storage.tasks import canonicalize_task_id, get_task

    from ..lib.checkpoint import remove_snapshot
    from ..lib.checkpoint_metadata import load_snapshot_meta
    from ..lib.commit_workflow import run_git

    try:
        task_id = canonicalize_task_id(task_id)
        checkpoint = load_snapshot_meta(task_id)
        if checkpoint is None:
            return None
        if checkpoint.task_id != task_id or checkpoint.project_id != project_id:
            return "checkpoint_kept:scope_mismatch"
        root = get_project_root_path(project_id)
        if not root:
            return "checkpoint_kept:project_root_unavailable"
        status = run_git(Path(root), ["status", "--porcelain", "--untracked-files=all"])
        if status.returncode != 0:
            return "checkpoint_kept:inspection_unavailable"
        if status.stdout.strip():
            return "checkpoint_kept:uncommitted_changes"
        refs = run_git(Path(root), ["for-each-ref", "--format=%(refname)", "refs/heads/"])
        if refs.returncode != 0:
            return "checkpoint_kept:inspection_unavailable"
        task_refs = (f"refs/heads/{task_id}", f"refs/heads/task/{task_id}")
        if any(
            ref == prefix or ref.startswith(prefix + "/")
            for ref in refs.stdout.splitlines()
            for prefix in task_refs
        ):
            return "checkpoint_kept:legacy_task_refs"
        # A pause can race a reopen/reclaim: don't discard a replacement checkpoint.
        task = get_task(task_id)
        if not task or task.get("id") != task_id or task.get("project_id") != project_id or task.get("status") != "paused":
            return "checkpoint_kept:task_not_paused"
        if load_snapshot_meta(task_id) != checkpoint:
            return "checkpoint_kept:checkpoint_changed"
        return "checkpoint_cleaned" if remove_snapshot(task_id, project_id=project_id) else "checkpoint_kept:cleanup_unavailable"
    except Exception:
        # The API pause succeeded; optional local cleanup must not undo it or leak diagnostics.
        return "checkpoint_kept:inspection_unavailable"


def cancel_task_command(
    task_id: str | None,
    reason: str,
) -> None:
    """Cancel a task (mark as cancelled from any state)."""
    task_id = require_task_id(task_id)
    client = STClient()

    try:
        task = client.cancel_task(task_id, reason=reason or None)
    except APIError as e:
        handle_api_error(e)
        return

    task["cancel_reason"] = reason
    output_task(task)


def pause_task_command(
    task_id: str | None,
    reason: str,
) -> None:
    """Pause a task and release any active claim while preserving task state."""
    task_id = require_task_id(task_id)
    client = STClient()

    try:
        task = client.pause_task(task_id, reason=reason or None)
    except APIError as e:
        handle_api_error(e)
        return

    cleanup_result = _cleanup_safe_pause_residue(task.get("id") or task_id, task.get("project_id"))
    if reason:
        task["pause_reason"] = reason
    output_task(task)
    if cleanup_result:
        if cleanup_result.startswith("checkpoint_kept:"):
            output_warning(cleanup_result)
        else:
            output_success(cleanup_result)


def delete_task_command(
    task_id: str | None,
) -> None:
    """Delete a task."""
    task_id = require_task_id(task_id)
    client = STClient()

    try:
        client.delete_task(task_id)
    except APIError as e:
        handle_api_error(e)
        return

    output_success(f"Deleted task {task_id}")


def reopen_task_command(
    task_id: str | None,
    reason: str,
) -> None:
    """Reopen a task by moving it back to pending.

    Accepts any non-pending state (paused, completed, cancelled, failed).
    """
    task_id = require_task_id(task_id)
    client = STClient()

    try:
        task = client.reopen_task(task_id, reason=reason or None)
    except APIError as e:
        handle_api_error(e)
        return

    if reason:
        task["reopen_reason"] = reason
    output_task(task)


def update_task_command(
    task_id: str,
    *,
    title: str | None = None,
    priority: int | None = None,
    labels: str | None = None,
    description: str | None = None,
    plan: Path | None = None,
) -> None:
    """Update in-flight task fields. Refuses status changes (use lifecycle verbs)."""
    task_id = require_task_id(task_id)
    fields: dict[str, Any] = {}
    if title is not None:
        fields["title"] = title
    if priority is not None:
        fields["priority"] = priority
    if labels is not None:
        fields["labels"] = [item.strip() for item in labels.split(",") if item.strip()]
    if description is not None:
        fields["description"] = description

    if not fields and plan is None:
        output_error(
            "st update needs at least one field to change.\n"
            "Resolution: pass --title, --priority, --labels, --description, or --plan"
        )
        raise typer.Exit(1)

    client = STClient()
    try:
        task = client.update_task(task_id, **fields) if fields else client.get_task(task_id)
    except APIError as e:
        handle_api_error(e)
        return

    if plan is not None:
        _apply_plan_swap(task_id, plan)
        try:
            task = client.get_task(task_id)
        except APIError as e:
            handle_api_error(e)
            return
        task["plan_swapped"] = True

    output_task(task)


def _apply_plan_swap(task_id: str, plan: Path) -> None:
    """Replace the task's spirit plan and reset plan_status to draft."""
    try:
        raw = json.loads(plan.read_text())
    except (OSError, json.JSONDecodeError) as e:
        output_error(
            f"Failed to read plan {plan}: {e}\n"
            "Resolution: pass a JSON plan file with at least {title, subtasks}"
        )
        raise typer.Exit(1) from None

    from app.storage import task_spirit as spirit_store

    from .tasks_helpers import upsert_task_spirit_from_plan
    upsert_task_spirit_from_plan(task_id, raw)
    spirit_store.set_plan_status(task_id, "draft", actor="st-update-plan")
