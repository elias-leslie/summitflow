"""Tasks API - Response conversion."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from ...schemas.tasks import (
    AcceptanceCriterion,
    BlockerInfo,
    CapabilityContext,
    SubtaskResponse,
    SubtaskSummary,
    TaskResponse,
)
from ...storage.tasks.execution_mode import is_autonomous_mode


def _format_datetime(val: str | datetime | None) -> str | None:
    if val is None:
        return None
    if isinstance(val, str):
        return val
    return val.isoformat()


def _none_if_blank(value: str | None) -> str | None:
    """Normalize empty strings in task spirit fields to null API values."""
    if isinstance(value, str) and not value.strip():
        return None
    return value


def _parse_criterion(crit: dict[str, Any]) -> AcceptanceCriterion:
    return AcceptanceCriterion(
        id=crit.get("id", "ac-000"),
        criterion=crit.get("criterion", crit.get("description", "")),
        category=crit.get("category", "correctness"),
        measurement=crit.get("measurement", "test"),
        threshold=crit.get("threshold"),
        verified=crit.get("verified", crit.get("passes", False)),
        verified_at=crit.get("verified_at"),
        verified_by=crit.get("verified_by"),
    )


def _parse_criteria(raw: list[dict[str, Any]], *, filter_empty: bool = False) -> list[AcceptanceCriterion]:
    if filter_empty:
        return [_parse_criterion(c) for c in raw
                if c.get("id") or c.get("criterion") or c.get("description")]
    return [_parse_criterion(c) for c in raw]


def _parse_capability(task: dict[str, Any]) -> CapabilityContext | None:
    c = task.get("capability")
    if c is None:
        return None
    criteria = _parse_criteria(c["acceptance_criteria"]) if c.get("acceptance_criteria") else None
    return CapabilityContext(
        id=c["id"], capability_id=c["capability_id"], name=c["name"],
        criteria_passed=c["criteria_passed"], criteria_total=c["criteria_total"],
        acceptance_criteria=criteria,
    )


def _parse_blockers(task: dict[str, Any]) -> tuple[list[BlockerInfo] | None, bool | None]:
    if task.get("blockers") is None:
        return None, None
    blockers = [
        BlockerInfo(id=b["id"], title=b["title"], status=b["status"], priority=b["priority"])
        for b in task["blockers"]
    ]
    return blockers, bool(blockers)


def _parse_subtask_summary(task: dict[str, Any]) -> SubtaskSummary | None:
    ss = task.get("subtask_summary")
    if ss is None:
        return None
    return SubtaskSummary(
        total=ss.get("total", 0), completed=ss.get("completed", 0),
        next_subtask_id=ss.get("next_subtask_id"), progress_percent=ss.get("progress_percent", 0.0),
    )


def _flatten_steps(steps: list[Any] | None) -> list[str]:
    """Convert steps from storage format (list of dicts or strings) to flat string list."""
    if not steps:
        return []
    if isinstance(steps[0], dict):
        return [step.get("description", "") for step in steps if isinstance(step, dict)]
    return list(steps)


def _parse_subtasks(task: dict[str, Any]) -> list[SubtaskResponse] | None:
    if task.get("subtasks") is None:
        return None
    return [
        SubtaskResponse(
            id=s["id"], task_id=s["task_id"], subtask_id=s["subtask_id"],
            phase=s.get("phase"), description=s["description"],
            steps=_flatten_steps(s.get("steps")),
            passes=s.get("passes", False),
            passed_at=_format_datetime(s.get("passed_at")),
            display_order=s.get("display_order", 0),
            created_at=_format_datetime(s.get("created_at")),
        )
        for s in task["subtasks"]
    ]


def _parse_task_criteria(task: dict[str, Any]) -> list[AcceptanceCriterion] | None:
    raw = task.get("acceptance_criteria")
    return _parse_criteria(raw, filter_empty=True) if isinstance(raw, list) else None


def task_to_response(task: dict[str, Any], criteria_count: int | None = None) -> TaskResponse:
    blockers, blocked_by_incomplete = _parse_blockers(task)
    execution_mode = task.get("execution_mode") or ("autonomous" if task.get("autonomous") else "manual")
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
        total_sessions=task["total_sessions"],
        total_tokens_used=task["total_tokens_used"],
        created_at=task.get("created_at"),
        updated_at=task.get("updated_at"),
        started_at=task.get("started_at"),
        completed_at=task.get("completed_at"),
        priority=task.get("priority", 2),
        labels=task.get("labels") or [],
        task_type=task.get("task_type", "task"),
        parent_task_id=task.get("parent_task_id"),
        acceptance_criteria=_parse_task_criteria(task),
        criteria_count=criteria_count if criteria_count is not None else 0,
        current_phase=task.get("current_phase"),
        verification_result=task.get("verification_result"),
        done_when=task.get("done_when"),
        complexity=task.get("complexity"),
        capability=_parse_capability(task),
        blockers=blockers,
        blocked_by_incomplete=blocked_by_incomplete,
        subtask_summary=_parse_subtask_summary(task),
        subtasks=_parse_subtasks(task),
        execution_mode=execution_mode,
        autonomous=is_autonomous_mode(execution_mode),
        ai_review=task.get("ai_review", True),
        agent_override=task.get("agent_override"),
        plan_status=task.get("plan_status"),
        plan_approved_at=task.get("plan_approved_at"),
        plan_approved_by=task.get("plan_approved_by"),
        context=task.get("context"),
        worktree=task.get("worktree"),
    )
