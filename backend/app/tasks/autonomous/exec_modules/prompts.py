"""Prompt template management and building."""

from __future__ import annotations

from typing import Any

from ....logging_config import get_logger
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
{objective}{spirit_anti_block}{handoff_block}

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


def _build_spirit_block(spirit_anti: str) -> str:
    if not spirit_anti:
        return ""
    return f"\n# Guiding Principles\n{spirit_anti}"


def _build_handoff_block(handoff: dict[str, Any]) -> str:
    previous_summaries = handoff.get("previous_summaries")
    if not previous_summaries:
        return ""
    lines = ["\n# Previous Work Summary"]
    lines.extend(f"- Subtask {s['short_id']}: {s['summary']}" for s in previous_summaries)
    return "\n".join(lines)


def build_subtask_prompt(
    task_id: str,
    subtask: dict[str, Any],
    project_id: str,
    project_path: str,
) -> str:
    """Build subtask prompt with fresh context: objective + spirit/anti + subtask + handoff."""
    spirit = get_task_spirit(task_id)
    objective = spirit.get("objective", "") if spirit else ""
    spirit_anti = spirit.get("spirit_anti", "") if spirit else ""
    subtask_short_id = subtask.get("subtask_id", "")
    handoff = get_handoff_context(task_id, subtask_short_id)

    template = _get_template_with_transient_fallback(
        _SLUG_AUTOCODE_SUBTASK,
        _TRANSIENT_SUBTASK_TEMPLATE,
    )
    prompt = template.format_map({
        "objective": objective,
        "spirit_anti_block": _build_spirit_block(spirit_anti),
        "handoff_block": _build_handoff_block(handoff),
        "subtask_id": subtask_short_id,
        "description": subtask.get("description", ""),
        "steps_block": build_steps_block(subtask.get("steps_from_table", [])),
        "project_path": project_path,
    })

    resume_block = build_resume_context(task_id)
    if resume_block:
        prompt += resume_block
    health_block = build_health_context(project_id)
    if health_block:
        prompt += f"\n\n{health_block}"
    return prompt


def build_feedback_prompt(results: list[dict[str, Any]]) -> str:
    """Build a feedback prompt with task execution summary."""
    parts = [
        f"- Subtask {r.get('subtask_id', '?')}: {r.get('status', 'unknown')} "
        f"({1 + r.get('self_fix_attempts', 0) + r.get('supervisor_guided_attempts', 0)} attempts)"
        for r in results
    ]
    task_summary = "\n".join(parts) if parts else "No subtask results"
    return FEEDBACK_PROMPT.format(task_summary=task_summary)


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
        "steps_block": build_steps_block(subtask.get("steps_from_table", [])),
    })
