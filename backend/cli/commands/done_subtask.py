"""Subtask completion logic for done command.

Handles subtask completion with git branch merging.
"""

from __future__ import annotations

import contextlib

import typer

from ..client import APIError, STClient
from ..lib.checkpoint import get_snapshot_info, merge_subtask_branch
from ..output import output_error
from .done_git import is_working_tree_clean
from .done_validators import parse_db_error


def _verify_step(
    client: STClient,
    task_id: str,
    subtask_id: str,
    step_number: int,
) -> None:
    """Verify a single step and abort on failure."""
    try:
        result = client.update_step(task_id, subtask_id, step_number, passes=True)
        if result.get("passes") is False:
            output_error(
                f"Step {subtask_id}#{step_number} verification failed. Aborting."
            )
            raise typer.Exit(1)
    except APIError as e:
        output_error(f"Step {subtask_id}#{step_number} failed: {e.detail}")
        raise typer.Exit(1) from None


def _verify_subtask_steps(
    client: STClient,
    task_id: str,
    subtask_id: str,
    steps: list[dict[str, str | int | bool]],
) -> None:
    """Verify all unpassed steps for a subtask."""
    for step in steps:
        step_number = step.get("step_number")
        if step_number is None or step.get("passes") is True:
            continue
        if step.get("status") == "plan_defect":
            continue
        _verify_step(client, task_id, subtask_id, int(step_number))


def _acknowledge_citations(
    client: STClient,
    task_id: str,
    subtask_id: str,
    citations_status: str | None,
) -> None:
    """Acknowledge citations if not already done."""
    if not citations_status:
        with contextlib.suppress(APIError):
            client.acknowledge_no_citations(task_id, subtask_id)


def _close_subtask(
    client: STClient,
    task_id: str,
    subtask_id: str,
    project_id: str | None,
) -> None:
    """Close subtask and merge its branch."""
    try:
        client.update_subtask(task_id, subtask_id, passes=True)
    except APIError as e:
        detail: dict[str, str] = (
            e.detail if isinstance(e.detail, dict) else {"detail": str(e.detail)}
        )
        helpful = parse_db_error(detail)
        if helpful:
            output_error(helpful)
        else:
            output_error(f"Failed to close subtask {subtask_id}: {e.detail}")
        raise typer.Exit(1) from None

    try:
        merge_subtask_branch(task_id, subtask_id, project_id=project_id)
    except SystemExit:
        output_error(f"Subtask {subtask_id} merge failed. Resolve conflicts manually.")
        raise typer.Exit(1) from None


def auto_close_subtasks(
    client: STClient,
    task_id: str,
    project_id: str | None,
) -> None:
    """Auto-verify steps, acknowledge citations, and close unpassed subtasks.

    For each subtask not yet passed:
    1. Verify unpassed steps via API (server-side pass marking)
    2. Acknowledge citations if not already done
    3. Close the subtask and merge its branch

    Aborts immediately if any step verification fails.
    """
    subtasks_resp = client.get_subtasks(task_id, include_steps=True)
    subtasks = subtasks_resp.get("subtasks", [])

    for subtask in subtasks:
        subtask_id = subtask.get("subtask_id") or subtask.get("id")
        if not subtask_id or subtask.get("passes") is True:
            continue

        steps = subtask.get("steps") or client.get_steps(task_id, subtask_id)
        _verify_subtask_steps(client, task_id, subtask_id, steps)

        citations_status = subtask.get("citations_status") or subtask.get(
            "citations_acknowledged"
        )
        _acknowledge_citations(client, task_id, subtask_id, citations_status)
        _close_subtask(client, task_id, subtask_id, project_id)


def _validate_working_tree_clean() -> None:
    """Ensure working tree has no uncommitted changes."""
    if not is_working_tree_clean():
        output_error(
            "Working tree has uncommitted changes.\nCommit first: git commit -m 'message'"
        )
        raise typer.Exit(1)


def _get_project_id(task_id: str) -> str | None:
    """Get project_id from snapshot info."""
    snapshot_info = get_snapshot_info(task_id)
    raw_pid = snapshot_info.get("project_id") if snapshot_info else None
    return str(raw_pid) if raw_pid is not None else None


def _update_subtask_status(
    client: STClient,
    task_id: str,
    subtask_id: str,
) -> None:
    """Update subtask status to passed."""
    try:
        client.update_subtask(task_id, subtask_id, passes=True)
    except APIError as e:
        detail: dict[str, str] = (
            e.detail if isinstance(e.detail, dict) else {"detail": str(e.detail)}
        )
        helpful = parse_db_error(detail)
        if helpful:
            output_error(helpful)
        else:
            output_error(f"Failed to complete subtask: {e.detail}")
        raise typer.Exit(1) from None


def _merge_subtask(
    task_id: str,
    subtask_id: str,
    project_id: str | None,
) -> None:
    """Merge subtask branch."""
    try:
        merge_subtask_branch(task_id, subtask_id, project_id=project_id)
    except SystemExit:
        output_error("Merge failed. Resolve conflicts manually, then retry.")
        raise typer.Exit(1) from None


def complete_subtask(
    client: STClient,
    subtask_id: str,
    task_id: str,
    message: str | None = None,
) -> dict[str, str | bool]:
    """Complete a subtask with git branch merge.

    DB triggers verify all steps passed.
    """
    _validate_working_tree_clean()
    project_id = _get_project_id(task_id)

    _update_subtask_status(client, task_id, subtask_id)
    _merge_subtask(task_id, subtask_id, project_id)

    return {
        "task_id": task_id,
        "subtask_id": subtask_id,
        "action": "completed",
        "merged": True,
    }
