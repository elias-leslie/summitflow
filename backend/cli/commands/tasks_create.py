"""Task creation command implementation."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import typer

from ..client import APIError, STClient
from ..config import get_config
from ..output import handle_api_error, output_error, output_task, require_explicit_project
from .task_plan_contract import CREATE_ERROR_HINT
from .tasks_import import create_from_file, import_plan_file


def _build_task_data(
    title: str,
    task_type: str,
    priority: int,
    description: str | None,
    labels: str | None,
    parent: str | None,
    execution_mode: str | None,
    manual_only: bool,
    autonomous: bool,
) -> dict[str, Any]:
    data: dict[str, Any] = {"title": title, "task_type": task_type, "priority": priority}
    if description:
        data["description"] = description
    if labels:
        data["labels"] = labels.split(",")
    if parent:
        data["parent_task_id"] = parent
    if manual_only:
        data["execution_mode"] = "manual_only"
    elif execution_mode:
        data["execution_mode"] = execution_mode
    if autonomous:
        data["autonomous"] = True
    return data


def _apply_blocked_by(
    client: STClient, task: dict[str, Any], blocked_by: str
) -> dict[str, Any]:
    try:
        client.add_dependency(task["id"], blocked_by, dep_type="blocks")
        task["blocked_by"] = blocked_by
    except APIError as e:
        task["dependency_error"] = e.detail
    return task


def _handle_plan_import(
    plan: Path, dry_run: bool, task_id: str | None
) -> None:
    require_explicit_project(get_config())
    client = STClient()
    task, tid = import_plan_file(plan, dry_run, task_id, client)
    if not dry_run:
        complexity = task.get("complexity", "SIMPLE")
        subtask_count = len(task.get("subtasks") or [])
        suffix = "intent-only" if subtask_count == 0 else f"{subtask_count} subtasks"
        second_opinion = ((task.get("context") or {}).get("second_opinion") or {})
        second_opinion_suffix = ""
        if isinstance(second_opinion, dict) and second_opinion.get("required"):
            stage = second_opinion.get("stage", "task_shape")
            status = second_opinion.get("status", "pending")
            second_opinion_suffix = f"|2nd:{stage}:{status}"
        typer.echo(f"IMPORT:{tid}|{complexity}|{suffix}{second_opinion_suffix}")


def _handle_single_task_create(
    title: str,
    dry_run: bool,
    description: str | None,
    priority: int,
    labels: str | None,
    task_type: str,
    parent: str | None,
    blocked_by: str | None,
    execution_mode: str | None,
    manual_only: bool,
    autonomous: bool,
) -> None:
    require_explicit_project(get_config())

    if dry_run:
        output_error("--dry-run only works with --from-file or --plan")
        raise typer.Exit(1)

    client = STClient()
    if manual_only and autonomous:
        output_error("--manual-only conflicts with --autonomous")
        raise typer.Exit(1)
    data = _build_task_data(
        title, task_type, priority, description, labels, parent, execution_mode, manual_only, autonomous
    )

    try:
        task = client.create_task(data)
    except APIError as e:
        handle_api_error(e)
        return

    if blocked_by:
        task = _apply_blocked_by(client, task, blocked_by)

    output_task(task)


def create_capture_task_command(
    title: str,
    description: str | None,
    priority: int,
    labels: str | None,
    task_type: str,
    parent: str | None,
    blocked_by: str | None,
    execution_mode: str | None,
    manual_only: bool,
    autonomous: bool,
) -> None:
    """Create a lightweight capture task without execution-ready plan metadata."""
    _handle_single_task_create(
        title,
        False,
        description,
        priority,
        labels,
        task_type,
        parent,
        blocked_by,
        execution_mode,
        manual_only,
        autonomous,
    )


def create_task_command(
    title: str | None,
    from_file: Path | None,
    dry_run: bool,
    description: str | None,
    priority: int,
    labels: str | None,
    task_type: str,
    parent: str | None,
    plan: Path | None,
    blocked_by: str | None,
    execution_mode: str | None,
    manual_only: bool,
    autonomous: bool,
    task_id: str | None = None,
) -> None:
    """Create an execution-ready task from plan or batch create from file.

    Requires explicit project (-P flag or ST_PROJECT_ID env var).

    Examples:
        st -P summitflow create --plan plan.json
        st -P summitflow create --plan plan.json --task existing-id
        st -P summitflow create --from-file tasks.json
        st -P summitflow create --from-file tasks.json --dry-run
    """
    if plan:
        _handle_plan_import(plan, dry_run, task_id)
        return

    if from_file:
        create_from_file(from_file, dry_run)
        return

    output_error(CREATE_ERROR_HINT)
    raise typer.Exit(1)
