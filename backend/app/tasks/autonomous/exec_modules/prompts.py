"""Prompt template management and building."""

from __future__ import annotations

from typing import Any

import httpx

from ....logging_config import get_logger
from ....storage.events import get_events_by_trace
from ....storage.subtasks import get_handoff_context
from ....storage.task_spirit import get_task_spirit

logger = get_logger(__name__)

# Prompt cache for process lifetime
_prompt_cache: dict[str, str] = {}


def get_prompt_template(slug: str) -> str:
    """Fetch prompt content from Agent Hub API by slug.

    Results are cached for the process lifetime to avoid repeated HTTP calls.
    Raises RuntimeError if the prompt cannot be fetched — DB is the sole
    source of truth, there are no hardcoded fallbacks.
    """
    if slug in _prompt_cache:
        return _prompt_cache[slug]

    from ....services.agent_hub_client import (
        AGENT_HUB_URL,
        SUMMITFLOW_CLIENT_ID,
        SUMMITFLOW_CLIENT_SECRET,
        SUMMITFLOW_REQUEST_SOURCE,
    )

    url = f"{AGENT_HUB_URL}/api/prompts/{slug}"
    headers: dict[str, str] = {}
    if SUMMITFLOW_CLIENT_ID and SUMMITFLOW_CLIENT_SECRET:
        headers = {
            "X-Client-Id": SUMMITFLOW_CLIENT_ID,
            "X-Client-Secret": SUMMITFLOW_CLIENT_SECRET,
            "X-Request-Source": SUMMITFLOW_REQUEST_SOURCE or "summitflow",
        }
    try:
        response = httpx.get(url, headers=headers, timeout=5.0)
    except httpx.HTTPError as e:
        raise RuntimeError(f"Cannot fetch prompt '{slug}' from {url}: {e}") from e

    if not response.is_success:
        raise RuntimeError(
            f"Prompt '{slug}' not found (HTTP {response.status_code}). "
            f"Seed it with: st prompt create {slug} '<name>' -f <file>"
        )

    data = response.json()
    content: str = data.get("content", "")
    if not content:
        raise RuntimeError(f"Prompt '{slug}' exists but has empty content")

    _prompt_cache[slug] = content
    return content


def build_steps_block(steps: list[dict[str, Any]]) -> str:
    """Build formatted steps block from step dicts."""
    if not steps:
        return ""
    lines = ["Steps to complete:"]
    for step in steps:
        step_num = step.get("step_number", 0)
        desc = step.get("description", "")
        verify = step.get("verify_command", "")
        expect = step.get("expected_output", "")
        lines.append(f"{step_num}. {desc}")
        if verify:
            lines.append(f"   Verify: {verify}")
        if expect:
            lines.append(f"   Expected: {expect}")
    return "\n".join(lines)


def build_failures_block(failed_steps: list[dict[str, Any]]) -> str:
    """Build formatted failures block from failed step results."""
    parts = []
    for fail in failed_steps:
        step_num = fail.get("step_number", "?")
        reason = fail.get("reason", "unknown")
        output = fail.get("output", "")[:500]
        parts.append(f"### Step {step_num}: FAILED")
        parts.append(f"Reason: {reason}")
        if output:
            parts.append(f"Output:\n```\n{output}\n```")
    return "\n\n".join(parts)


def build_resume_context(task_id: str) -> str:
    """Build continuity context for a resumed task.

    Queries task events for wind_down logs and prior execution history
    to provide the agent with context about what was previously tried.

    Returns empty string if no prior execution history exists.
    """
    try:
        events = get_events_by_trace(task_id, limit=50)
        if not events:
            return ""

        # Look for wind_down events and failure summaries
        wind_down_msgs = []
        error_msgs = []
        for evt in events:
            msg = evt.get("message", "") or ""
            if "SESSION END" in msg:
                wind_down_msgs.append(msg[:500])
            elif evt.get("level") in ("error", "warn") and "FAILED" in msg.upper():
                error_msgs.append(msg[:200])

        if not wind_down_msgs and not error_msgs:
            return ""

        lines = ["\n# Resume Context (prior execution)"]
        if wind_down_msgs:
            lines.append("Last session state:")
            lines.append(wind_down_msgs[-1])
        if error_msgs:
            lines.append(f"\nPrior failures ({len(error_msgs)}):")
            for msg in error_msgs[-3:]:
                lines.append(f"- {msg}")
        lines.append("\nApproach this with a fresh perspective based on the above history.")

        return "\n".join(lines)
    except Exception as e:
        logger.debug("Failed to build resume context", error=str(e))
        return ""


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

    spirit_anti_block = ""
    if spirit_anti:
        spirit_anti_block = f"\n# Guiding Principles\n{spirit_anti}"

    handoff_block = ""
    if handoff.get("previous_summaries"):
        handoff_lines = ["\n# Previous Work Summary"]
        for summary in handoff["previous_summaries"]:
            handoff_lines.append(f"- Subtask {summary['short_id']}: {summary['summary']}")
        handoff_block = "\n".join(handoff_lines)

    # Inject resume context for previously-paused tasks
    resume_block = build_resume_context(task_id)

    steps = subtask.get("steps_from_table", [])
    steps_block = build_steps_block(steps)

    template = get_prompt_template("autocode-subtask")

    prompt = template.format_map({
        "objective": objective,
        "spirit_anti_block": spirit_anti_block,
        "handoff_block": handoff_block,
        "subtask_id": subtask_short_id,
        "description": subtask.get("description", ""),
        "steps_block": steps_block,
        "project_path": project_path,
    })

    # Append resume context for previously-paused tasks (outside template)
    if resume_block:
        prompt += resume_block

    return prompt


def build_fix_prompt(
    subtask: dict[str, Any],
    failed_steps: list[dict[str, Any]],
    previous_response: str,
    supervisor_guidance: str | None = None,
) -> str:
    """Build a fix prompt with error context for self-healing.

    Args:
        subtask: The subtask being executed
        failed_steps: List of failed step verification results
        previous_response: Agent's previous response (for context)
        supervisor_guidance: Optional supervisor guidance text

    Returns:
        Fix prompt to send to agent
    """
    subtask_short_id = subtask.get("subtask_id", "")
    subtask_desc = subtask.get("description", "")

    failures_block = build_failures_block(failed_steps)

    supervisor_block = ""
    if supervisor_guidance:
        supervisor_block = f"\n## Supervisor Guidance\n{supervisor_guidance}"

    steps = subtask.get("steps_from_table", [])
    steps_block = build_steps_block(steps)

    template = get_prompt_template("autocode-fix")

    return template.format_map({
        "subtask_id": subtask_short_id,
        "description": subtask_desc,
        "failures_block": failures_block,
        "supervisor_block": supervisor_block,
        "steps_block": steps_block,
    })
