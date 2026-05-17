"""Task creation command implementation.

One verb: `st create <title>` (canonical). Modes:
- bare title           → execution-ready task, auto-enrichment pipeline
- --draft              → kernel only, no auto-enrichment (replaces `st capture`)
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
    execution_mode: str | None,
    manual_only: bool,
    autonomous: bool,
    draft: bool,
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
        data["execution_mode"] = "autonomous"
    # Default: kick the enrichment pipeline so bare titles produce structured plans.
    # --draft leaves it off so the kernel stays as captured.
    if not draft:
        data["auto_dispatch"] = True
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
            second_opinion_suffix = f"|2nd:advisory:{stage}:{status}"
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
    draft: bool,
) -> None:
    if dry_run:
        output_error("--dry-run only works with --from-file or --plan")
        raise typer.Exit(1)

    client = STClient()
    if manual_only and autonomous:
        output_error("--manual-only conflicts with --autonomous")
        raise typer.Exit(1)

    if task_type == "bug":
        create_bug_task(title, description, priority, labels, None, client)
        return

    resolved_labels = labels
    if task_type == "idea":
        resolved_labels = _merge_labels(labels, _IDEA_LABEL)
        autonomous = True

    data = _build_task_data(
        title, task_type, priority, description, resolved_labels, parent,
        execution_mode, manual_only, autonomous, draft,
    )

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
    priority: int,
    labels: str | None,
    task_type: str,
    parent: str | None,
    plan: Path | None,
    blocked_by: str | None,
    execution_mode: str | None,
    manual_only: bool,
    autonomous: bool,
    draft: bool = False,
    task_id: str | None = None,
) -> None:
    """Create a task. Modes: bare title (auto-enrich), --plan, --from-file, --draft.

    Project context auto-detected from cwd; -P overrides.

    Examples:
        st create "fix login redirect bug"          # auto-enriched task
        st create "stash this idea" --draft         # kernel only
        st create "session expires" --type bug      # bug-shaped task
        st create --plan plan.json                  # structured import
        st create --from-file tasks.json            # batch
    """
    if plan:
        _handle_plan_import(plan, dry_run, task_id)
        return

    if from_file:
        create_from_file(from_file, dry_run)
        return

    if not title:
        output_error(
            "st create needs a title (or --plan / --from-file).\n"
            "Resolution: st create \"<short description>\" [--draft] [--type bug|idea]"
        )
        raise typer.Exit(1)

    _handle_single_task_create(
        title, dry_run, description, priority, labels, task_type, parent,
        blocked_by, execution_mode, manual_only, autonomous, draft,
    )
