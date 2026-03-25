"""Prompt template management and building."""

from __future__ import annotations

from typing import Any

from ....logging_config import get_logger
from ....services.context_gatherer import (
    PRECISION_CODE_SEARCH_GUIDANCE,
    collect_precision_code_search_context,
)
from ....services.task_harness import estimate_prompt_tokens, summarize_execution_contract
from ....storage import tasks as task_store
from ....storage.events import get_events_by_trace
from ....storage.subtasks import get_handoff_context
from ....storage.task_spirit import get_task_spirit
from ...autonomous.pickup_guards import check_system_health
from ._prompt_blocks import (
    EVENTS_FETCH_LIMIT,
    FEEDBACK_PROMPT,
    MAX_PRIOR_ERRORS,
    build_failures_block,
    build_steps_block,
    classify_events,
)
from ._prompt_fetch import PromptFetchError, TransientPromptFetchError, get_prompt_template

logger = get_logger(__name__)

_SLUG_AUTOCODE_SUBTASK = "autocode-subtask"
_SLUG_AUTOCODE_FIX = "autocode-fix"
_TRANSIENT_SUBTASK_TEMPLATE = """# Task Objective
{objective}{spirit_anti_block}{done_when_block}{scope_block}{contract_block}{handoff_block}

# Subtask {subtask_id}
{description}

# Steps
{steps_block}

# Working Directory
{project_path}

Preserve existing behavior. Keep the scope tight to this subtask and run the relevant verification before finishing."""
_TRANSIENT_FIX_TEMPLATE = """The previous attempt did not satisfy verification for subtask {subtask_id}: {description}

{failures_block}{supervisor_block}

# Steps
{steps_block}

Revise the implementation in place. Address the failed steps directly without broadening scope, then rerun the relevant verification before finishing."""


def _get_template_with_transient_fallback(slug: str, fallback_template: str) -> str:
    try:
        return get_prompt_template(slug)
    except TransientPromptFetchError as e:
        logger.warning(
            "prompt_template_fallback",
            slug=slug,
            error=str(e),
        )
        return fallback_template
    except PromptFetchError:
        raise


def build_health_context(project_id: str) -> str:
    """Build system health summary for agent prompt context."""
    try:
        health_error = check_system_health(project_id)
        if health_error is None:
            return ""
        details = health_error.get("details", {})
        failing = health_error.get("failing_services", [])
        lines = ["## System Health Warning"]
        for service, _status in details.items():
            indicator = "unhealthy" if service in failing else "healthy"
            lines.append(f"- {service}: {indicator}")
        lines.append("")
        lines.append("Some services are degraded. Avoid operations that depend on unhealthy services.")
        return "\n".join(lines)
    except Exception:
        logger.debug("Failed to build health context", exc_info=True)
        return ""


def build_resume_context(task_id: str) -> str:
    """Build continuity context for a resumed task.

    Returns empty string if no prior execution history exists.
    """
    try:
        events = get_events_by_trace(task_id, limit=EVENTS_FETCH_LIMIT)
        if not events:
            return ""
        wind_down_msgs, error_msgs = classify_events(events)
        if not wind_down_msgs and not error_msgs:
            return ""
        lines = ["\n# Resume Context (prior execution)"]
        if wind_down_msgs:
            lines.extend(["Last session state:", wind_down_msgs[-1]])
        if error_msgs:
            lines.append(f"\nPrior failures ({len(error_msgs)}):")
            lines.extend(f"- {msg}" for msg in error_msgs[-MAX_PRIOR_ERRORS:])
        lines.append("\nApproach this with a fresh perspective based on the above history.")
        return "\n".join(lines)
    except Exception as e:
        logger.debug("Failed to build resume context", error=str(e))
        return ""


