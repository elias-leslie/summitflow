"""Tasks API - Workflow endpoints.

Handles plan approval, context retrieval, export, and logs:
- POST /approve: Approve a task's plan
- GET /context: Full task context (TOON default)
- GET /export: Complete task JSON for plan.json round-trip
- GET /logs: Task progress log entries (TOON default)
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel

from ...logging_config import get_logger
from ...storage import task_dependencies as dep_store
from ...storage import tasks as task_store
from ...storage.events import get_events_by_trace
from ...storage.steps import get_steps_for_subtask
from ...storage.subtasks import get_subtasks_for_task
from ...storage.task_spirit import approve_plan, get_task_spirit

logger = get_logger(__name__)

router = APIRouter()


# Request/Response models
class PlanApproveRequest(BaseModel):
    """Request body for plan approval."""

    approved_by: str = "user"
    notes: str | None = None


class PlanApproveResponse(BaseModel):
    """Response for plan approval."""

    task_id: str
    plan_status: str
    plan_approved_at: str | None
    plan_approved_by: str | None
    message: str


# Helper functions
def _verify_task_project(task_id: str, project_id: str) -> dict[str, Any]:
    """Get task and verify it belongs to the project."""
    task = task_store.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail=f"Task {task_id} not found")
    if task["project_id"] != project_id:
        raise HTTPException(
            status_code=404, detail=f"Task {task_id} not found in project {project_id}"
        )
    return task


def _format_toon_context(
    task: dict[str, Any],
    spirit: dict[str, Any] | None,
    subtasks: list[dict[str, Any]],
    blockers: list[dict[str, Any]],
) -> str:
    """Format task context as TOON (Token-Optimized Output Notation).

    Format matches `st context` output for API-CLI parity.
    """
    lines: list[str] = []

    # Task header: TASK:id|status|priority|type|complexity
    priority = f"P{task.get('priority', 2)}"
    complexity = task.get("complexity") or spirit.get("complexity") if spirit else ""
    complexity = complexity or "STANDARD"
    lines.append(
        f"TASK:{task['id']}|{task['status']}|{priority}|{task.get('task_type', 'task')}|{complexity}"
    )

    # Workflow status
    plan_status = spirit.get("plan_status", "draft") if spirit else "draft"
    qa_status = task.get("qa_status", "pending")
    criteria_count = 0
    for st in subtasks:
        steps = get_steps_for_subtask(st["id"])
        criteria_count += len(steps)
    decisions_count = len(spirit.get("decisions", [])) if spirit else 0
    lines.append(
        f"WORKFLOW:plan:{plan_status}|qa:{qa_status}|criteria:{criteria_count}|decisions:{decisions_count}"
    )

    # Objective
    if spirit and spirit.get("objective"):
        lines.append(f"OBJECTIVE:{spirit['objective']}")

    # Spirit & Anti-pattern
    if spirit and spirit.get("spirit_anti"):
        lines.append(f"SPIRIT_ANTI:{spirit['spirit_anti']}")

    # Done when
    if spirit and spirit.get("done_when"):
        done_when_list = spirit["done_when"]
        if done_when_list:
            done_when_strs = [str(d) for d in done_when_list]
            lines.append(f"DONE_WHEN[{len(done_when_strs)}]:{' | '.join(done_when_strs)}")

    # Context (files to modify/create, refs, testing)
    if spirit and spirit.get("context"):
        ctx = spirit["context"]
        ctx_parts: list[str] = []
        if ctx.get("files_to_modify"):
            ctx_parts.append(f"modify:{','.join(ctx['files_to_modify'][:5])}")
        if ctx.get("files_to_create"):
            ctx_parts.append(f"create:{','.join(ctx['files_to_create'][:5])}")
        if ctx.get("references"):
            ctx_parts.append(f"refs:{len(ctx['references'])}")
        if ctx.get("testing_strategy"):
            ctx_parts.append(f"testing:{ctx['testing_strategy'][:80]}")
        if ctx_parts:
            lines.append(f"CONTEXT:{' | '.join(ctx_parts)}")

    # Subtasks summary and details
    if subtasks:
        completed = sum(1 for s in subtasks if s.get("passes"))
        lines.append(
            f"SUBTASKS[{len(subtasks)}]:{completed}/{len(subtasks)}:{int(completed / len(subtasks) * 100) if subtasks else 0}%"
        )

        for st in subtasks:
            steps = get_steps_for_subtask(st["id"])
            passed_steps = sum(1 for s in steps if s.get("passes"))
            status_marker = "PASS" if st.get("passes") else "____"
            phase_tag = f"[{st.get('phase', 'work')}] " if st.get("phase") else ""
            # Truncate description
            desc = st.get("description", "")[:45]
            if len(st.get("description", "")) > 45:
                desc += "..."
            lines.append(
                f"{st['subtask_id']}   {status_marker} {phase_tag}{desc} [{passed_steps}/{len(steps)}]"
            )

            # Steps under each subtask
            for step in steps:
                step_num = step.get("step_number", 0)
                step_status = "PASS" if step.get("passes") else "____"
                step_desc = step.get("description", "")[:60]
                lines.append(f"  {step_num}. {step_status} {step_desc}")

                # Verify command and expected output
                if step.get("verify_command"):
                    lines.append(f"       verify: {step['verify_command']}")
                if step.get("expected_output"):
                    lines.append(f"       expect: {step['expected_output']}")

    # Blockers
    if blockers:
        lines.append(f"BLOCKERS[{len(blockers)}]:")
        for b in blockers:
            lines.append(f"  {b['id']}|{b['status']}|{b['title'][:50]}")

    # Progress log from events table (last 3 entries for session continuity)
    events = get_events_by_trace(task["id"], visibility="user", limit=100)
    if events:
        recent_events = events[-3:]
        lines.append(f"LOG[{len(events)}]:")
        for event in recent_events:
            msg = event.get("message") or ""
            ts = event.get("timestamp")
            ts_str = ts.strftime("%Y-%m-%d %H:%M:%S") if ts else ""
            log_preview = f"[{ts_str}] {msg[:80]}"
            if len(msg) > 80:
                log_preview += "..."
            lines.append(f"  {log_preview}")

    # Acceptance criteria count
    criteria_verified = sum(
        1 for st in subtasks for s in get_steps_for_subtask(st["id"]) if s.get("passes")
    )
    lines.append(f"CRITERIA[{criteria_verified}]:{criteria_verified}/{criteria_count}")

    return "\n".join(lines)


def _build_export_data(
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


# Endpoints
@router.post("/projects/{project_id}/tasks/{task_id}/approve", response_model=PlanApproveResponse)
async def approve_task_plan(
    project_id: str,
    task_id: str,
    body: PlanApproveRequest | None = None,
) -> PlanApproveResponse:
    """Approve a task's plan, allowing execution to start.

    Args:
        project_id: Project ID
        task_id: Task ID
        body: Optional approval details (approved_by, notes)

    Returns:
        PlanApproveResponse with updated plan status
    """
    _verify_task_project(task_id, project_id)

    approved_by = body.approved_by if body else "user"
    notes = body.notes if body else None

    result = approve_plan(task_id, approved_by=approved_by, notes=notes)

    if not result:
        # Task exists but no task_spirit record - create one with approved status
        from ...storage.task_spirit import create_task_spirit

        try:
            task_data = task_store.get_task(task_id)
            if task_data:
                objective = task_data.get("objective") or task_data.get("title", "")
                create_task_spirit(
                    task_id=task_id,
                    objective=objective,
                )
                result = approve_plan(task_id, approved_by=approved_by, notes=notes)
        except Exception as e:
            logger.warning(f"Failed to create task_spirit for approval: {e}")

    if not result:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to approve plan for task {task_id}",
        )

    return PlanApproveResponse(
        task_id=task_id,
        plan_status=result["plan_status"],
        plan_approved_at=result["plan_approved_at"],
        plan_approved_by=result["plan_approved_by"],
        message=f"Plan approved for task {task_id}",
    )


@router.get("/projects/{project_id}/tasks/{task_id}/context", response_model=None)
async def get_task_context(
    project_id: str,
    task_id: str,
    format: str | None = Query(
        None, description="Output format: 'json' for JSON (default is TOON)"
    ),
) -> PlainTextResponse | dict[str, Any]:
    """Get full task context including spirit, subtasks, steps, and blockers.

    Returns TOON format by default (matches st context output).
    Use ?format=json for JSON response.

    Args:
        project_id: Project ID
        task_id: Task ID
        format: Output format ('json' for JSON, default is TOON)
    """
    task = _verify_task_project(task_id, project_id)

    # Get spirit data
    spirit = get_task_spirit(task_id)

    # Get subtasks with steps
    subtasks = get_subtasks_for_task(task_id, include_steps=False)

    # Get blockers
    blockers = dep_store.get_blocking_tasks(task_id)

    if format == "json":
        # Return structured JSON
        subtasks_with_steps = []
        for st in subtasks:
            steps = get_steps_for_subtask(st["id"])
            subtasks_with_steps.append(
                {
                    **st,
                    "steps": steps,
                }
            )

        return {
            "task": {
                "id": task["id"],
                "project_id": task["project_id"],
                "title": task["title"],
                "description": task.get("description"),
                "status": task["status"],
                "priority": task.get("priority", 2),
                "task_type": task.get("task_type", "task"),
                "complexity": task.get("complexity"),
                "qa_status": task.get("qa_status", "pending"),
            },
            "spirit": spirit,
            "subtasks": subtasks_with_steps,
            "blockers": blockers,
        }

    # Default: TOON format
    toon_output = _format_toon_context(task, spirit, subtasks, blockers)
    return PlainTextResponse(content=toon_output)


@router.get("/projects/{project_id}/tasks/{task_id}/export")
async def export_task(
    project_id: str,
    task_id: str,
) -> dict[str, Any]:
    """Export complete task data for plan.json round-trip.

    Returns all nested data including:
    - Task basic info
    - Spirit (objective, done_when, context, etc.)
    - Acceptance criteria
    - Subtasks with steps
    - Dependencies
    - Progress log

    Args:
        project_id: Project ID
        task_id: Task ID
    """
    task = _verify_task_project(task_id, project_id)

    # Get spirit data
    spirit = get_task_spirit(task_id)

    # Get subtasks
    subtasks = get_subtasks_for_task(task_id, include_steps=False)

    return _build_export_data(task, spirit, subtasks)


@router.get("/projects/{project_id}/tasks/{task_id}/logs", response_model=None)
async def get_task_logs(
    project_id: str,
    task_id: str,
    format: str | None = Query(
        None, description="Output format: 'json' for JSON (default is TOON)"
    ),
) -> PlainTextResponse | dict[str, Any]:
    """Get task progress log entries.

    Returns TOON format by default:
    ```
    LOGS[3]:task-abc123
    [2026-01-23 10:00] Plan defect in subtask 1.2...
    [2026-01-23 11:00] Gap analysis completed...
    [2026-01-23 12:00] Session paused at subtask 2.1
    ```

    Use ?format=json for JSON response.

    Args:
        project_id: Project ID
        task_id: Task ID
        format: Output format ('json' for JSON, default is TOON)
    """
    _verify_task_project(task_id, project_id)

    # Get progress log from events table
    events = get_events_by_trace(task_id, visibility="user", limit=500)
    progress_log = [
        f"[{e['timestamp'].strftime('%Y-%m-%d %H:%M:%S')}] {e['message']}"
        for e in events
        if e.get("message")
    ]

    if format == "json":
        return {
            "task_id": task_id,
            "entries": progress_log,
            "count": len(progress_log),
        }

    # Default: TOON format
    lines = [f"LOGS[{len(progress_log)}]:{task_id}"]
    for entry in progress_log:
        lines.append(entry)

    return PlainTextResponse(content="\n".join(lines))
