"""Task creation helpers for routine upkeep signals."""

from __future__ import annotations

from typing import Any

from app.storage import tasks as task_store
from app.storage.connection import get_cursor
from app.storage.task_spirit import approve_plan, create_task_spirit
from app.tasks.autonomous.task_builders import create_single_subtask_with_steps

from .upkeep_constants import (
    DONE_WHEN,
    EXECUTION_MODE_AUTONOMOUS,
    PHASE_BACKEND,
    PHASE_IMPLEMENTATION,
    SUBTASK_ID,
    SUBTASK_TYPE_BUG_FIX,
    SUBTASK_TYPE_IMPLEMENTATION,
    TASK_TYPE_BUG,
    UPKEEP_LABELS,
)
from .upkeep_models import SignalTaskSpec


def task_exists_for_upkeep_source(project_id: str, source_key: str) -> str | None:
    """Return active task ID for upkeep source key, if one exists."""
    with get_cursor() as cur:
        cur.execute(
            """
            SELECT t.id
            FROM tasks t
            JOIN task_spirit ts ON ts.task_id = t.id
            WHERE t.project_id = %s
              AND t.status NOT IN ('completed', 'cancelled')
              AND ts.context -> 'upkeep' ->> 'source_key' = %s
            ORDER BY t.created_at ASC
            LIMIT 1
            """,
            (project_id, source_key),
        )
        row = cur.fetchone()
    return str(row[0]) if row else None


def source_key(signal_type: str, stable_id: object) -> str:
    return f"upkeep:{signal_type}:{stable_id}"


def signal_context(
    source_key_value: str,
    signal_type: str,
    *,
    files_to_modify: list[str] | None,
    source_context: dict[str, Any] | None,
) -> dict[str, Any]:
    context: dict[str, Any] = {"upkeep": {"source_key": source_key_value, "signal_type": signal_type}}
    if source_context:
        context["upkeep"].update(source_context)
    if files_to_modify:
        context["files_to_modify"] = files_to_modify
    return context


def subtask_phase(files_to_modify: list[str] | None) -> str:
    if files_to_modify and any(path.endswith(".py") for path in files_to_modify):
        return PHASE_BACKEND
    return PHASE_IMPLEMENTATION


def create_signal_task(project_id: str, spec: SignalTaskSpec) -> str:
    task = task_store.create_task(
        project_id=project_id,
        title=spec.title,
        description=spec.description,
        priority=spec.priority,
        task_type=spec.task_type,
        complexity=spec.complexity,
        execution_mode=EXECUTION_MODE_AUTONOMOUS,
        autonomous=True,
        labels=[*UPKEEP_LABELS, spec.signal_type],
    )
    task_id = str(task["id"])
    if spec.agent_override:
        task_store.update_task(task_id, agent_override=spec.agent_override)
    create_task_spirit(
        task_id=task_id,
        done_when=DONE_WHEN,
        context=signal_context(
            spec.source_key,
            spec.signal_type,
            files_to_modify=spec.files_to_modify,
            source_context=spec.source_context,
        ),
        complexity=spec.complexity,
    )
    approve_plan(task_id, approved_by="routine-upkeep")
    create_single_subtask_with_steps(
        task_id=task_id,
        subtask_id=SUBTASK_ID,
        phase=subtask_phase(spec.files_to_modify),
        description=spec.subtask_description,
        steps=spec.steps,
        subtask_type=SUBTASK_TYPE_BUG_FIX if spec.task_type == TASK_TYPE_BUG else SUBTASK_TYPE_IMPLEMENTATION,
    )
    return task_id
