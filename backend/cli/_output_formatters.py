"""Internal formatting logic for CLI output."""

from __future__ import annotations

from typing import Any


def truncate(s: str, length: int) -> str:
    """Truncate string to length, adding ... if truncated."""
    if len(s) <= length:
        return s
    return s[: length - 3] + "..."


def _safe_int(value: Any) -> int:
    """Convert value to int safely; returns 0 for non-numeric or invalid values."""
    if isinstance(value, (int, float)):
        return int(value)
    return 0


def format_compact_task(task: dict[str, Any]) -> str:
    """Format task as compact one-liner."""
    priority = task.get("priority", 3)
    task_id = task.get("id", "unknown")
    project_id = task.get("project_id") or ""
    task_type = (task.get("task_type") or "task")[:10].ljust(10)
    status = (task.get("status") or "pending")[:7].ljust(7)
    triage = "[TRIAGE] " if not task.get("objective") and not task.get("complexity") else ""
    title = truncate(task.get("title") or "", 50 - len(triage))
    return f"P{priority} {task_id} {project_id:12} {task_type} {status} {triage}{title}"


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


def _format_context_lines(context: dict[str, Any] | None) -> list[str]:
    """Build CONTEXT line parts from task context dict."""
    if not context or not isinstance(context, dict):
        return []
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
    if isinstance(second_opinion := context.get("second_opinion"), dict):
        stage = second_opinion.get("stage", "task_shape")
        status = second_opinion.get("status", "pending")
        parts.append(f"2nd:{stage}:{status}")
    return [f"CONTEXT:{' | '.join(parts)}"] if parts else []


def _format_specialist_group(group: dict[str, Any]) -> str | None:
    """Format a single specialist group entry; returns None for invalid groups."""
    if not isinstance(group, dict):
        return None
    agent_slug = str(group.get("agent_slug") or "unknown")
    count = _safe_int(group.get("count"))
    newest = _safe_int(group.get("newest_age_minutes"))
    oldest = _safe_int(group.get("oldest_age_minutes"))
    age_label = f"{newest}-{oldest}m" if newest != oldest else f"{oldest}m"
    segment = f"{agent_slug}:{count}:{age_label}"
    request_sources = group.get("request_sources")
    if isinstance(request_sources, list) and request_sources:
        segment += f":{','.join(str(s) for s in request_sources[:2])}"
    return segment


def _format_lane_lines(lane_preflight: dict[str, Any] | None) -> list[str]:
    """Build LANE and SPECIALISTS lines from lane_preflight."""
    if not isinstance(lane_preflight, dict):
        return []
    lines = []
    if lane_preflight.get("issues"):
        parts = []
        if disposition := lane_preflight.get("disposition"):
            parts.append(f"disp:{disposition}")
        if overlap_kind := lane_preflight.get("overlap_kind"):
            parts.append(f"kind:{overlap_kind}")
        conflicting_tasks = lane_preflight.get("conflicting_tasks") or []
        if conflicting_tasks:
            parts.append(f"tasks:{','.join(conflicting_tasks[:3])}")
        if owner_location := lane_preflight.get("owner_location"):
            parts.append(f"owner:{owner_location}")
        overlap_paths = lane_preflight.get("overlap_paths") or []
        if overlap_paths:
            parts.append(f"paths:{','.join(overlap_paths[:3])}")
        if lane_preflight.get("shared_plumbing"):
            parts.append("shared:yes")
        lines.append(f"LANE:{' | '.join(parts) if parts else 'conflict'}")
    specialist_groups = lane_preflight.get("active_specialists") or []
    if isinstance(specialist_groups, list) and specialist_groups:
        parts = [seg for g in specialist_groups[:3] if (seg := _format_specialist_group(g)) is not None]
        if parts:
            lines.append(f"SPECIALISTS:{' | '.join(parts)}")
    return lines


def format_context_task(task: dict[str, Any]) -> str:
    """Format task header for context output."""
    lines = []
    task_id = task.get("id", "unknown")
    status = task.get("status", "pending")
    priority = task.get("priority", 3)
    task_type = task.get("task_type", "task")
    complexity = task.get("complexity") or "SIMPLE"
    lines.append(f"TASK:{task_id}|{status}|P{priority}|{task_type}|{complexity}")
    if title := task.get("title"):
        lines.append(f"TITLE:{title}")
    if description := task.get("description"):
        lines.append(f"DESCRIPTION:{description}")
    decisions_count = len(task.get("decisions") or [])
    readiness = task.get("execution_readiness")
    plan_status = task.get("plan_status") or "draft"
    if decisions_count > 0 or readiness is not None or plan_status != "draft":
        ready_flag = "yes" if readiness and readiness.ready else "no"
        issues = len(readiness.issues) if readiness else 0
        lines.append(f"WORKFLOW:plan:{plan_status}|ready:{ready_flag}|issues:{issues}|decisions:{decisions_count}")
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
    if readiness and readiness.missing_fields:
        lines.append(f"READINESS:missing:{','.join(readiness.missing_fields)}")
    completion_readiness = task.get("completion_readiness")
    if isinstance(completion_readiness, dict):
        gates = completion_readiness.get("gates") or []
        if completion_readiness.get("ready"):
            lines.append("COMPLETE_READY:yes")
        else:
            gate_codes = [
                str(g.get("gate") or g.get("code") or "unknown")
                for g in gates
                if isinstance(g, dict)
            ]
            if gate_codes:
                lines.append(f"COMPLETE_READY:no|gates:{','.join(gate_codes)}")
    syncable = task.get("syncable_subtasks") or []
    if isinstance(syncable, list) and syncable:
        lines.append(f"SYNCABLE_SUBTASKS:{','.join(str(item) for item in syncable)}")
    skipped = task.get("syncable_subtasks_skipped") or []
    if isinstance(skipped, list) and skipped:
        lines.append(f"SYNC_SKIPS:{' | '.join(str(item) for item in skipped[:8])}")
    lines.extend(_format_context_lines(task.get("context")))
    lines.extend(_format_lane_lines(task.get("lane_preflight")))
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
