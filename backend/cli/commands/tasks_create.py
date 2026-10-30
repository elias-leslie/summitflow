"""Task creation command implementation.

One verb: `st create <title>` (canonical). Modes:
- bare title           → pending task with the title and optional description
- --type bug|idea|...  → typed kernel (replaces hidden `st bug` / `st idea`)
- --plan plan.json     → skip enrichment, import a structured plan
- --from-file file.json → batch
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import typer

from ..client import APIError, STClient
from ..output import handle_api_error, output_error, output_task
from .tasks_bug import create_bug_task
from .tasks_import import create_from_file, import_plan_file

_DEFAULT_TASK_TYPE = "task"
_DEFAULT_PRIORITY = 2
_IDEA_LABEL = "crowdsourced"


def _merge_labels(labels: str | None, extra: str) -> str:
    items: list[str] = []
    for raw in (labels or "").split(","):
        cleaned = raw.strip()
        if cleaned and cleaned not in items:
            items.append(cleaned)
    if extra not in items:
        items.append(extra)
    return ",".join(items)


def _build_task_data(
    title: str,
    task_type: str,
    priority: int,
    description: str | None,
    labels: str | None,
    parent: str | None,
) -> dict[str, Any]:
    data: dict[str, Any] = {"title": title, "task_type": task_type, "priority": priority}
    if description:
        data["description"] = description
    if labels:
        data["labels"] = labels.split(",")
    if parent:
        data["parent_task_id"] = parent
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
    plan: Path, dry_run: bool, task_id: str | None,
    overrides: dict[str, Any], labels: str | None,
    parent: str | None, blocked_by: str | None,
) -> None:
    client = STClient()
    task, tid = import_plan_file(
        plan, dry_run, task_id, client,
        overrides=overrides, labels=labels.split(",") if labels else None, parent=parent,
    )
    if blocked_by:
        task = _apply_blocked_by(client, task, blocked_by)
        if "dependency_error" in task:
            output_error(f"Imported {tid}, but --blocked-by {blocked_by} failed: {task['dependency_error']}")
            raise typer.Exit(1)
    if not dry_run:
        complexity = task.get("complexity", "SIMPLE")
        subtask_count = len(task.get("subtasks") or [])
        suffix = "intent-only" if subtask_count == 0 else f"{subtask_count} subtasks"
        second_opinion = ((task.get("context") or {}).get("second_opinion") or {})
        second_opinion_suffix = ""
        if isinstance(second_opinion, dict) and second_opinion.get("required"):
            stage = second_opinion.get("stage", "task_shape")
            status = second_opinion.get("status", "pending")
            second_opinion_suffix = f"|2nd:advisory:{stage}:{status}"
        blocked_suffix = f"|blocked-by:{blocked_by}" if blocked_by else ""
        typer.echo(f"IMPORT:{tid}|{complexity}|{suffix}{second_opinion_suffix}{blocked_suffix}")


def _handle_single_task_create(
    title: str,
    dry_run: bool,
    description: str | None,
    priority: int,
    labels: str | None,
    task_type: str,
    parent: str | None,
    blocked_by: str | None,
) -> None:
    if dry_run:
        output_error("--dry-run only works with --from-file or --plan")
        raise typer.Exit(1)

    client = STClient()

    if task_type == "bug":
        create_bug_task(title, description, priority, labels, None, client)
        return

    resolved_labels = labels
    if task_type == "idea":
        resolved_labels = _merge_labels(labels, _IDEA_LABEL)

    data = _build_task_data(title, task_type, priority, description, resolved_labels, parent)

    try:
        task = client.create_task(data)
    except APIError as e:
        handle_api_error(e)
        return

    if blocked_by:
        task = _apply_blocked_by(client, task, blocked_by)

    output_task(task)


def create_task_command(
    title: str | None,
    from_file: Path | None,
    dry_run: bool,
    description: str | None,
    priority: int | None,
    labels: str | None,
    task_type: str | None,
    parent: str | None,
    plan: Path | None,
    blocked_by: str | None,
    task_id: str | None = None,
) -> None:
    """Create a task. Modes: bare title (pending task), --plan, --from-file.

    Project context auto-detected from cwd; -P overrides.

    Examples:
        st create "fix login redirect bug"          # pending task
        st create "session expires" --type bug      # bug-shaped task
        st create --plan plan.json                  # structured import
        st create --from-file tasks.json            # batch
    """
    if plan:
        overrides = {"title": title, "description": description, "priority": priority, "task_type": task_type}
        _handle_plan_import(
            plan, dry_run, task_id,
            {k: v for k, v in overrides.items() if v is not None}, labels, parent, blocked_by,
        )
        return

    if from_file:
        create_from_file(from_file, dry_run)
        return

    if not title:
        output_error(
            "st create needs a title (or --plan / --from-file).\n"
            "Resolution: st create \"<short description>\" [-d details] [--type bug|idea]"
        )
        raise typer.Exit(1)

    _handle_single_task_create(
        title, dry_run, description,
        _DEFAULT_PRIORITY if priority is None else priority,
        labels, task_type or _DEFAULT_TASK_TYPE, parent, blocked_by,
    )
