"""Internal formatting logic for CLI output."""

from __future__ import annotations

from typing import Any


def truncate(s: str, length: int) -> str:
    """Truncate string to length, adding ... if truncated."""
    if len(s) <= length:
        return s
    return s[: length - 3] + "..."


def format_compact_task(task: dict[str, Any]) -> str:
    """Format task as compact one-liner."""
    priority = task.get("priority", 3)
    task_id = task.get("id", "unknown")
    task_type = (task.get("task_type") or "task")[:10].ljust(10)
    status = (task.get("status") or "pending")[:7].ljust(7)
    title = truncate(task.get("title") or "", 50)
    return f"P{priority} {task_id} {task_type} {status} {title}"


def format_compact_subtask(subtask: dict[str, Any]) -> str:
    """Format subtask as compact one-liner."""
    subtask_id = subtask.get("subtask_id", "?")
    passes = "PASS" if subtask.get("passes") else "____"
    description = truncate(subtask.get("description") or "", 40)
    step_summary = subtask.get("step_summary", {})
    done = step_summary.get("completed", 0)
    total = step_summary.get("total", 0)
    return f"{subtask_id:5} {passes} {description:40} [{done}/{total}]"


def format_compact_step(step: dict[str, Any]) -> str:
    """Format step as compact one-liner."""
    step_num = step.get("step_number", 0)
    passes = "PASS" if step.get("passes") else "____"
    description = truncate(step.get("description") or "", 50)
    return f"{step_num:2} {passes} {description}"


def format_compact_dep(dep: dict[str, Any]) -> str:
    """Format dependency as compact one-liner."""
    from_id = dep.get("from_task_id", "?")
    to_id = dep.get("to_task_id", "?")
    dep_type = (dep.get("dependency_type") or "blocks")[:6].ljust(6)
    return f"{from_id} {dep_type} {to_id}"


def format_context_task(task: dict[str, Any]) -> str:
    """Format task header for context output."""
    lines = []
    task_id = task.get("id", "unknown")
    status = task.get("status", "pending")
    priority = task.get("priority", 3)
    task_type = task.get("task_type", "task")
    complexity = task.get("complexity") or "SIMPLE"
    lines.append(f"TASK:{task_id}|{status}|P{priority}|{task_type}|{complexity}")
    decisions_count = len(task.get("decisions") or [])
    lines.append(f"WORKFLOW:decisions:{decisions_count}")
    if objective := task.get("objective"):
        lines.append(f"OBJECTIVE:{objective}")
    if spirit_anti := task.get("spirit_anti"):
        lines.append(f"SPIRIT_ANTI:{spirit_anti}")
    constraints = task.get("constraints") or []
    if constraints:
        lines.append(f"CONSTRAINTS[{len(constraints)}]:{' | '.join(constraints)}")
    done_when = task.get("done_when") or []
    if done_when:
        lines.append(f"DONE_WHEN[{len(done_when)}]:{' | '.join(done_when)}")
    context = task.get("context") or {}
    if context:
        parts = []
        if files_mod := context.get("files_to_modify"):
            parts.append(f"modify:{','.join(files_mod)}")
        if files_create := context.get("files_to_create"):
            parts.append(f"create:{','.join(files_create)}")
        if risks := context.get("risks"):
            parts.append(f"risks:{len(risks)}")
        if refs := context.get("references"):
            parts.append(f"refs:{len(refs)}")
        if testing := context.get("testing_strategy"):
            parts.append(f"testing:{testing[:50]}")
        if parts:
            lines.append(f"CONTEXT:{' | '.join(parts)}")
    return "\n".join(lines)


def format_context_decisions(decisions: list[dict[str, Any]]) -> str:
    """Format decisions for context output."""
    if not decisions:
        return ""
    lines = [f"DECISIONS[{len(decisions)}]"]
    for d in decisions:
        d_id = d.get("id", "?")
        title = d.get("title", "")
        outcome = d.get("outcome", "")
        lines.append(f"{d_id}:{title}→{outcome}")
    return "\n".join(lines)