def build_conflict_context(task_id: str) -> str:
    """Build merge-conflict context for reopened residue tasks."""
    try:
        task = task_store.get_task(task_id)
        if not task:
            return ""
        conflict_info = task.get("conflict_info")
        if not isinstance(conflict_info, dict) or not conflict_info:
            return ""
        files = conflict_info.get("conflicting_files") or []
        lines = [
            "\n# Merge Conflict Context",
            "This task previously passed verification but failed to merge cleanly into the current main branch.",
            "Resolve the conflict in this existing task worktree, preserve the task intent, and rerun the relevant verification.",
        ]
        if files:
            lines.append("Conflicting files:")
            lines.extend(f"- {path}" for path in files[:10])
        task_branch = conflict_info.get("task_branch")
        base_branch = conflict_info.get("base_branch")
        if task_branch or base_branch:
            lines.append(f"Branch: {task_branch or 'task branch'} -> {base_branch or 'main'}")
        error_output = str(conflict_info.get("error_output") or "").strip()
        if error_output:
            lines.append(f"Git reported: {error_output[:300]}")
        return "\n".join(lines)
    except Exception as e:
        logger.debug("Failed to build conflict context", error=str(e))
        return ""


def _build_spirit_block(spirit_anti: str) -> str:
    if not spirit_anti:
        return ""
    return f"\n# Guiding Principles\n{spirit_anti}"


def _build_done_when_block(done_when: list[Any]) -> str:
    items = [str(item).strip() for item in done_when if str(item).strip()]
    if not items:
        return ""
    lines = ["\n# Completion Criteria"]
    lines.extend(f"- {item}" for item in items)
    return "\n".join(lines)


def _build_scope_block(context: dict[str, Any]) -> str:
    if not isinstance(context, dict):
        return ""
    files_to_modify = [str(path).strip() for path in context.get("files_to_modify", []) if str(path).strip()]
    files_to_create = [str(path).strip() for path in context.get("files_to_create", []) if str(path).strip()]
    risks = [str(item).strip() for item in context.get("risks", []) if str(item).strip()]
    if not files_to_modify and not files_to_create and not risks:
        return ""
    lines = ["\n# Expected Scope"]
    if files_to_modify:
        lines.append("Existing files to modify:")
        lines.extend(f"- {path}" for path in files_to_modify)
    if files_to_create:
        lines.append("Files to create:")
        lines.extend(f"- {path}" for path in files_to_create)
    if risks:
        lines.append("Known risks:")
        lines.extend(f"- {item}" for item in risks)
    return "\n".join(lines)


def _build_handoff_block(handoff: dict[str, Any]) -> str:
    previous_summaries = handoff.get("previous_summaries")
    if not previous_summaries:
        return ""
    lines = ["\n# Previous Work Summary"]
    lines.extend(f"- Subtask {s['short_id']}: {s['summary']}" for s in previous_summaries)
    return "\n".join(lines)


def _build_execution_contract_block(context: dict[str, Any]) -> str:
    if not isinstance(context, dict):
        return ""
    contract = context.get("execution_contract")
    summary = summarize_execution_contract(contract)
    if summary["target_url_count"] == 0 and summary["user_flow_count"] == 0 and summary["api_check_count"] == 0 and summary["negative_case_count"] == 0 and not summary["has_design_criteria"]:
        return ""

    contract = contract if isinstance(contract, dict) else {}
    lines = [f"\n# Execution Contract\nMode: {summary['mode']}"]
    target_urls = contract.get("target_urls") or []
    if target_urls:
        lines.append("Target URLs:")
        lines.extend(f"- {url}" for url in target_urls)
    user_flows = contract.get("user_flows") or []
    if user_flows:
        lines.append("User flows:")
        for flow in user_flows:
            title = flow.get("title", "Flow")
            lines.append(f"- {title}")
            actions = flow.get("actions") or []
            expected = flow.get("expected_outcomes") or []
            if actions:
                lines.append(f"  actions: {'; '.join(str(action) for action in actions)}")
            if expected:
                lines.append(f"  expect: {'; '.join(str(item) for item in expected)}")
    api_checks = contract.get("api_checks") or []
    if api_checks:
        lines.append("API checks:")
        for check in api_checks:
            lines.append(
                f"- {check.get('method', 'GET')} {check.get('path', '')} -> {check.get('status', '?')}"
            )
    negative_cases = contract.get("negative_cases") or []
    if negative_cases:
        lines.append("Negative cases:")
        for case in negative_cases:
            title = case.get("title") or case.get("path") or "Negative case"
            lines.append(f"- {title} -> {case.get('status', '?')}")
    if summary["has_design_criteria"]:
        lines.append("Design critic: required")
    risk_notes = contract.get("risk_notes") or []
    if risk_notes:
        lines.append("Evaluator focus:")
        lines.extend(f"- {note}" for note in risk_notes)
    return "\n".join(lines)


