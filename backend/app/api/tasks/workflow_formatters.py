"""Workflow formatters.

TOON (Token-Optimized Output Notation) formatting for task context.
"""

from __future__ import annotations

from typing import Any

from ...storage.events import get_events_by_trace
from ...storage.steps import get_steps_for_subtask


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
    return [f"CONTEXT:{' | '.join(parts)}"] if parts else []


def _format_subtask_lines(subtasks: list[dict[str, Any]]) -> tuple[list[str], int, int]:
    """Return subtask lines, total criteria count, and verified criteria count."""
    if not subtasks:
        return [], 0, 0
    completed = sum(1 for s in subtasks if s.get("passes"))
    pct = int(completed / len(subtasks) * 100)
    lines: list[str] = [f"SUBTASKS[{len(subtasks)}]:{completed}/{len(subtasks)}:{pct}%"]
    total_criteria = 0
    verified_criteria = 0
    for st in subtasks:
        steps = get_steps_for_subtask(st["id"])
        total_criteria += len(steps)
        passed = sum(1 for s in steps if s.get("passes"))
        verified_criteria += passed
        marker = "PASS" if st.get("passes") else "____"
        phase = f"[{st['phase']}] " if st.get("phase") else ""
        raw_desc = st.get("description", "")
        desc = raw_desc[:45] + ("..." if len(raw_desc) > 45 else "")
        lines.append(f"{st['subtask_id']}   {marker} {phase}{desc} [{passed}/{len(steps)}]")
        for step in steps:
            step_desc = step.get("description", "")[:60]
            status = "PASS" if step.get("passes") else "____"
            lines.append(f"  {step.get('step_number', 0)}. {status} {step_desc}")
    return lines, total_criteria, verified_criteria


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


def format_toon_context(
    task: dict[str, Any],
    spirit: dict[str, Any] | None,
    subtasks: list[dict[str, Any]],
    blockers: list[dict[str, Any]],
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
        lines.append(f"DESCRIPTION:{description}")

    plan_status = spirit.get("plan_status", "draft") if spirit else "draft"
    subtask_lines, criteria_count, criteria_verified = _format_subtask_lines(subtasks)
    decisions_count = len(spirit.get("decisions", [])) if spirit else 0
    if plan_status != "draft" or criteria_count > 0 or decisions_count > 0:
        lines.append(f"WORKFLOW:plan:{plan_status}|criteria:{criteria_count}|decisions:{decisions_count}")

    if spirit and spirit.get("objective"):
        lines.append(f"OBJECTIVE:{spirit['objective']}")
    if spirit and spirit.get("spirit_anti"):
        lines.append(f"SPIRIT_ANTI:{spirit['spirit_anti']}")

    if spirit:
        done_when_list = spirit.get("done_when") or []
        if done_when_list:
            strs = [str(d) for d in done_when_list]
            lines.append(f"DONE_WHEN[{len(strs)}]:{' | '.join(strs)}")
        lines.extend(_format_context_lines(spirit))

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
) -> dict[str, Any]:
    """Build JSON context response."""
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
    }


def format_logs_toon(task_id: str, progress_log: list[str]) -> str:
    """Format progress logs as TOON."""
    lines = [f"LOGS[{len(progress_log)}]:{task_id}"]
    lines.extend(progress_log)
    return "\n".join(lines)
