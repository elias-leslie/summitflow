"""Database storage operations for autonomous planning."""

from __future__ import annotations

from typing import Any

from ...logging_config import get_logger
from ...services.task_execution_readiness import sync_task_execution_readiness
from ...services.task_plan_context import build_task_plan_context
from ...services.task_planning_signature import build_task_planning_signature
from ...services.task_second_opinion import ensure_second_opinion_tracking
from ...storage import tasks as task_store
from ...storage.subtasks import bulk_add_subtask_dependencies, bulk_create_subtasks
from ...storage.task_spirit import create_task_spirit, get_task_spirit, update_task_spirit

logger = get_logger(__name__)


def _format_step(step: Any) -> dict[str, Any]:
    """Format a single step into a dict with a description field."""
    if isinstance(step, dict):
        formatted: dict[str, Any] = {"description": step.get("description", "")}
        spec = step.get("spec")
        if isinstance(spec, dict) and spec:
            formatted["spec"] = spec
        return formatted
    return {"description": str(step)}


def _format_subtask(st: dict[str, Any], index: int) -> dict[str, Any]:
    """Format a single subtask entry for bulk creation."""
    steps = st.get("steps", [])
    formatted_steps = [_format_step(step) for step in steps]
    return {
        "subtask_id": st.get("subtask_id", f"{index}.1"),
        "phase": st.get("phase"),
        "subtask_type": st.get("subtask_type"),
        "description": st.get("description", ""),
        "steps": formatted_steps,
    }


def _collect_dependencies(subtasks_data: list[dict[str, Any]]) -> list[tuple[str, str]]:
    """Collect all subtask dependency pairs from plan data."""
    deps: list[tuple[str, str]] = []
    for st in subtasks_data:
        sid = st.get("subtask_id", "")
        for dep in st.get("depends_on", []):
            if dep and sid:
                deps.append((sid, dep))
    return deps


def _merge_unique_strings(
    existing: list[Any] | None,
    incoming: list[Any] | None,
) -> list[str]:
    merged: list[str] = []
    seen: set[str] = set()
    for source in [*(existing or []), *(incoming or [])]:
        text = str(source).strip()
        if not text or text in seen:
            continue
        seen.add(text)
        merged.append(text)
    return merged


def _merge_context(
    existing: dict[str, Any] | None,
    incoming: dict[str, Any] | None,
) -> dict[str, Any]:
    merged = dict(existing or {})
    for key, value in (incoming or {}).items():
        if key in {"files_to_modify", "files_to_create", "risks"}:
            existing_items = merged.get(key) if isinstance(merged.get(key), list) else []
            incoming_items = value if isinstance(value, list) else []
            merged[key] = _merge_unique_strings(existing_items, incoming_items)
            continue
        merged[key] = value
    return merged


def _upsert_task_spirit(task_id: str, plan_data: dict[str, Any], task: dict[str, Any] | None) -> None:
    """Create or update the task spirit record."""
    done_when = _merge_unique_strings(None, plan_data.get("done_when", []))
    context = build_task_plan_context(plan_data)
    planning_signature = build_task_planning_signature(task)
    if planning_signature:
        context["planning_signature"] = planning_signature
    complexity = str(plan_data.get("complexity", "")).strip() or None
    spirit = get_task_spirit(task_id)
    if not spirit:
        create_task_spirit(
            task_id=task_id,
            done_when=done_when,
            context=context,
            complexity=complexity,
        )
    else:
        updates: dict[str, Any] = {
            "done_when": _merge_unique_strings(spirit.get("done_when"), done_when),
            "context": _merge_context(
                spirit.get("context") if isinstance(spirit.get("context"), dict) else {},
                context,
            ),
        }
        if complexity and not spirit.get("complexity"):
            updates["complexity"] = complexity
        update_task_spirit(task_id, **updates)


def _create_subtasks_from_plan(
    task_id: str, subtasks_data: list[dict[str, Any]]
) -> None:
    """Create subtasks and their dependencies from plan data."""
    formatted_subtasks = [
        _format_subtask(st, i + 1) for i, st in enumerate(subtasks_data)
    ]
    bulk_create_subtasks(task_id, formatted_subtasks)
    logger.info("Created subtasks from plan", task_id=task_id, count=len(formatted_subtasks))

    deps = _collect_dependencies(subtasks_data)
    if not deps:
        return
    try:
        bulk_add_subtask_dependencies(task_id, deps)
        logger.info("Created subtask dependencies", task_id=task_id, count=len(deps))
    except Exception as e:
        logger.warning("Failed to create dependencies", task_id=task_id, error=str(e))


def save_plan_to_database(task_id: str, plan_data: dict[str, Any]) -> None:
    """Save parsed plan to database using existing storage functions.

    Args:
        task_id: Task ID to save plan for
        plan_data: Parsed plan with objective, subtasks, and constraints
    """
    subtasks_data = plan_data.get("subtasks", [])
    task = task_store.get_task(task_id)
    _upsert_task_spirit(task_id, plan_data, task)

    if subtasks_data:
        _create_subtasks_from_plan(task_id, subtasks_data)

    if task:
        ensure_second_opinion_tracking(task_id, task, source="planning")
        sync_task_execution_readiness(task_id, "planning")
