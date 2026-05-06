"""Bug task creation functionality."""

from __future__ import annotations

from typing import Any

import typer

from ..client import APIError, STClient
from ..output import handle_api_error, output_task

_BUG_DONE_WHEN = [
    "Bug is reproduced or existing failure evidence is confirmed.",
    "Root cause is fixed with the smallest scoped code change.",
    "Original symptom no longer reproduces and relevant st check gates pass.",
]
_BUG_SUBTASK_STEPS: list[str | dict[str, Any]] = [
    "Confirm reproduction or recorded failure evidence.",
    "Implement the smallest root-cause fix.",
    "Verify the original symptom and run st check --quick --changed-only.",
]


def create_bug_task(
    title: str,
    description: str | None,
    priority: int,
    labels: str | None,
    from_task: str | None,
    client: STClient,
) -> None:
    """Create a bug task with optional parent task inheritance."""
    inherited_labels = _fetch_inherited_labels(from_task, client)
    all_labels = _build_labels_list(labels, inherited_labels)
    task_data = _build_bug_task_data(title, description, priority, all_labels)

    task = _create_task(task_data, client)
    task = _add_bug_fix_subtask(task, client)
    task = _add_discovered_from_link(task, from_task, client)

    output_task(task)


def _fetch_inherited_labels(
    from_task: str | None,
    client: STClient,
) -> list[str]:
    """Fetch domain labels from parent task if specified."""
    if not from_task:
        return []

    try:
        parent = client.get_task(from_task)
        parent_labels = parent.get("labels", [])
        if not isinstance(parent_labels, list):
            return []

        return [
            label
            for label in parent_labels
            if isinstance(label, str) and label.startswith("domains:")
        ]
    except APIError:
        return []


def _build_labels_list(
    labels: str | None,
    inherited_labels: list[str],
) -> list[str]:
    """Build combined labels list from user input and inherited labels."""
    all_labels: list[str] = []

    if labels:
        all_labels.extend(labels.split(","))

    for label in inherited_labels:
        if label not in all_labels:
            all_labels.append(label)

    return all_labels


def _build_bug_task_data(
    title: str,
    description: str | None,
    priority: int,
    labels: list[str],
) -> dict[str, object]:
    """Build task creation data dictionary."""
    data: dict[str, object] = {
        "title": title,
        "description": description or title,
        "task_type": "bug",
        "priority": priority,
        "execution_mode": "autonomous",
        "autonomous": True,
        "done_when": _BUG_DONE_WHEN,
    }

    if labels:
        data["labels"] = labels

    return data


def _create_task(
    data: dict[str, object],
    client: STClient,
) -> dict[str, object]:
    """Create the bug task via API."""
    try:
        return client.create_task(data)
    except APIError as e:
        handle_api_error(e)
        raise typer.Exit(1) from None


def _add_bug_fix_subtask(task: dict[str, object], client: STClient) -> dict[str, object]:
    """Attach one focused bug-fix subtask to manual bug captures."""
    task_id = task.get("id")
    if not isinstance(task_id, str):
        return task
    try:
        client.create_subtask(
            task_id=task_id,
            subtask_id="1.1",
            description="Reproduce, fix, and verify bug.",
            phase="debugging",
            steps=_BUG_SUBTASK_STEPS,
            subtask_type="bug-fix",
        )
        task["subtasks_created"] = 1
    except APIError as e:
        task["subtask_error"] = e.detail
    return task


def _add_discovered_from_link(
    task: dict[str, object],
    from_task: str | None,
    client: STClient,
) -> dict[str, object]:
    """Add discovered-from dependency if --from specified."""
    if not from_task:
        return task

    task_id = task.get("id")
    if not isinstance(task_id, str):
        return task

    try:
        client.add_dependency(task_id, from_task, dep_type="discovered-from")
        task["linked_from"] = from_task
    except APIError as e:
        task["dependency_error"] = e.detail

    return task
