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
    step_summary = subtask.get("step_summary") or {}
    done = _safe_int(step_summary.get("completed", 0))
    total = _safe_int(step_summary.get("total", 0))
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
    parts: list[str] = []
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


def _format_specialist_group(group: Any) -> str | None:
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


def _format_lane_conflict(lane_preflight: dict[str, Any]) -> str:
    """Build the LANE or LANE_ADVISORY line from lane_preflight issues."""
    parts: list[str] = []
    disposition = lane_preflight.get("disposition")
    if disposition:
        parts.append(f"disp:{disposition}")
    if overlap_kind := lane_preflight.get("overlap_kind"):
        parts.append(f"kind:{overlap_kind}")
    conflicting_tasks = lane_preflight.get("conflicting_tasks") or []
    if conflicting_tasks:
        key = "active_tasks" if disposition == "warn" else "tasks"
        parts.append(f"{key}:{','.join(conflicting_tasks[:3])}")
    if owner_location := lane_preflight.get("owner_location"):
        parts.append(f"owner:{owner_location}")
    overlap_paths = lane_preflight.get("overlap_paths") or []
    if overlap_paths:
        parts.append(f"paths:{','.join(overlap_paths[:3])}")
    if lane_preflight.get("shared_plumbing"):
        parts.append("shared:yes")
    label = "LANE_ADVISORY" if disposition == "warn" else "LANE"
    return f"{label}:{' | '.join(parts) if parts else 'conflict'}"


def _format_lane_lines(lane_preflight: dict[str, Any] | None) -> list[str]:
    """Build LANE and SPECIALISTS lines from lane_preflight."""
    if not isinstance(lane_preflight, dict):
        return []
    lines: list[str] = []
    if lane_preflight.get("issues"):
        lines.append(_format_lane_conflict(lane_preflight))
    specialist_groups = lane_preflight.get("active_specialists") or []
    if isinstance(specialist_groups, list) and specialist_groups:
        parts = [seg for g in specialist_groups[:3] if (seg := _format_specialist_group(g)) is not None]
        if parts:
            lines.append(f"SPECIALISTS:{' | '.join(parts)}")
    return lines


def _visible_sync_skips(task: dict[str, Any]) -> list[str]:
    """Return sync skips worth surfacing in context output."""
    skipped = task.get("syncable_subtasks_skipped") or []
    if not isinstance(skipped, list):
        return []
    syncable = task.get("syncable_subtasks") or []
    if isinstance(syncable, list) and syncable:
        return [str(item) for item in skipped]
    status = str(task.get("status") or "")
    if status == "pending":
        return [str(item) for item in skipped if ":steps-" not in str(item)]
    return [str(item) for item in skipped]


def _format_workflow_line(task: dict[str, Any]) -> str | None:
    """Return WORKFLOW line if there's anything worth showing."""
    decisions_count = len(task.get("decisions") or [])
    readiness = task.get("execution_readiness")
    plan_status = task.get("plan_status") or "draft"
    if not (decisions_count > 0 or readiness is not None or plan_status != "draft"):
        return None
    ready_flag = "yes" if readiness and readiness.ready else "no"
    issues = len(readiness.issues) if readiness else 0
    return f"WORKFLOW:plan:{plan_status}|ready:{ready_flag}|issues:{issues}|decisions:{decisions_count}"


def _format_completion_readiness(completion_readiness: Any) -> str | None:
    """Return COMPLETE_READY line if relevant."""
    if not isinstance(completion_readiness, dict):
        return None
    if completion_readiness.get("ready"):
        return "COMPLETE_READY:yes"
    gates = completion_readiness.get("gates") or []
    gate_codes = [
        str(g.get("gate") or g.get("code") or "unknown")
        for g in gates
        if isinstance(g, dict)
    ]
    return f"COMPLETE_READY:no|gates:{','.join(gate_codes)}" if gate_codes else None


def format_context_task(task: dict[str, Any]) -> str:
    """Format task header for context output."""
    task_id = task.get("id", "unknown")
    status = task.get("status", "pending")
    priority = task.get("priority", 3)
    task_type = task.get("task_type", "task")
    complexity = task.get("complexity") or "SIMPLE"
    lines = [f"TASK:{task_id}|{status}|P{priority}|{task_type}|{complexity}"]
    if title := task.get("title"):
        lines.append(f"TITLE:{title}")
    if description := task.get("description"):
        lines.append(f"DESCRIPTION:{description}")
    if workflow := _format_workflow_line(task):
        lines.append(workflow)
    if objective := task.get("objective"):
        lines.append(f"OBJECTIVE:{objective}")
    if spirit_anti := task.get("spirit_anti"):
        lines.append(f"SPIRIT_ANTI:{spirit_anti}")
    if constraints := task.get("constraints") or []:
        lines.append(f"CONSTRAINTS[{len(constraints)}]:{' | '.join(constraints)}")
    if done_when := task.get("done_when") or []:
        lines.append(f"DONE_WHEN[{len(done_when)}]:{' | '.join(done_when)}")
    readiness = task.get("execution_readiness")
    if readiness and readiness.missing_fields:
        lines.append(f"READINESS:missing:{','.join(readiness.missing_fields)}")
    if cr_line := _format_completion_readiness(task.get("completion_readiness")):
        lines.append(cr_line)
    syncable = task.get("syncable_subtasks") or []
    if isinstance(syncable, list) and syncable:
        lines.append(f"SYNCABLE_SUBTASKS:{','.join(str(item) for item in syncable)}")
    if skipped := _visible_sync_skips(task):
        lines.append(f"SYNC_SKIPS:{' | '.join(skipped[:8])}")
    lines.extend(_format_context_lines(task.get("context")))
    lines.extend(_format_lane_lines(task.get("lane_preflight")))
    return "\n".join(lines)


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
    entries = [e.strip() for e in progress_log.split("\n") if e.strip()] if isinstance(progress_log, str) else progress_log
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
        uuid = ref.get("uuid", "?")[:8]
        summary = ref.get("summary") or truncate(ref.get("content", ""), 50)
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
        # Show just date+time, trim microseconds
        ts = str(created_at)[:19]
        lines[0] += f"|since:{ts}"
    if base_branch := snapshot.get("base_branch"):
        lines.append(f"BASE_BRANCH:{base_branch}")
    if worktree_path := snapshot.get("worktree_path"):
        lines.append(f"WORKTREE_PATH:{worktree_path}")
    if worktree_branch := snapshot.get("worktree_branch"):
        lines.append(f"TASK_BRANCH:{worktree_branch}")
    ports: list[str] = []
    if bp := snapshot.get("backend_port"):
        ports.append(f"backend:{bp}")
    if fp := snapshot.get("frontend_port"):
        ports.append(f"frontend:{fp}")
    if ports:
        lines.append(f"PORTS:{' | '.join(ports)}")
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
