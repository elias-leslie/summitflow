"""Additional task command implementations."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import typer

from ..client import APIError, STClient
from ..output import (
    handle_api_error,
    output_error,
    output_json,
    output_success,
    output_task,
)


def export_task(
    task_id: str,
    output: str | None,
    client: STClient,
) -> None:
    """Export complete task details to JSON file."""
    try:
        # Fetch task with full details
        task = client.get_task(task_id)

        # Fetch subtasks with steps
        task_project_id = task.get("project_id")
        if task_project_id and client.project_id != task_project_id:
            subtask_client = STClient(project_id=task_project_id, require_project=False)
            subtask_data = subtask_client.get_subtasks(task_id, include_steps=True)
        else:
            subtask_data = client.get_subtasks(task_id, include_steps=True)

        subtasks = subtask_data.get("subtasks", [])
        criteria: list[dict[str, Any]] = []

        # Fetch dependencies
        deps = client.list_dependencies(task_id)

        # Fetch blockers
        blockers = []
        for d in deps:
            if d.get("dependency_type") == "blocks" and d.get("depends_on_status") not in (
                "completed",
                "cancelled",
            ):
                blocker_id = d.get("depends_on_task_id")
                if blocker_id:
                    try:
                        blocker_task = client.get_task(blocker_id)
                        blockers.append(blocker_task)
                    except APIError:
                        blockers.append({"id": blocker_id, "status": "unknown", "title": "?"})

        # Progress log
        progress_log_raw = task.get("progress_log") or ""
        progress_log = [line.strip() for line in progress_log_raw.split("\n") if line.strip()]

    except APIError as e:
        handle_api_error(e)
        raise typer.Exit(1) from None

    # Build complete export structure
    export_data = {
        "exported_at": datetime.now(UTC).isoformat(),
        "task": {
            "id": task.get("id"),
            "title": task.get("title"),
            "description": task.get("description"),
            "status": task.get("status"),
            "priority": task.get("priority"),
            "task_type": task.get("task_type"),
            "complexity": task.get("complexity"),
            "project_id": task.get("project_id"),
            "objective": task.get("objective"),
            "spirit_anti": task.get("spirit_anti"),
            "done_when": task.get("done_when") or [],
            "constraints": task.get("constraints") or [],
            "decisions": task.get("decisions") or [],
            "risks": task.get("risks") or [],
            "files_to_create": task.get("files_to_create") or [],
            "files_to_modify": task.get("files_to_modify") or [],
            "context": task.get("context") or {},
            "branch": task.get("branch"),
            "pr_url": task.get("pr_url"),
            "created_at": task.get("created_at"),
            "updated_at": task.get("updated_at"),
        },
        "subtasks": subtasks,
        "acceptance_criteria": criteria,
        "dependencies": deps,
        "blockers": blockers,
        "progress_log": progress_log,
    }

    # Output
    json_str = json.dumps(export_data, indent=2, default=str)

    if output:
        output_path = Path(output)
        output_path.write_text(json_str)
        output_success(f"Exported to {output_path}")
    else:
        print(json_str)


def autocode_task(
    task_id: str,
    dry_run: bool,
    at: str | None,
    client: STClient,
) -> None:
    """Queue task for autonomous execution via Hatchet."""
    from app.scheduling.types import OnceSchedule, parse_at_time

    try:
        task = client.get_task(task_id)
    except APIError as e:
        handle_api_error(e)
        raise typer.Exit(1) from None

    task_project_id = task.get("project_id", "summitflow")
    if task_project_id != client.project_id:
        client = STClient(project_id=task_project_id, require_project=False)

    try:
        subtasks_response = client.get_subtasks(task_id)
        subtasks = subtasks_response.get("subtasks", [])
    except APIError as e:
        handle_api_error(e)
        raise typer.Exit(1) from None

    if not subtasks:
        output_error(f"Task {task_id} has no subtasks. Use 'st autocode' to generate a plan.")
        raise typer.Exit(1)

    current_status = task.get("status", "pending")
    if current_status in ("running", "queue"):
        output_error(f"Task {task_id} is already {current_status}.")
        raise typer.Exit(1)
    if current_status in ("completed", "merged", "pr_created"):
        output_error(f"Task {task_id} is already {current_status}.")
        raise typer.Exit(1)

    schedule = None
    if at:
        try:
            scheduled_time = parse_at_time(at)
            schedule = OnceSchedule(timestamp=scheduled_time)
        except ValueError as e:
            output_error(f"Invalid --at value: {e}")
            raise typer.Exit(1) from None

    if dry_run:
        incomplete = [s for s in subtasks if not s.get("passes")]
        result = {
            "task_id": task_id,
            "status": "dry_run",
            "subtasks_total": len(subtasks),
            "subtasks_incomplete": len(incomplete),
            "next_subtask": incomplete[0]["subtask_id"] if incomplete else None,
            "message": f"Would queue {task_id} for autonomous execution",
        }
        if schedule:
            result["scheduled_for"] = schedule.timestamp.isoformat()
        output_json(result)
        return

    try:
        client.update_status(task_id, status="queue")
    except APIError as e:
        handle_api_error(e)
        raise typer.Exit(1) from None

    if schedule:
        output_json(
            {
                "task_id": task_id,
                "status": "scheduled",
                "scheduled_for": schedule.timestamp.isoformat(),
                "message": f"Task scheduled for {schedule.timestamp.strftime('%Y-%m-%d %H:%M UTC')}",
            }
        )
    else:
        output_json(
            {
                "task_id": task_id,
                "status": "queued",
                "dispatch": "immediate",
                "message": f"Task queued for immediate execution. Monitor via: st context {task_id}",
            }
        )


def create_bug_task(
    title: str,
    description: str | None,
    priority: int,
    labels: str | None,
    from_task: str | None,
    client: STClient,
) -> None:
    """Create a bug task with optional parent task inheritance."""
    # If --from specified, fetch parent to inherit domains
    inherited_labels: list[str] = []
    if from_task:
        try:
            parent = client.get_task(from_task)
            parent_labels = parent.get("labels", [])
            for label in parent_labels:
                if label.startswith("domains:"):
                    inherited_labels.append(label)
        except APIError:
            pass

    # Build labels list
    all_labels: list[str] = []
    if labels:
        all_labels.extend(labels.split(","))
    for label in inherited_labels:
        if label not in all_labels:
            all_labels.append(label)

    data: dict[str, Any] = {
        "title": title,
        "task_type": "bug",
        "priority": priority,
    }
    if description:
        data["description"] = description
    if all_labels:
        data["labels"] = all_labels

    try:
        task = client.create_task(data)
    except APIError as e:
        handle_api_error(e)
        raise typer.Exit(1) from None

    # Create discovered-from dependency if --from specified
    if from_task:
        try:
            client.add_dependency(task["id"], from_task, dep_type="discovered-from")
            task["linked_from"] = from_task
        except APIError as e:
            task["dependency_error"] = e.detail

    output_task(task)


def append_task_log(
    message: str,
    task_id: str,
    client: STClient,
) -> None:
    """Append a log entry to a task's progress log."""
    timestamp = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    entry = f"[{timestamp}] {message}"

    try:
        result = client.append_log(task_id, entry)
    except APIError as e:
        handle_api_error(e)
        raise typer.Exit(1) from None

    output_json(result)
