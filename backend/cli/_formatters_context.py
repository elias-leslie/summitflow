"""Context-view section formatters for task and subtask TOON output."""

from __future__ import annotations

from typing import Any

from ._formatters_compact import _safe_int, truncate
from ._formatters_context_task import format_context_task as format_context_task


def format_context_decisions(decisions: list[dict[str, Any]]) -> str:
    """Format decisions for context output."""
    if not decisions:
        return ""
    lines = [f"DECISIONS[{len(decisions)}]"]
    for d in decisions:
        lines.append(f"{d.get('id', '?')}:{d.get('title', '')}→{d.get('outcome', '')}")
    return "\n".join(lines)


def format_context_subtasks(subtasks: list[dict[str, Any]]) -> str:
    """Format subtasks with steps inline for context output."""
    if not subtasks:
        return ""
    done = sum(1 for s in subtasks if s.get("passes"))
    total = len(subtasks)
    pct = (done / total * 100) if total > 0 else 0
    lines = [f"SUBTASKS[{total}]:{done}/{total}:{pct:.0f}%"]
    for subtask in subtasks:
        subtask_id = subtask.get("subtask_id", "?")
        passes = "PASS" if subtask.get("passes") else "____"
        phase = subtask.get("phase") or ""
        desc = subtask.get("description") or ""
        step_summary = subtask.get("step_summary") or {}
        step_done = _safe_int(step_summary.get("completed", 0))
        step_total = _safe_int(step_summary.get("total", 0))
        phase_prefix = f"[{phase}] " if phase else ""
        lines.append(f"{subtask_id:5} {passes} {phase_prefix}{desc} [{step_done}/{step_total}]")
        for step in subtask.get("steps") or subtask.get("steps_from_table") or []:
            step_num = step.get("step_number", 0)
            step_pass = "PASS" if step.get("passes") else "____"
            lines.append(f"  {step_num}. {step_pass} {step.get('description') or ''}")
    return "\n".join(lines)


def format_context_blockers(blockers: list[dict[str, Any]]) -> str:
    """Format blockers for context output."""
    if not blockers:
        return ""
    lines = [f"BLOCKERS[{len(blockers)}]"]
    for b in blockers:
        lines.append(f"{b.get('id', '?')}|{b.get('status', '?')}|{b.get('title') or ''}")
    return "\n".join(lines)


def format_context_log(progress_log: list[str] | str | None) -> str:
    """Format progress log for context output (last 3 entries)."""
    if not progress_log:
        return ""
    entries = (
        [e.strip() for e in progress_log.split("\n") if e.strip()]
        if isinstance(progress_log, str)
        else progress_log
    )
    if not entries:
        return ""
    lines = [f"LOG[{len(entries)}]"]
    for log in entries[-3:]:
        log_str = str(log)
        lines.append(f"  {log_str[:100]}{'...' if len(log_str) > 100 else ''}")
    return "\n".join(lines)


def format_context_references(references: list[dict[str, Any]], header: str = "REFERENCES") -> str:
    """Format triggered references for context output."""
    if not references:
        return ""
    lines = [f"{header}[{len(references)}]"]
    for ref in references:
        uuid = str(ref.get("uuid", "?"))[:8]
        summary = ref.get("summary") or truncate(str(ref.get("content", "")), 50)
        lines.append(f"  {uuid}:{summary}")
    return "\n".join(lines)


def format_context_snapshot(snapshot: dict[str, Any]) -> str:
    """Format snapshot/checkpoint state for context output."""
    if not snapshot:
        return ""
    lines = ["SNAPSHOT:active"]
    if claimed_by := snapshot.get("claimed_by"):
        lines[0] += f"|claimed_by:{claimed_by}"
    if created_at := snapshot.get("created_at"):
        ts = str(created_at)[:19]
        lines[0] += f"|since:{ts}"
    if base_branch := snapshot.get("base_branch"):
        lines.append(f"BASE_BRANCH:{base_branch}")
    if branch := snapshot.get("branch"):
        lines.append(f"TASK_BRANCH:{branch}")
    return "\n".join(lines)


def format_subtask_context_task_summary(task: dict[str, Any]) -> str:
    """Format task summary for subtask-scoped context."""
    task_id = task.get("id", "unknown")
    title = task.get("title", "")
    lines = [f"TASK:{task_id}|{title}"]
    if objective := task.get("objective"):
        lines.append(f"OBJECTIVE:{objective}")
    if spirit_anti := task.get("spirit_anti"):
        lines.append(f"SPIRIT_ANTI:{spirit_anti}")
    if done_when := task.get("done_when") or []:
        lines.append(f"DONE_WHEN[{len(done_when)}]:{' | '.join(done_when)}")
    return "\n".join(lines)


def format_subtask_context_subtask(subtask: dict[str, Any]) -> str:
    """Format subtask details with all steps and verification info."""
    subtask_id = subtask.get("subtask_id", "?")
    phase = subtask.get("phase") or ""
    passes = "PASS" if subtask.get("passes") else "____"
    desc = subtask.get("description") or ""
    lines = [f"SUBTASK:{subtask_id}|{phase}|{passes}", f"DESCRIPTION:{desc}"]
    steps = subtask.get("steps") or subtask.get("steps_from_table") or []
    if steps:
        done = sum(1 for s in steps if s.get("passes"))
        total = len(steps)
        pct = (done / total * 100) if total > 0 else 0
        lines.append(f"STEPS[{total}]:{done}/{total}:{pct:.0f}%")
        for step in steps:
            step_num = step.get("step_number", 0)
            step_pass = "PASS" if step.get("passes") else "____"
            lines.append(f"  {step_num}. {step_pass} {step.get('description') or ''}")
    return "\n".join(lines)


def format_subtask_context_dependencies(dependencies: list[dict[str, Any]]) -> str:
    """Format subtask dependencies with status."""
    if not dependencies:
        return ""
    lines = [f"DEPENDS_ON[{len(dependencies)}]"]
    for dep in dependencies:
        lines.append(f"  {dep.get('subtask_id', '?')} [{dep.get('status', 'PENDING')}]")
    return "\n".join(lines)
