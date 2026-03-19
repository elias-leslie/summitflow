"""Workflow formatters.

TOON (Token-Optimized Output Notation) formatting for task context.
"""

from __future__ import annotations

from typing import Any

from ...services.task_execution_readiness import TaskExecutionReadiness
from ...services.task_lane_preflight import TaskLaneConflictCheck, TaskLaneConflictCheckDict
from ...storage.events import get_events_by_trace


def _format_context_lines(spirit: dict[str, Any]) -> list[str]:
    """Return CONTEXT line(s) from spirit context dict."""
    ctx = spirit.get("context")
    if not ctx:
        return []
    parts: list[str] = []
    if ctx.get("files_to_modify"):
        parts.append(f"modify:{','.join(ctx['files_to_modify'][:5])}")
    if ctx.get("files_to_create"):
        parts.append(f"create:{','.join(ctx['files_to_create'][:5])}")
    if ctx.get("references"):
        parts.append(f"refs:{len(ctx['references'])}")
    if ctx.get("testing_strategy"):
        parts.append(f"testing:{ctx['testing_strategy'][:80]}")
    second_opinion = ctx.get("second_opinion")
    if isinstance(second_opinion, dict):
        parts.append(
            "2nd:"
            f"{second_opinion.get('stage', 'task_shape')}:"
            f"{second_opinion.get('status', 'pending')}"
        )
    return [f"CONTEXT:{' | '.join(parts)}"] if parts else []


def _format_lane_line(lane_check: TaskLaneConflictCheck | dict[str, Any] | None) -> list[str]:
    """Return a compact lane-overlap line when active ownership matters."""
    if lane_check is None:
        return []
    data = lane_check.to_dict() if isinstance(lane_check, TaskLaneConflictCheck) else lane_check
    issues = data.get("issues") or []
    if not issues:
        return []
    parts: list[str] = []
    disposition = data.get("disposition")
    if disposition:
        parts.append(f"disp:{disposition}")
    overlap_kind = data.get("overlap_kind")
    if overlap_kind:
        parts.append(f"kind:{overlap_kind}")
    conflicting_tasks = data.get("conflicting_tasks") or []
    if conflicting_tasks:
        parts.append(f"tasks:{','.join(conflicting_tasks[:3])}")
    owner_location = data.get("owner_location")
    if owner_location:
        parts.append(f"owner:{owner_location}")
    overlap_paths = data.get("overlap_paths") or []
    if overlap_paths:
        parts.append(f"paths:{','.join(overlap_paths[:3])}")
    if data.get("shared_plumbing"):
        parts.append("shared:yes")
    return [f"LANE:{' | '.join(parts)}"] if parts else ["LANE:conflict"]


def _format_subtask_lines(subtasks: list[dict[str, Any]]) -> tuple[list[str], int, int]:
    """Return subtask lines, total criteria count, and verified criteria count."""
    if not subtasks:
        return [], 0, 0
    completed = sum(1 for s in subtasks if s.get("passes"))
    pct = int(completed / len(subtasks) * 100)
    lines: list[str] = [f"SUBTASKS[{len(subtasks)}]:{completed}/{len(subtasks)}:{pct}%"]
    for st in subtasks:
        marker = "PASS" if st.get("passes") else "____"
        phase = f"[{st['phase']}] " if st.get("phase") else ""
        raw_desc = st.get("description", "")
        desc = raw_desc[:45] + ("..." if len(raw_desc) > 45 else "")
        lines.append(f"{st['subtask_id']}   {marker} {phase}{desc}")
    return lines, 0, 0


def _format_event_log_lines(task_id: str) -> list[str]:
    """Return LOG lines for the last 3 user-visible events."""
    events = get_events_by_trace(task_id, visibility="user", limit=100)
    if not events:
        return []
    lines = [f"LOG[{len(events)}]:"]
    for event in events[-3:]:
        msg = event.get("message") or ""
        ts = event.get("timestamp")
        ts_str = ts.strftime("%Y-%m-%d %H:%M:%S") if ts else ""
        preview = f"[{ts_str}] {msg[:80]}" + ("..." if len(msg) > 80 else "")
        lines.append(f"  {preview}")
    return lines


