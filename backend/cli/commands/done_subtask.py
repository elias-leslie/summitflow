"""Subtask completion logic for done command.

Subtasks complete when the completion gate passes; work has already been
committed to main with file-level coordination via `st lease`.
"""

from __future__ import annotations

import contextlib

import typer

from ..client import APIError, STClient
from ..lib.checkpoint import get_snapshot_info
from ..output import output_error
from .done_git import is_working_tree_clean
from .done_validators import parse_db_error


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
    """Close subtask via API."""
    del project_id
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


def auto_close_subtasks(
    client: STClient,
    task_id: str,
    project_id: str | None,
) -> None:
    """Auto-close all unpassed subtasks in dependency order."""
    subtasks_resp = client.get_subtasks(task_id)
    subtasks = subtasks_resp.get("subtasks", [])
    all_ids = {
        str(subtask_id)
        for subtask in subtasks
        if (subtask_id := subtask.get("subtask_id") or subtask.get("id"))
    }
    passed_ids = {
        str(subtask_id)
        for subtask in subtasks
        if subtask.get("passes") is True and (subtask_id := subtask.get("subtask_id") or subtask.get("id"))
    }
    remaining = [subtask for subtask in subtasks if subtask.get("passes") is not True]

    while remaining:
        next_remaining = []
        progressed = False
        for subtask in remaining:
            subtask_id = subtask.get("subtask_id") or subtask.get("id")
            if not subtask_id:
                continue
            dependencies = {
                str(dep)
                for dep in (subtask.get("depends_on") or [])
                if isinstance(dep, str) and dep in all_ids
            }
            if dependencies - passed_ids:
                next_remaining.append(subtask)
                continue
            citations_status = subtask.get("citations_status") or subtask.get(
                "citations_acknowledged"
            )
            _acknowledge_citations(client, task_id, str(subtask_id), citations_status)
            _close_subtask(client, task_id, str(subtask_id), project_id)
            passed_ids.add(str(subtask_id))
            progressed = True
        if not progressed:
            blocked = ", ".join(str(subtask.get("subtask_id") or subtask.get("id")) for subtask in next_remaining)
            output_error(f"Cannot auto-close subtasks; dependency cycle or missing dependency: {blocked}")
            raise typer.Exit(1)
        remaining = next_remaining


def _validate_working_tree_clean() -> None:
    """Ensure working tree has no uncommitted changes."""
    if not is_working_tree_clean():
        output_error(
            "Working tree has uncommitted changes.\nUse task-level closeout: st done <task-id> -m 'message'"
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


def _resolve_citations_for_subtask(
    client: STClient,
    task_id: str,
    subtask_id: str,
    citations: list[str] | None,
    acknowledge_none: bool,
) -> None:
    """Record subtask citations before marking it passed.

    Replaces the old `st subtask pass` flow — citations now live with `st done`.
    """
    if citations and acknowledge_none:
        output_error("Use either --citation or --none, not both.")
        raise typer.Exit(1)
    if not citations and not acknowledge_none:
        # No-op: API will accept the pass if citations are already on file.
        return
    from .subtask import _normalize_inline_citations  # local import to avoid cycle

    try:
        if citations:
            client.log_citations(task_id, subtask_id, _normalize_inline_citations(citations))
        else:
            client.acknowledge_no_citations(task_id, subtask_id)
    except APIError as e:
        output_error(f"Failed to record citations: {e.detail}")
        raise typer.Exit(1) from None


def complete_subtask(
    client: STClient,
    subtask_id: str,
    task_id: str,
    message: str | None = None,
    citations: list[str] | None = None,
    acknowledge_none: bool = False,
) -> dict[str, str | bool]:
    """Complete a subtask.

    Already-passed subtasks return a `resumed` no-op (idempotent close).
    """
    del message
    subtasks = client.get_subtasks(task_id).get("subtasks", [])
    already_passed = any(
        (str(sub.get("subtask_id") or sub.get("id")) == subtask_id) and sub.get("passes") is True
        for sub in subtasks
    )
    if already_passed:
        return {
            "task_id": task_id,
            "subtask_id": subtask_id,
            "action": "noop",
            "merged": False,
        }

    _validate_working_tree_clean()
    _get_project_id(task_id)

    _resolve_citations_for_subtask(client, task_id, subtask_id, citations, acknowledge_none)
    _update_subtask_status(client, task_id, subtask_id)

    return {
        "task_id": task_id,
        "subtask_id": subtask_id,
        "action": "completed",
        "merged": False,
    }
