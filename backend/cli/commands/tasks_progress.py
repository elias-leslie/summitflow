"""Task progress sync helpers for plan-backed tasks."""

from __future__ import annotations

from dataclasses import dataclass

import typer

from ..client import APIError, STClient
from ..output import handle_api_error, output_success
from .subtask_validation import is_step_resolved


def _incomplete_step_numbers(steps: list[dict[str, object]]) -> list[int]:
    step_passes = {int(step["step_number"]): bool(step.get("passes", False)) for step in steps}
    return [
        int(step["step_number"])
        for step in steps
        if not is_step_resolved(step, step_passes)
    ]


def _subtask_steps(subtask: dict[str, object]) -> list[dict[str, object]]:
    steps = subtask.get("steps_from_table")
    if isinstance(steps, list):
        return steps
    steps = subtask.get("steps")
    if isinstance(steps, list):
        return steps
    return []


def _uses_plan_context_steps(subtask: dict[str, object]) -> bool:
    return subtask.get("steps_source") == "plan_context"


@dataclass
class SyncAnalysis:
    synced: list[str]
    syncable: list[str]
    skipped: list[str]


def analyze_subtask_sync(subtasks: list[dict[str, object]]) -> SyncAnalysis:
    """Classify subtasks into syncable and skipped buckets."""
    syncable: list[str] = []
    skipped: list[str] = []

    for subtask in subtasks:
        subtask_id = str(subtask.get("subtask_id", ""))
        if not subtask_id or subtask.get("passes"):
            continue

        steps = _subtask_steps(subtask)
        if not steps:
            skipped.append(f"{subtask_id}:no-steps")
            continue
        if _uses_plan_context_steps(subtask):
            citations_acknowledged = bool(subtask.get("citations_acknowledged_at"))
            if not citations_acknowledged:
                skipped.append(f"{subtask_id}:citations")
                continue
            syncable.append(subtask_id)
            continue

        incomplete = _incomplete_step_numbers(steps)
        if incomplete:
            skipped.append(f"{subtask_id}:steps-{','.join(str(step) for step in incomplete)}")
            continue

        citations_acknowledged = bool(subtask.get("citations_acknowledged_at"))
        if not citations_acknowledged:
            skipped.append(f"{subtask_id}:citations")
            continue

        syncable.append(subtask_id)

    return SyncAnalysis(synced=[], syncable=syncable, skipped=skipped)


def sync_completed_subtasks(
    client: STClient,
    task_id: str,
    subtasks: list[dict[str, object]],
    acknowledge_none: bool,
) -> SyncAnalysis:
    """Mark syncable subtasks passed, optionally acknowledging missing citations."""
    analysis = SyncAnalysis(synced=[], syncable=[], skipped=[])

    for subtask in subtasks:
        subtask_id = str(subtask.get("subtask_id", ""))
        if not subtask_id or subtask.get("passes"):
            continue

        steps = _subtask_steps(subtask)
        if not steps:
            analysis.skipped.append(f"{subtask_id}:no-steps")
            continue
        if _uses_plan_context_steps(subtask):
            citations_acknowledged = bool(subtask.get("citations_acknowledged_at"))
            if not citations_acknowledged:
                if not acknowledge_none:
                    analysis.skipped.append(f"{subtask_id}:citations")
                    continue
                try:
                    client.acknowledge_no_citations(task_id, subtask_id)
                except APIError as e:
                    handle_api_error(e)
                    raise typer.Exit(1) from None
                subtask["citations_acknowledged_at"] = True
            try:
                client.update_subtask(task_id, subtask_id, passes=True)
            except APIError as e:
                handle_api_error(e)
                raise typer.Exit(1) from None
            subtask["passes"] = True
            analysis.synced.append(subtask_id)
            continue

        incomplete = _incomplete_step_numbers(steps)
        if incomplete:
            analysis.skipped.append(f"{subtask_id}:steps-{','.join(str(step) for step in incomplete)}")
            continue

        citations_acknowledged = bool(subtask.get("citations_acknowledged_at"))
        if not citations_acknowledged:
            if not acknowledge_none:
                analysis.skipped.append(f"{subtask_id}:citations")
                continue
            try:
                client.acknowledge_no_citations(task_id, subtask_id)
            except APIError as e:
                handle_api_error(e)
                raise typer.Exit(1) from None
            subtask["citations_acknowledged_at"] = True

        try:
            client.update_subtask(task_id, subtask_id, passes=True)
        except APIError as e:
            handle_api_error(e)
            raise typer.Exit(1) from None
        subtask["passes"] = True
        analysis.synced.append(subtask_id)

    remaining_analysis = analyze_subtask_sync(subtasks)
    analysis.syncable = remaining_analysis.syncable
    analysis.skipped = remaining_analysis.skipped
    return analysis


def sync_progress_command(
    task_id: str | None,
    acknowledge_none: bool,
) -> None:
    """Mark objectively complete subtasks as passed."""
    from ..context import require_task_id

    task_id = require_task_id(task_id)
    client = STClient(require_project=False)

    try:
        result = client.get_subtasks(task_id, include_steps=True)
    except APIError as e:
        handle_api_error(e)
        return

    analysis = sync_completed_subtasks(
        client,
        task_id,
        result.get("subtasks", []),
        acknowledge_none,
    )

    if analysis.synced:
        output_success(f"Synchronized subtasks: {', '.join(analysis.synced)}")
    if analysis.skipped:
        typer.echo(f"SKIP {' | '.join(analysis.skipped)}")
    if not analysis.synced and not analysis.skipped:
        typer.echo("No incomplete subtasks needed syncing.")
