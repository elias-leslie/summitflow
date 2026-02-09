"""Workflow export utilities.

Build complete export data for plan.json round-trip.
"""

from __future__ import annotations

from typing import Any

from ...storage import task_dependencies as dep_store
from ...storage.events import get_events_by_trace
from ...storage.steps import get_steps_for_subtask


def build_export_data(
    task: dict[str, Any],
    spirit: dict[str, Any] | None,
    subtasks: list[dict[str, Any]],
) -> dict[str, Any]:
    """Build complete export data for plan.json round-trip."""

    # Get acceptance criteria from spirit's done_when
    acceptance_criteria = []
    if spirit and spirit.get("done_when"):
        for i, dw in enumerate(spirit["done_when"], 1):
            acceptance_criteria.append(
                {
                    "id": f"ac-{i}",
                    "criterion": dw,
                    "verified": False,
                }
            )

    # Build subtasks with full step details
    subtasks_export = []
    for st in subtasks:
        steps = get_steps_for_subtask(st["id"])
        # Get dependencies from subtask_dependencies table
        from ...storage.subtasks import get_subtask_dependencies

        deps = get_subtask_dependencies(task["id"], st["subtask_id"])
        depends_on = deps if deps else None

        subtasks_export.append(
            {
                "id": st["subtask_id"],
                "phase": st.get("phase"),
                "description": st["description"],
                "passes": st.get("passes", False),
                "passed_at": st.get("passed_at"),
                "depends_on": depends_on,
                "steps": [
                    {
                        "step_number": s["step_number"],
                        "description": s["description"],
                        "spec": s.get("spec"),
                        "verify_command": s.get("verify_command"),
                        "expected_output": s.get("expected_output"),
                        "passes": s.get("passes", False),
                        "status": s.get("status"),
                    }
                    for s in steps
                ],
            }
        )

    # Get progress log from events table
    events = get_events_by_trace(task["id"], visibility="user", limit=500)
    progress_log = [
        f"[{e['timestamp'].strftime('%Y-%m-%d %H:%M:%S')}] {e['message']}"
        for e in events
        if e.get("message")
    ]

    # Get dependencies
    blocking = dep_store.get_blocking_tasks(task["id"])
    # Note: We only show blockers (tasks that block this one), not what this blocks
    # This is consistent with the context endpoint's behavior

    return {
        "task": {
            "id": task["id"],
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
            "objective": spirit.get("objective") if spirit else None,
            "spirit_anti": spirit.get("spirit_anti") if spirit else None,
            "decisions": spirit.get("decisions", []) if spirit else [],
            "constraints": spirit.get("constraints", []) if spirit else [],
            "done_when": spirit.get("done_when", []) if spirit else [],
            "context": spirit.get("context", {}) if spirit else {},
        }
        if spirit
        else None,
        "acceptance_criteria": acceptance_criteria,
        "subtasks": subtasks_export,
        "dependencies": {
            "blocks": [{"id": t["id"], "title": t["title"]} for t in blocking],
            "blocked_by": [],  # TODO: Add blocked_by if needed
        },
        "progress_log": progress_log,
    }
