"""Workflow formatters.

TOON (Token-Optimized Output Notation) formatting for task context.
"""

from __future__ import annotations

from typing import Any

from ...storage.events import get_events_by_trace
from ...storage.steps import get_steps_for_subtask


def format_toon_context(
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
            "qa_status": task.get("qa_status", "pending"),
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
