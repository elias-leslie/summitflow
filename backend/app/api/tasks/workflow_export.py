"""Workflow export utilities.

Build complete export data for plan.json round-trip.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from ...services.task_plan_context import extract_task_plan_fields, hydrate_task_plan_fields
from ...storage import task_dependencies as dep_store
from ...storage.events import get_events_by_trace
from ...storage.subtasks import get_subtask_dependencies


def _build_acceptance_criteria(spirit: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not spirit or not spirit.get("done_when"):
        return []
    return [
        {"id": f"ac-{i}", "criterion": dw, "verified": False}
        for i, dw in enumerate(spirit["done_when"], 1)
    ]


def _format_datetime(value: Any) -> str | None:
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def _hydrate_export_task(
    task: dict[str, Any],
    spirit: dict[str, Any] | None,
) -> dict[str, Any]:
    merged = dict(task)
    if spirit:
        merged["done_when"] = spirit.get("done_when") or merged.get("done_when") or []
        merged["context"] = spirit.get("context") or {}
        merged["plan_status"] = spirit.get("plan_status") or merged.get("plan_status") or "draft"
        merged["plan_approved_at"] = spirit.get("plan_approved_at")
        merged["plan_approved_by"] = spirit.get("plan_approved_by")
        if spirit.get("complexity") and not merged.get("complexity"):
            merged["complexity"] = spirit.get("complexity")
    else:
        merged["done_when"] = merged.get("done_when") or []
        merged["context"] = merged.get("context") or {}
        merged["plan_status"] = merged.get("plan_status") or "draft"
    return hydrate_task_plan_fields(merged)


def _build_task_payload(task: dict[str, Any], spirit: dict[str, Any] | None) -> dict[str, Any]:
    hydrated = _hydrate_export_task(task, spirit)
    plan_fields = extract_task_plan_fields(hydrated)
    return {
        "id": hydrated["id"],
        "project_id": hydrated["project_id"],
        "title": hydrated["title"],
        "description": hydrated.get("description"),
        "status": hydrated["status"],
        "priority": hydrated.get("priority", 2),
        "task_type": hydrated.get("task_type", "task"),
        "complexity": hydrated.get("complexity"),
        "plan_status": hydrated.get("plan_status") or "draft",
        "plan_approved_at": hydrated.get("plan_approved_at"),
        "plan_approved_by": hydrated.get("plan_approved_by"),
        "done_when": hydrated.get("done_when") or [],
        **plan_fields,
        "context": hydrated.get("context") or {},
        "branch_name": hydrated.get("branch_name"),
        "created_at": _format_datetime(hydrated.get("created_at")),
        "updated_at": _format_datetime(hydrated.get("updated_at")),
    }


def _build_spirit_payload(task: dict[str, Any], spirit: dict[str, Any] | None) -> dict[str, Any] | None:
    hydrated = _hydrate_export_task(task, spirit)
    plan_fields = extract_task_plan_fields(hydrated)
    if not any(
        hydrated.get(field) not in (None, "", [], {})
        for field in (
            "done_when",
            "context",
            *tuple(plan_fields.keys()),
        )
    ):
        return None
    return {
        "done_when": hydrated.get("done_when") or [],
        **plan_fields,
        "context": hydrated.get("context") or {},
        "complexity": hydrated.get("complexity"),
        "plan_status": hydrated.get("plan_status") or "draft",
        "plan_approved_at": hydrated.get("plan_approved_at"),
        "plan_approved_by": hydrated.get("plan_approved_by"),
    }


def _build_subtask_steps(subtask: dict[str, Any]) -> list[dict[str, Any]]:
    steps = subtask.get("steps") or subtask.get("steps_from_table") or []
    normalized: list[dict[str, Any]] = []
    for index, step in enumerate(steps, start=1):
        if isinstance(step, dict):
            normalized.append(
                {
                    "step_number": step.get("step_number", index),
                    "description": step.get("description") or "",
                    "passes": bool(step.get("passes", False)),
                    "spec": step.get("spec"),
                }
            )
            continue
        normalized.append(
            {
                "step_number": index,
                "description": str(step),
                "passes": False,
                "spec": None,
            }
        )
    return normalized


def _build_subtask_entry(task_id: str, st: dict[str, Any]) -> dict[str, Any]:
    deps = get_subtask_dependencies(task_id, st["subtask_id"])
    steps = _build_subtask_steps(st)
    step_summary = st.get("step_summary")
    if not isinstance(step_summary, dict):
        step_summary = {
            "total": len(steps),
            "completed": sum(1 for step in steps if step.get("passes")),
        }
    return {
        "id": st["subtask_id"],
        "task_id": task_id,
        "subtask_id": st["subtask_id"],
        "phase": st.get("phase"),
        "subtask_type": st.get("subtask_type"),
        "description": st["description"],
        "passes": st.get("passes", False),
        "passed_at": _format_datetime(st.get("passed_at")),
        "display_order": st.get("display_order", 0),
        "created_at": _format_datetime(st.get("created_at")),
        "depends_on": deps or None,
        "step_summary": step_summary,
        "steps": steps,
    }


def _build_progress_log(task_id: str) -> list[str]:
    events = get_events_by_trace(task_id, visibility="user", limit=500)
    return [
        f"[{e['timestamp'].strftime('%Y-%m-%d %H:%M:%S')}] {e['message']}"
        for e in events
        if e.get("message")
    ]


def build_export_data(
    task: dict[str, Any],
    spirit: dict[str, Any] | None,
    subtasks: list[dict[str, Any]],
) -> dict[str, Any]:
    """Build complete export data for plan.json round-trip."""
    task_id = task["id"]
    blocking = dep_store.get_blocking_tasks(task_id)
    return {
        "exported_at": datetime.now(UTC).isoformat(),
        "task": _build_task_payload(task, spirit),
        "spirit": _build_spirit_payload(task, spirit),
        "acceptance_criteria": _build_acceptance_criteria(spirit),
        "subtasks": [_build_subtask_entry(task_id, st) for st in subtasks],
        "dependencies": {
            "blocks": [{"id": t["id"], "title": t["title"]} for t in blocking],
            "blocked_by": [],
        },
        "progress_log": _build_progress_log(task_id),
    }