def _format_workflow_readiness_lines(
    plan_status: str,
    criteria_count: int,
    decisions_count: int,
    readiness: TaskExecutionReadiness | None,
) -> list[str]:
    """Return WORKFLOW and READINESS lines when relevant."""
    lines: list[str] = []
    if plan_status != "draft" or criteria_count > 0 or decisions_count > 0 or readiness is not None:
        ready_flag = "yes" if readiness and readiness.ready else "no"
        issue_count = len(readiness.issues) if readiness else 0
        lines.append(
            f"WORKFLOW:plan:{plan_status}|ready:{ready_flag}|issues:{issue_count}"
            f"|criteria:{criteria_count}|decisions:{decisions_count}"
        )
    if readiness and readiness.issues:
        lines.append(f"READINESS:missing:{','.join(readiness.missing_fields)}")
    return lines


def _format_spirit_section_lines(spirit: dict[str, Any]) -> list[str]:
    """Return OBJECTIVE, SPIRIT_ANTI, DONE_WHEN, and CONTEXT lines from spirit."""
    lines: list[str] = []
    done_when_list = spirit.get("done_when") or []
    if done_when_list:
        strs = [str(d) for d in done_when_list]
        lines.append(f"DONE_WHEN[{len(strs)}]:{' | '.join(strs)}")
    lines.extend(_format_context_lines(spirit))
    return lines


def format_toon_context(
    task: dict[str, Any],
    spirit: dict[str, Any] | None,
    subtasks: list[dict[str, Any]],
    blockers: list[dict[str, Any]],
    readiness: TaskExecutionReadiness | None = None,
    lane_check: TaskLaneConflictCheck | dict[str, Any] | None = None,
) -> str:
    """Format task context as TOON (Token-Optimized Output Notation).

    Format matches `st context` output for API-CLI parity.
    """
    priority = f"P{task.get('priority', 2)}"
    complexity = (task.get("complexity") or (spirit.get("complexity") if spirit else None)) or "STANDARD"
    lines: list[str] = [
        f"TASK:{task['id']}|{task['status']}|{priority}|{task.get('task_type', 'task')}|{complexity}"
    ]
    title = str(task.get("title") or "").strip()
    if title:
        lines.append(f"TITLE:{title}")
    description = str(task.get("description") or "").strip()
    if description:
        lines.append(f"DESCRIPTION:{description[:200]}{'...' if len(description) > 200 else ''}")

    plan_status = spirit.get("plan_status", "draft") if spirit else "draft"
    subtask_lines, criteria_count, criteria_verified = _format_subtask_lines(subtasks)
    lines.extend(_format_workflow_readiness_lines(plan_status, criteria_count, 0, readiness))

    if spirit:
        lines.extend(_format_spirit_section_lines(spirit))
    lines.extend(_format_lane_line(lane_check))
    lines.extend(subtask_lines)

    if blockers:
        lines.append(f"BLOCKERS[{len(blockers)}]:")
        for b in blockers:
            lines.append(f"  {b['id']}|{b['status']}|{b['title'][:50]}")

    lines.extend(_format_event_log_lines(task["id"]))
    if criteria_count > 0:
        lines.append(f"CRITERIA[{criteria_verified}]:{criteria_verified}/{criteria_count}")
    return "\n".join(lines)


def build_context_json(
    task: dict[str, Any],
    spirit: dict[str, Any] | None,
    subtasks: list[dict[str, Any]],
    blockers: list[dict[str, Any]],
    lane_check: TaskLaneConflictCheck | dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build JSON context response."""
    lane_payload: TaskLaneConflictCheckDict | dict[str, Any] | None = None
    if lane_check is not None:
        lane_payload = lane_check.to_dict() if isinstance(lane_check, TaskLaneConflictCheck) else lane_check
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
        },
        "spirit": spirit,
        "subtasks": subtasks,
        "blockers": blockers,
        "lane_preflight": lane_payload,
    }


def format_logs_toon(task_id: str, progress_log: list[str]) -> str:
    """Format progress logs as TOON."""
    lines = [f"LOGS[{len(progress_log)}]:{task_id}"]
    lines.extend(progress_log)
    return "\n".join(lines)
