"""Workflow export utilities.

Build complete export data for plan.json round-trip.
"""

from __future__ import annotations

from typing import Any

from ...storage import task_dependencies as dep_store
from ...storage.events import get_events_by_trace
from ...storage.steps import get_steps_for_subtask
from ...storage.subtasks import get_subtask_dependencies


def _build_acceptance_criteria(spirit: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not spirit or not spirit.get("done_when"):
        return []
    return [
        {"id": f"ac-{i}", "criterion": dw, "verified": False}
        for i, dw in enumerate(spirit["done_when"], 1)
    ]


def _build_subtask_entry(task_id: str, st: dict[str, Any]) -> dict[str, Any]:
    steps = get_steps_for_subtask(st["id"])
    deps = get_subtask_dependencies(task_id, st["subtask_id"])
    return {
        "id": st["subtask_id"],
        "phase": st.get("phase"),
        "description": st["description"],
        "passes": st.get("passes", False),
        "passed_at": st.get("passed_at"),
        "depends_on": deps or None,
        "steps": [
            {
                "step_number": s["step_number"],
                "description": s["description"],
                "spec": s.get("spec"),
                "verify_command": s.get("verify_command"),
                "passes": s.get("passes", False),
                "status": s.get("status"),
            }
            for s in steps
        ],
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
        "task": {
            "id": task_id,
            "project_id": task["project_id"],
            "title": task["title"],
            "description": task.get("description"),
            "status": task["status"],
            "priority": task.get("priority", 2),
            "task_type": task.get("task_type", "task"),
            "complexity": task.get("complexity") or (spirit.get("complexity") if spirit else None),
            "qa_status": task.get("qa_status", "pending"),
            "plan_status": spirit.get("plan_status") if spirit else "draft",
            "created_at": task["created_at"].isoformat() if task.get("created_at") else None,
        },
        "spirit": {
            "objective": spirit.get("objective"),
            "spirit_anti": spirit.get("spirit_anti"),
            "decisions": spirit.get("decisions", []),
            "constraints": spirit.get("constraints", []),
            "done_when": spirit.get("done_when", []),
            "context": spirit.get("context", {}),
        }
        if spirit
        else None,
        "acceptance_criteria": _build_acceptance_criteria(spirit),
        "subtasks": [_build_subtask_entry(task_id, st) for st in subtasks],
        "dependencies": {
            "blocks": [{"id": t["id"], "title": t["title"]} for t in blocking],
            "blocked_by": [],
        },
        "progress_log": _build_progress_log(task_id),
    }
