"""Task progress sync helpers for objectively verifiable subtasks."""

from __future__ import annotations

from dataclasses import dataclass

import typer

from app.storage._subtask_dep_helpers import CycleError, build_graph, kahn_sort

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
    steps_from_table = subtask.get("steps_from_table")
    if isinstance(steps_from_table, list) and steps_from_table:
        return steps_from_table
    steps = subtask.get("steps")
    if isinstance(steps, list):
        return steps
    if isinstance(steps_from_table, list):
        return steps_from_table
    return []


def _uses_plan_context_steps(subtask: dict[str, object]) -> bool:
    return subtask.get("steps_source") == "plan_context"


@dataclass
class SyncAnalysis:
    synced: list[str]
    syncable: list[str]
    skipped: list[str]


def _plan_context_skip_reason(subtask_id: str) -> str:
    return f"{subtask_id}:plan-context"


def _dependency_ordered_subtasks(
    task_id: str,
    subtasks: list[dict[str, object]],
) -> list[dict[str, object]]:
    """Return subtasks using the canonical dependency-order algorithm."""
    ordered_ids = [
        str(subtask.get("subtask_id", ""))
        for subtask in subtasks
        if subtask.get("subtask_id")
    ]
    if not ordered_ids:
        return subtasks

    dependency_pairs: list[tuple[str, str]] = []
    for subtask in subtasks:
        subtask_id = str(subtask.get("subtask_id", ""))
        raw_dependencies = subtask.get("depends_on")
        if not subtask_id or not isinstance(raw_dependencies, list):
            continue
        dependency_pairs.extend(
            (subtask_id, str(dependency))
            for dependency in raw_dependencies
            if str(dependency) in ordered_ids
        )

    try:
        in_degree, dependents = build_graph(ordered_ids, dependency_pairs)
        topo_ids = kahn_sort(ordered_ids, in_degree, dependents, task_id)
    except CycleError:
        return subtasks

    positions = {subtask_id: index for index, subtask_id in enumerate(topo_ids)}
    return sorted(
        subtasks,
        key=lambda subtask: positions.get(str(subtask.get("subtask_id", "")), len(topo_ids)),
    )


def analyze_subtask_sync(subtasks: list[dict[str, object]]) -> SyncAnalysis:
    """Classify subtasks into syncable and skipped buckets."""
    syncable: list[str] = []
    skipped: list[str] = []

    for subtask in subtasks:
        subtask_id = str(subtask.get("subtask_id", ""))
        if not subtask_id or subtask.get("passes"):
            continue

        if _uses_plan_context_steps(subtask):
            skipped.append(_plan_context_skip_reason(subtask_id))
            continue

        steps = _subtask_steps(subtask)
        if not steps:
            skipped.append(f"{subtask_id}:no-steps")
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


def _ensure_citations_acknowledged(
    client: STClient,
    task_id: str,
    subtask_id: str,
    subtask: dict[str, object],
    acknowledge_none: bool,
) -> bool:
    """Acknowledge missing citations if requested; return True if acknowledged or already set."""
    if bool(subtask.get("citations_acknowledged_at")):
        return True
    if not acknowledge_none:
        return False
    try:
        client.acknowledge_no_citations(task_id, subtask_id)
    except APIError as e:
        handle_api_error(e)
        raise typer.Exit(1) from None
    subtask["citations_acknowledged_at"] = True
    return True


def _mark_subtask_passed(
    client: STClient,
    task_id: str,
    subtask_id: str,
    subtask: dict[str, object],
    analysis: SyncAnalysis,
) -> None:
    """Call the API to mark a subtask passed and record it in the analysis."""
    try:
        client.update_subtask(task_id, subtask_id, passes=True)
    except APIError as e:
        handle_api_error(e)
        raise typer.Exit(1) from None
    subtask["passes"] = True
    analysis.synced.append(subtask_id)


def _sync_regular_subtask(
    client: STClient,
    task_id: str,
    subtask_id: str,
    subtask: dict[str, object],
    steps: list[dict[str, object]],
    acknowledge_none: bool,
    analysis: SyncAnalysis,
) -> None:
    """Sync a regular subtask, checking step completion and citations."""
    incomplete = _incomplete_step_numbers(steps)
    if incomplete:
        analysis.skipped.append(f"{subtask_id}:steps-{','.join(str(s) for s in incomplete)}")
        return

    acknowledged = _ensure_citations_acknowledged(
        client, task_id, subtask_id, subtask, acknowledge_none
    )
    if not acknowledged:
        analysis.skipped.append(f"{subtask_id}:citations")
        return

    _mark_subtask_passed(client, task_id, subtask_id, subtask, analysis)


def sync_completed_subtasks(
    client: STClient,
    task_id: str,
    subtasks: list[dict[str, object]],
    acknowledge_none: bool,
) -> SyncAnalysis:
    """Mark syncable subtasks passed, optionally acknowledging missing citations."""
    analysis = SyncAnalysis(synced=[], syncable=[], skipped=[])

    for subtask in _dependency_ordered_subtasks(task_id, subtasks):
        subtask_id = str(subtask.get("subtask_id", ""))
        if not subtask_id or subtask.get("passes"):
            continue

        if _uses_plan_context_steps(subtask):
            analysis.skipped.append(_plan_context_skip_reason(subtask_id))
            continue

        steps = _subtask_steps(subtask)
        if not steps:
            analysis.skipped.append(f"{subtask_id}:no-steps")
            continue

        _sync_regular_subtask(
            client, task_id, subtask_id, subtask, steps, acknowledge_none, analysis
        )

    remaining = analyze_subtask_sync(subtasks)
    analysis.syncable = remaining.syncable
    analysis.skipped = remaining.skipped
    return analysis


def sync_progress_command(
    task_id: str | None,
    acknowledge_none: bool,
) -> None:
    """Mark objectively complete, step-backed subtasks as passed."""
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
