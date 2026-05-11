"""Task header formatter for task context output."""

from __future__ import annotations

from typing import Any, cast

from app.services.task_context_guardrails import format_task_freshness_lines
from app.services.task_continuity import format_continuity_lines
from app.services.task_execution_readiness import is_final_task_status
from app.services.task_harness import summarize_execution_contract

from ._formatters_compact import _safe_int


def _format_context_lines(
    context: dict[str, Any] | None,
    *,
    include_execution_metadata: bool = True,
) -> list[str]:
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
        parts.append(f"testing:{str(testing)[:50]}")
    second_opinion = context.get("second_opinion")
    if include_execution_metadata and isinstance(second_opinion, dict):
        stage = second_opinion.get("stage", "task_shape")
        status = second_opinion.get("status", "pending")
        parts.append(f"2nd:advisory:{stage}:{status}")
    return [f"CONTEXT:{' | '.join(parts)}"] if parts else []


def _format_contract_line(context: dict[str, Any] | None) -> str | None:
    if not isinstance(context, dict):
        return None
    summary = summarize_execution_contract(context.get("execution_contract"))
    has_contract = any(
        summary[key] > 0
        for key in (
            "target_url_count",
            "user_flow_count",
            "api_check_count",
            "negative_case_count",
        )
    ) or summary["has_design_criteria"]
    if not has_contract:
        return None
    design_flag = "yes" if summary["has_design_criteria"] else "no"
    return (
        "CONTRACT:"
        f"urls={summary['target_url_count']}|"
        f"flows={summary['user_flow_count']}|"
        f"api={summary['api_check_count']}|"
        f"negative={summary['negative_case_count']}|"
        f"design={design_flag}"
    )


def _format_harness_line(task: dict[str, Any]) -> str | None:
    route = task.get("harness_route")
    if not isinstance(route, dict):
        return None
    mode = str(route.get("mode") or "code_only")
    reasons = route.get("reasons") or []
    reason_text = ",".join(str(reason) for reason in reasons if reason)
    return f"HARNESS:{mode}|reasons:{reason_text}" if reason_text else f"HARNESS:{mode}"


def _format_specialist_group(group: object) -> str | None:
    """Format a single specialist group entry; returns None for invalid groups."""
    if not isinstance(group, dict):
        return None
    group_data = cast(dict[str, Any], group)
    agent_slug = str(group_data.get("agent_slug") or "unknown")
    count = _safe_int(group_data.get("count"))
    newest = _safe_int(group_data.get("newest_age_minutes"))
    oldest = _safe_int(group_data.get("oldest_age_minutes"))
    age_label = f"{newest}-{oldest}m" if newest != oldest else f"{oldest}m"
    segment = f"{agent_slug}:{count}:{age_label}"
    request_sources = group_data.get("request_sources")
    if isinstance(request_sources, list) and request_sources:
        segment += f":{','.join(str(s) for s in request_sources[:2])}"
    return segment


def _format_lane_lines(lane_preflight: dict[str, Any] | None) -> list[str]:
    """Build LANE and SPECIALISTS lines from lane_preflight."""
    if not isinstance(lane_preflight, dict):
        return []
    lines: list[str] = []
    if lane_preflight.get("issues") and lane_preflight.get("disposition") != "warn":
        lines.append(_format_lane_conflict(lane_preflight))
    specialist_groups = lane_preflight.get("active_specialists") or []
    if isinstance(specialist_groups, list) and specialist_groups:
        parts = [
            seg
            for group in specialist_groups[:3]
            if (seg := _format_specialist_group(group)) is not None
        ]
        if parts:
            lines.append(f"SPECIALISTS:{' | '.join(parts)}")
    return lines


def _format_lane_conflict(lane_preflight: dict[str, Any]) -> str:
    """Build the LANE line from lane_preflight issues."""
    parts: list[str] = []
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
    return f"LANE:{' | '.join(parts) if parts else 'conflict'}"


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


def _format_verification_summary(verify: object) -> str | None:
    if not isinstance(verify, dict) or not verify:
        return None
    data = cast(dict[str, Any], verify)
    for key in ("execution_clean", "all_verified", "partial_merge"):
        if key in data:
            return f"{key}={str(data[key]).lower()}"
    return f"keys={','.join(str(k) for k in list(data.keys())[:3])}"


def _format_runtime_line(task: dict[str, Any]) -> str | None:
    """Surface operational fields that diverge from the visible status.

    Investigations like 'stuck-after-success' need current_phase, verification_result,
    and error_message at a glance — without these, agents drop to raw DB queries.
    """
    parts: list[str] = []
    status = str(task.get("status") or "")
    phase = str(task.get("current_phase") or "")
    expected_phase = {"pending": "plan", "running": "execute", "completed": "complete"}
    if phase and phase != expected_phase.get(status):
        parts.append(f"phase={phase}")
    if verify_summary := _format_verification_summary(task.get("verification_result")):
        parts.append(f"verify={verify_summary}")
    if err := task.get("error_message"):
        parts.append(f"err={str(err)[:80]}")
    return f"RUNTIME:{' | '.join(parts)}" if parts else None