def _build_precision_code_search_block(
    project_id: str,
    objective: str,
    subtask: dict[str, Any],
) -> str:
    steps = _get_subtask_steps(subtask)
    queries = [
        objective,
        str(subtask.get("description", "")),
        *(str(step.get("description", "")) for step in steps),
    ]
    result = collect_precision_code_search_context(
        project_id,
        queries,
        budget_tokens=1500,
    )
    if not result.prompt_context:
        return ""
    return (
        f"\n# Precision Code Search\n{result.prompt_context}\n\n"
        f"{PRECISION_CODE_SEARCH_GUIDANCE}"
    )


def _get_subtask_steps(subtask: dict[str, Any]) -> list[dict[str, Any]]:
    steps_from_table = subtask.get("steps_from_table")
    if isinstance(steps_from_table, list) and steps_from_table:
        return steps_from_table
    steps = subtask.get("steps")
    if isinstance(steps, list):
        return steps
    return []


def _build_snapshot_sections(
    objective: str,
    done_when_block: str,
    scope_block: str,
    contract_block: str,
    handoff_block: str,
    subtask: dict[str, Any],
    project_path: str,
) -> list[dict[str, Any]]:
    sections: list[tuple[str, str]] = [
        ("Task Objective", objective),
        ("Completion Criteria", done_when_block),
        ("Expected Scope", scope_block),
        ("Execution Contract", contract_block),
        ("Previous Work Summary", handoff_block),
        ("Subtask", subtask.get("description", "")),
        ("Steps", build_steps_block(_get_subtask_steps(subtask))),
        ("Working Directory", project_path),
    ]
    return [
        {
            "label": label,
            "estimated_tokens": estimate_prompt_tokens(content),
        }
        for label, content in sections
        if content
    ]


def build_subtask_prompt_payload(
    task_id: str,
    subtask: dict[str, Any],
    project_id: str,
    project_path: str,
) -> tuple[str, dict[str, Any]]:
    """Build subtask prompt plus a compact prompt-composition snapshot."""
    spirit = get_task_spirit(task_id)
    done_when = spirit.get("done_when", []) if spirit else []
    context = spirit.get("context", {}) if spirit else {}
    subtask_short_id = subtask.get("subtask_id", "")
    handoff = get_handoff_context(task_id, subtask_short_id)

    task = task_store.get_task(task_id)
    objective = (task.get("description") or task.get("title") or "") if task else ""
    done_when_block = _build_done_when_block(done_when)
    scope_block = _build_scope_block(context)
    contract_block = _build_execution_contract_block(context)
    handoff_block = _build_handoff_block(handoff)
    steps_block = build_steps_block(_get_subtask_steps(subtask))

    template = _get_template_with_transient_fallback(
        _SLUG_AUTOCODE_SUBTASK,
        _TRANSIENT_SUBTASK_TEMPLATE,
    )
    prompt = template.format_map({
        "objective": objective,
        "spirit_anti_block": "",
        "done_when_block": done_when_block,
        "scope_block": scope_block,
        "contract_block": contract_block,
        "handoff_block": handoff_block,
        "subtask_id": subtask_short_id,
        "description": subtask.get("description", ""),
        "steps_block": steps_block,
        "project_path": project_path,
    })

    snapshot_sections = _build_snapshot_sections(
        objective,
        done_when_block,
        scope_block,
        contract_block,
        handoff_block,
        subtask,
        project_path,
    )

    precision_block = _build_precision_code_search_block(project_id, objective, subtask)
    if precision_block:
        prompt += precision_block
        snapshot_sections.append(
            {"label": "Precision Code Search", "estimated_tokens": estimate_prompt_tokens(precision_block)}
        )

    resume_block = build_resume_context(task_id)
    if resume_block:
        prompt += resume_block
        snapshot_sections.append(
            {"label": "Resume Context", "estimated_tokens": estimate_prompt_tokens(resume_block)}
        )
    conflict_block = build_conflict_context(task_id)
    if conflict_block:
        prompt += conflict_block
        snapshot_sections.append(
            {"label": "Merge Conflict Context", "estimated_tokens": estimate_prompt_tokens(conflict_block)}
        )
    health_block = build_health_context(project_id)
    if health_block:
        prompt += f"\n\n{health_block}"
        snapshot_sections.append(
            {"label": "System Health Warning", "estimated_tokens": estimate_prompt_tokens(health_block)}
        )

    return prompt, {
        "mode": summarize_execution_contract(context.get("execution_contract")).get("mode", "code_only"),
        "sections": snapshot_sections,
        "execution_contract": summarize_execution_contract(context.get("execution_contract")),
    }