def format_context_subtasks(subtasks: list[dict[str, Any]]) -> str:
    """Format subtasks with steps inline for context output."""
    if not subtasks:
        return "SUBTASKS[0]:0/0:0%"
    done = sum(1 for s in subtasks if s.get("passes"))
    total = len(subtasks)
    pct = (done / total * 100) if total > 0 else 0
    lines = [f"SUBTASKS[{total}]:{done}/{total}:{pct:.0f}%"]
    for subtask in subtasks:
        subtask_id = subtask.get("subtask_id", "?")
        passes = "PASS" if subtask.get("passes") else "____"
        phase = subtask.get("phase") or ""
        desc = subtask.get("description") or ""
        step_summary = subtask.get("step_summary", {})
        step_done = step_summary.get("completed", 0)
        step_total = step_summary.get("total", 0)
        phase_prefix = f"[{phase}] " if phase else ""
        lines.append(f"{subtask_id:5} {passes} {phase_prefix}{desc} [{step_done}/{step_total}]")
        steps = subtask.get("steps") or subtask.get("steps_from_table") or []
        for step in steps:
            step_num = step.get("step_number", 0)
            step_pass = "PASS" if step.get("passes") else "____"
            step_desc = step.get("description") or ""
            lines.append(f"  {step_num}. {step_pass} {step_desc}")
            if verify_cmd := step.get("verify_command"):
                lines.append(f"       verify: {verify_cmd}")
            if expected_out := step.get("expected_output"):
                lines.append(f"       expect: {expected_out}")
    return "\n".join(lines)


def format_context_blockers(blockers: list[dict[str, Any]]) -> str:
    """Format blockers for context output."""
    if not blockers:
        return ""
    lines = [f"BLOCKERS[{len(blockers)}]"]
    for b in blockers:
        b_id = b.get("id", "?")
        status = b.get("status", "?")
        title = b.get("title") or ""
        lines.append(f"{b_id}|{status}|{title}")
    return "\n".join(lines)


def format_context_log(progress_log: list[str] | str | None) -> str:
    """Format progress log for context output (last 3 entries)."""
    if not progress_log:
        return ""
    if isinstance(progress_log, str):
        entries = [e.strip() for e in progress_log.split("\n") if e.strip()]
    else:
        entries = progress_log
    if not entries:
        return ""
    recent_logs = entries[-3:]
    lines = [f"LOG[{len(entries)}]"]
    for log in recent_logs:
        log_preview = str(log)[:100]
        if len(str(log)) > 100:
            log_preview += "..."
        lines.append(f"  {log_preview}")
    return "\n".join(lines)


def format_context_references(references: list[dict[str, Any]], header: str = "REFERENCES") -> str:
    """Format triggered references for context output."""
    if not references:
        return ""
    lines = [f"{header}[{len(references)}]"]
    for ref in references:
        uuid = ref.get("uuid", "?")[:8]
        summary = ref.get("summary") or truncate(ref.get("content", ""), 50)
        lines.append(f"  {uuid}:{summary}")
    return "\n".join(lines)


def format_subtask_context_task_summary(task: dict[str, Any]) -> str:
    """Format task summary for subtask-scoped context."""
    lines = []
    task_id = task.get("id", "unknown")
    title = task.get("title", "")
    lines.append(f"TASK:{task_id}|{title}")
    if objective := task.get("objective"):
        lines.append(f"OBJECTIVE:{objective}")
    if spirit_anti := task.get("spirit_anti"):
        lines.append(f"SPIRIT_ANTI:{spirit_anti}")
    done_when = task.get("done_when") or []
    if done_when:
        lines.append(f"DONE_WHEN[{len(done_when)}]:{' | '.join(done_when)}")
    return "\n".join(lines)


def format_subtask_context_subtask(subtask: dict[str, Any]) -> str:
    """Format subtask details with all steps and verification info."""
    lines = []
    subtask_id = subtask.get("subtask_id", "?")
    phase = subtask.get("phase") or ""
    passes = "PASS" if subtask.get("passes") else "____"
    desc = subtask.get("description") or ""
    lines.append(f"SUBTASK:{subtask_id}|{phase}|{passes}")
    lines.append(f"DESCRIPTION:{desc}")
    steps = subtask.get("steps") or subtask.get("steps_from_table") or []
    if steps:
        done = sum(1 for s in steps if s.get("passes"))
        total = len(steps)
        pct = (done / total * 100) if total > 0 else 0
        lines.append(f"STEPS[{total}]:{done}/{total}:{pct:.0f}%")
        for step in steps:
            step_num = step.get("step_number", 0)
            step_pass = "PASS" if step.get("passes") else "____"
            step_desc = step.get("description") or ""
            lines.append(f"  {step_num}. {step_pass} {step_desc}")
            if verify_cmd := step.get("verify_command"):
                lines.append(f"       verify: {verify_cmd}")
            if expected_out := step.get("expected_output"):
                lines.append(f"       expect: {expected_out}")
    return "\n".join(lines)


def format_subtask_context_dependencies(dependencies: list[dict[str, Any]]) -> str:
    """Format subtask dependencies with status."""
    if not dependencies:
        return ""
    lines = [f"DEPENDS_ON[{len(dependencies)}]"]
    for dep in dependencies:
        dep_id = dep.get("subtask_id", "?")
        status = dep.get("status", "PENDING")
        lines.append(f"  {dep_id} [{status}]")
    return "\n".join(lines)