def _format_workflow_line(task: dict[str, Any]) -> str | None:
    """Return WORKFLOW line if there's anything worth showing."""
    if is_final_task_status(task.get("status")):
        return None
    decisions_count = len(task.get("decisions") or [])
    readiness = task.get("execution_readiness")
    plan_status = task.get("plan_status") or "draft"
    if not (decisions_count > 0 or readiness is not None or plan_status != "draft"):
        return None
    ready_flag = "yes" if readiness and readiness.ready else "no"
    issues = len(readiness.issues) if readiness else 0
    return f"WORKFLOW:plan:{plan_status}|ready:{ready_flag}|issues:{issues}|decisions:{decisions_count}"


def _format_completion_readiness(completion_readiness: object) -> str | None:
    """Return COMPLETE_READY line if relevant."""
    if not isinstance(completion_readiness, dict):
        return None
    readiness_data = cast(dict[str, Any], completion_readiness)
    if readiness_data.get("ready"):
        return "COMPLETE_READY:yes"
    gates = readiness_data.get("gates") or []
    gate_codes = [
        str(g.get("gate") or g.get("code") or "unknown")
        for g in gates
        if isinstance(g, dict)
    ]
    return f"COMPLETE_READY:no|gates:{','.join(gate_codes)}" if gate_codes else None


def _format_archived_line(task: dict[str, Any]) -> str | None:
    if not task.get("archived"):
        return None
    deleted_at = task.get("deleted_at") or "unknown"
    deletion_source = task.get("deletion_source") or "unknown"
    archived_line = f"ARCHIVED:deleted_at:{deleted_at} | source:{deletion_source}"
    if deletion_reason := task.get("deletion_reason"):
        archived_line += f" | reason:{deletion_reason}"
    return archived_line


def _format_identity_lines(task: dict[str, Any], status: object) -> list[str]:
    priority = task.get("priority", 3)
    task_id = task.get("id", "unknown")
    task_type = task.get("task_type", "task")
    complexity = task.get("complexity") or "SIMPLE"
    lines = [f"TASK:{task_id}|{status}|P{priority}|{task_type}|{complexity}"]
    if title := task.get("title"):
        lines.append(f"TITLE:{title}")
    if description := task.get("description"):
        lines.append(f"DESCRIPTION:{description}")
    if archived_line := _format_archived_line(task):
        lines.append(archived_line)
    return lines


def _format_continuity_or_objective_lines(task: dict[str, Any]) -> list[str]:
    continuity = task.get("continuity")
    if isinstance(continuity, dict):
        return format_continuity_lines(continuity)
    if objective := task.get("objective"):
        return [f"OBJECTIVE:{objective}"]
    return []


def _format_body_lines(task: dict[str, Any], *, final_status: bool) -> list[str]:
    lines = _format_continuity_or_objective_lines(task)
    if spirit_anti := task.get("spirit_anti"):
        lines.append(f"SPIRIT_ANTI:{spirit_anti}")
    if constraints := task.get("constraints") or []:
        lines.append(f"CONSTRAINTS[{len(constraints)}]:{' | '.join(constraints)}")
    if done_when := task.get("done_when") or []:
        lines.append(f"DONE_WHEN[{len(done_when)}]:{' | '.join(done_when)}")
    readiness = task.get("execution_readiness")
    if not final_status and readiness and readiness.missing_fields:
        lines.append(f"READINESS:missing:{','.join(readiness.missing_fields)}")
    return lines


def _format_sync_lines(task: dict[str, Any]) -> list[str]:
    lines: list[str] = []
    syncable = task.get("syncable_subtasks") or []
    if isinstance(syncable, list) and syncable:
        lines.append(f"SYNCABLE_SUBTASKS:{','.join(str(item) for item in syncable)}")
    if skipped := _visible_sync_skips(task):
        lines.append(f"SYNC_SKIPS:{' | '.join(skipped[:8])}")
    return lines


def format_context_task(task: dict[str, Any]) -> str:
    """Format task header for context output."""
    status = task.get("status", "pending")
    final_status = is_final_task_status(status)
    lines = _format_identity_lines(task, status)
    lines.extend(format_task_freshness_lines(status))
    if workflow := _format_workflow_line(task):
        lines.append(workflow)
    if runtime := _format_runtime_line(task):
        lines.append(runtime)
    if harness := _format_harness_line(task):
        lines.append(harness)
    lines.extend(_format_body_lines(task, final_status=final_status))
    if cr_line := _format_completion_readiness(task.get("completion_readiness")):
        lines.append(cr_line)
    lines.extend(_format_sync_lines(task))
    lines.extend(
        _format_context_lines(
            task.get("context"),
            include_execution_metadata=not final_status,
        )
    )
    if contract_line := _format_contract_line(task.get("context")):
        lines.append(contract_line)
    lines.extend(_format_lane_lines(task.get("lane_preflight")))
    return "\n".join(lines)
