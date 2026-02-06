"""Tasks API - Response conversion.

Handles conversion of task dictionaries from storage layer to API response models.
"""

from __future__ import annotations

from typing import Any

from ...schemas.tasks import (
    AcceptanceCriterion,
    BlockerInfo,
    CapabilityContext,
    SubtaskResponse,
    SubtaskSummary,
    TaskResponse,
)
from .helpers import get_step_count_for_task


def task_to_response(task: dict[str, Any], criteria_count: int | None = None) -> TaskResponse:
    """Convert task dict to response model.

    Args:
        task: Task dict from storage
        criteria_count: Pre-fetched criteria count (avoids N+1 query in list endpoints)
    """
    # Handle optional capability context
    capability_context = None
    if task.get("capability") is not None:
        c = task["capability"]
        # Parse acceptance criteria if present
        criteria_list = None
        if c.get("acceptance_criteria"):
            criteria_list = [
                AcceptanceCriterion(
                    id=crit.get("id", "ac-000"),
                    criterion=crit.get("criterion", crit.get("description", "")),
                    category=crit.get("category", "correctness"),
                    measurement=crit.get("measurement", "test"),
                    threshold=crit.get("threshold"),
                    verified=crit.get("verified", crit.get("passes", False)),
                    verified_at=crit.get("verified_at"),
                    verified_by=crit.get("verified_by"),
                )
                for crit in c["acceptance_criteria"]
            ]
        capability_context = CapabilityContext(
            id=c["id"],
            capability_id=c["capability_id"],
            name=c["name"],
            criteria_passed=c["criteria_passed"],
            criteria_total=c["criteria_total"],
            acceptance_criteria=criteria_list,
        )

    # Handle optional blockers context
    blockers_list = None
    blocked_by_incomplete = None
    if task.get("blockers") is not None:
        blockers_list = [
            BlockerInfo(
                id=b["id"],
                title=b["title"],
                status=b["status"],
                priority=b["priority"],
            )
            for b in task["blockers"]
        ]
        blocked_by_incomplete = len(blockers_list) > 0

    # Handle task-level acceptance criteria (JSONB from storage)
    task_criteria_list = None
    if task.get("acceptance_criteria"):
        raw_criteria = task["acceptance_criteria"]
        # Storage returns list of dicts from JSONB
        if isinstance(raw_criteria, list):
            task_criteria_list = [
                AcceptanceCriterion(
                    id=crit.get("id", "ac-000"),
                    criterion=crit.get("criterion", crit.get("description", "")),
                    category=crit.get("category", "correctness"),
                    measurement=crit.get("measurement", "test"),
                    threshold=crit.get("threshold"),
                    verified=crit.get("verified", False),
                    verified_at=crit.get("verified_at"),
                    verified_by=crit.get("verified_by"),
                )
                for crit in raw_criteria
                if crit.get("id") or crit.get("criterion") or crit.get("description")
            ]

    # Handle subtask summary (from list_ready_tasks with JOIN)
    subtask_summary_obj = None
    if task.get("subtask_summary") is not None:
        ss = task["subtask_summary"]
        subtask_summary_obj = SubtaskSummary(
            total=ss.get("total", 0),
            completed=ss.get("completed", 0),
            next_subtask_id=ss.get("next_subtask_id"),
            progress_percent=ss.get("progress_percent", 0.0),
        )

    # Handle subtasks (from batch create with nested subtasks)
    subtasks_list = None
    if task.get("subtasks") is not None:

        def _format_datetime(val: Any) -> str | None:
            """Convert datetime to ISO string, handling already-string values."""
            if val is None:
                return None
            if isinstance(val, str):
                return val
            return val.isoformat() if hasattr(val, "isoformat") else str(val)

        subtasks_list = [
            SubtaskResponse(
                id=s["id"],
                task_id=s["task_id"],
                subtask_id=s["subtask_id"],
                phase=s.get("phase"),
                description=s["description"],
                # Steps from storage: list of dicts with "description" key
                steps=[step["description"] for step in s.get("steps", [])]
                if s.get("steps") and isinstance(s["steps"][0], dict)
                else s.get("steps", []),
                passes=s.get("passes", False),
                passed_at=_format_datetime(s.get("passed_at")),
                display_order=s.get("display_order", 0),
                created_at=_format_datetime(s.get("created_at")),
            )
            for s in task["subtasks"]
        ]

    return TaskResponse(
        id=task["id"],
        project_id=task["project_id"],
        capability_id=task["capability_id"],
        title=task["title"],
        description=task["description"],
        status=task["status"],
        error_message=task["error_message"],
        branch_name=task["branch_name"],
        commits=task["commits"] or [],
        pull_request_url=task["pull_request_url"],
        total_sessions=task["total_sessions"],
        total_tokens_used=task["total_tokens_used"],
        created_at=task["created_at"].isoformat() if task["created_at"] else None,
        started_at=task["started_at"].isoformat() if task["started_at"] else None,
        completed_at=task["completed_at"].isoformat() if task["completed_at"] else None,
        # Issue tracking fields
        priority=task.get("priority", 2),
        labels=task.get("labels") or [],
        task_type=task.get("task_type", "task"),
        parent_task_id=task.get("parent_task_id"),
        # AI agent reliability fields
        objective=task.get("objective"),
        acceptance_criteria=task_criteria_list,
        criteria_count=criteria_count
        if criteria_count is not None
        else get_step_count_for_task(task["id"]),
        current_phase=task.get("current_phase"),
        verification_result=task.get("verification_result"),
        # Pipeline v2 fields
        spirit_anti=task.get("spirit_anti"),
        decisions=task.get("decisions"),
        constraints=task.get("constraints"),
        done_when=task.get("done_when"),
        complexity=task.get("complexity"),
        # Optional feature context
        capability=capability_context,
        # Optional blockers context
        blockers=blockers_list,
        blocked_by_incomplete=blocked_by_incomplete,
        # Subtask summary (from list_ready_tasks with JOIN)
        subtask_summary=subtask_summary_obj,
        # Subtasks with steps (from batch create)
        subtasks=subtasks_list,
        # Autonomous execution flag
        autonomous=task.get("autonomous", False),
        # QA workflow fields (migration 068)
        qa_status=task.get("qa_status", "pending"),
        qa_signoff_at=task["qa_signoff_at"].isoformat() if task.get("qa_signoff_at") else None,
        qa_signoff_by=task.get("qa_signoff_by"),
        qa_issues=task.get("qa_issues"),
        # Plan workflow fields (from task_spirit if joined)
        plan_status=task.get("plan_status"),
        plan_approved_at=task.get("plan_approved_at"),
        plan_approved_by=task.get("plan_approved_by"),
        # Context for plan.json round-trip (from task_spirit if joined)
        context=task.get("context"),
        # Worktree info (when task has an active worktree)
        worktree=task.get("worktree"),
    )
