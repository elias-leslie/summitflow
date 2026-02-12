"""Task export functionality."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import typer

from ..client import APIError, STClient
from ..output import handle_api_error, output_success


def export_task(
    task_id: str,
    output: str | None,
    client: STClient,
) -> None:
    """Export complete task details to JSON file."""
    task_data = _fetch_task_data(task_id, client)
    export_data = _build_export_structure(task_data)
    _write_export_output(export_data, output)


def _fetch_task_data(
    task_id: str,
    client: STClient,
) -> dict[str, object]:
    """Fetch all task-related data needed for export."""
    try:
        task = client.get_task(task_id)
        subtasks = _fetch_subtasks(task_id, task, client)
        deps = client.list_dependencies(task_id)
        blockers = _fetch_blockers(deps, client)
        progress_log = _parse_progress_log(task)

        return {
            "task": task,
            "subtasks": subtasks,
            "dependencies": deps,
            "blockers": blockers,
            "progress_log": progress_log,
        }
    except APIError as e:
        handle_api_error(e)
        raise typer.Exit(1) from None


def _fetch_subtasks(
    task_id: str,
    task: dict[str, object],
    client: STClient,
) -> list[dict[str, object]]:
    """Fetch subtasks, handling cross-project scenarios."""
    task_project_id = task.get("project_id")
    if task_project_id and client.project_id != task_project_id:
        client = STClient(project_id=str(task_project_id), require_project=False)
    subtask_data = client.get_subtasks(task_id, include_steps=True)
    return list(subtask_data.get("subtasks", []))


def _fetch_blockers(
    deps: list[dict[str, object]],
    client: STClient,
) -> list[dict[str, object]]:
    """Fetch blocker tasks from dependencies."""
    blockers: list[dict[str, object]] = []
    for dep in deps:
        if dep.get("dependency_type") != "blocks":
            continue
        if dep.get("depends_on_status") in ("completed", "cancelled"):
            continue

        blocker_id = dep.get("depends_on_task_id")
        if not blocker_id:
            continue

        try:
            blockers.append(client.get_task(str(blocker_id)))
        except APIError:
            blockers.append({"id": blocker_id, "status": "unknown", "title": "?"})

    return blockers


def _parse_progress_log(task: dict[str, object]) -> list[str]:
    """Parse progress log from task data."""
    raw = task.get("progress_log") or ""
    if not isinstance(raw, str):
        return []
    return [line.strip() for line in raw.split("\n") if line.strip()]


def _build_export_structure(task_data: dict[str, object]) -> dict[str, object]:
    """Build the complete export data structure."""
    task = task_data["task"]
    if not isinstance(task, dict):
        task = {}

    return {
        "exported_at": datetime.now(UTC).isoformat(),
        "task": {
            "id": task.get("id"), "title": task.get("title"),
            "description": task.get("description"), "status": task.get("status"),
            "priority": task.get("priority"), "task_type": task.get("task_type"),
            "complexity": task.get("complexity"), "project_id": task.get("project_id"),
            "objective": task.get("objective"), "spirit_anti": task.get("spirit_anti"),
            "done_when": task.get("done_when") or [],
            "constraints": task.get("constraints") or [],
            "decisions": task.get("decisions") or [],
            "risks": task.get("risks") or [],
            "files_to_create": task.get("files_to_create") or [],
            "files_to_modify": task.get("files_to_modify") or [],
            "context": task.get("context") or {},
            "branch": task.get("branch"), "pr_url": task.get("pr_url"),
            "created_at": task.get("created_at"),
            "updated_at": task.get("updated_at"),
        },
        "subtasks": task_data["subtasks"],
        "acceptance_criteria": [],
        "dependencies": task_data["dependencies"],
        "blockers": task_data["blockers"],
        "progress_log": task_data["progress_log"],
    }


def _write_export_output(
    export_data: dict[str, object],
    output: str | None,
) -> None:
    """Write export data to file or stdout."""
    json_str = json.dumps(export_data, indent=2, default=str)
    if output:
        Path(output).write_text(json_str)
        output_success(f"Exported to {output}")
    else:
        print(json_str)