def build_subtask_prompt(
    task_id: str,
    subtask: dict[str, Any],
    project_id: str,
    project_path: str,
) -> str:
    """Build subtask prompt with fresh context: description + done_when + subtask + handoff."""
    prompt, _snapshot = build_subtask_prompt_payload(task_id, subtask, project_id, project_path)
    return prompt


def _summarize_failure(step_results: list[dict[str, Any]]) -> str:
    """Extract a concise failure reason from step results."""
    failed = [r for r in step_results if not r.get("passed")]
    if not failed:
        return "no failure details"
    reasons = []
    for f in failed[:3]:
        reason = f.get("reason") or f.get("error") or "unknown"
        reasons.append(str(reason)[:100])
    return "; ".join(reasons)


def _format_subtask_result_line(r: dict[str, Any]) -> str:
    """Format a single subtask result with failure context when applicable."""
    subtask_id = r.get("subtask_id", "?")
    status = r.get("status", "unknown")
    total_attempts = 1 + r.get("self_fix_attempts", 0) + r.get("supervisor_guided_attempts", 0)
    line = f"- Subtask {subtask_id}: {status} ({total_attempts} attempts)"

    if status != "passed":
        step_results = r.get("step_results", [])
        failure_reason = _summarize_failure(step_results) if step_results else (
            r.get("error") or r.get("message") or "no details available"
        )
        line += f"\n  Failure: {failure_reason}"
        # Surface affected area from failed steps
        failed_steps = [s for s in step_results if not s.get("passed")]
        if failed_steps:
            step_ids = [str(s.get("step_number", "?")) for s in failed_steps[:5]]
            line += f"\n  Affected steps: {', '.join(step_ids)}"
        line += "\n  Next: investigate failure root cause, then re-run or adjust approach"

    return line


def build_feedback_prompt(results: list[dict[str, Any]], feedback_session_id: str) -> str:
    """Build a feedback prompt with task execution summary."""
    parts = [_format_subtask_result_line(r) for r in results]
    task_summary = "\n".join(parts) if parts else "No subtask results"
    return FEEDBACK_PROMPT.format(
        task_summary=task_summary,
        feedback_session_id=feedback_session_id,
    )


def build_fix_prompt(
    subtask: dict[str, Any],
    failed_steps: list[dict[str, Any]],
    previous_response: str,
    supervisor_guidance: str | None = None,
) -> str:
    """Build a fix prompt with error context for self-healing."""
    supervisor_block = f"\n## Supervisor Guidance\n{supervisor_guidance}" if supervisor_guidance else ""
    template = _get_template_with_transient_fallback(
        _SLUG_AUTOCODE_FIX,
        _TRANSIENT_FIX_TEMPLATE,
    )
    return template.format_map({
        "subtask_id": subtask.get("subtask_id", ""),
        "description": subtask.get("description", ""),
        "failures_block": build_failures_block(failed_steps),
        "supervisor_block": supervisor_block,
        "steps_block": build_steps_block(_get_subtask_steps(subtask)),
    })
