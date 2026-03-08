"""Cross-agent fallback execution logic."""

from __future__ import annotations

from typing import Any

from ....logging_config import get_logger
from .agent_execution import execute_agent_initial
from .agent_routing import get_fallback_agents
from .events import emit_log
from .retry_loop import run_self_healing_loop

logger = get_logger(__name__)


def try_fallback_agent(
    task_id: str,
    subtask_id: str,
    subtask_short_id: str,
    subtask: dict[str, Any],
    steps: list[dict[str, Any]],
    project_path: str,
    project_id: str,
    fallback_slug: str,
    original_agent: str,
    original_prompt: str,
    attempts_made: int,
) -> tuple[bool, list[dict[str, Any]], int, int, int]:
    """Try executing subtask with a fallback agent."""
    emit_log(
        task_id, "info",
        f"Cross-agent fallback: trying {fallback_slug} for subtask {subtask_short_id}",
        project_id=project_id,
    )
    fallback_prompt = (
        f"Previous agent ({original_agent}) failed this subtask after "
        f"{attempts_made} attempts.\n\n{original_prompt}\n\nTry a different approach."
    )
    response, session = execute_agent_initial(
        task_id, subtask_short_id, fallback_prompt,
        fallback_slug, project_path, project_id,
    )
    all_passed, step_results, fb_self, fb_super, fb_ext, _ = run_self_healing_loop(
        task_id, subtask_id, subtask_short_id, subtask,
        steps, project_path, project_id,
        fallback_slug, session, response.content,
    )
    if all_passed:
        emit_log(
            task_id, "info",
            f"Cross-agent fallback to {fallback_slug} succeeded",
            project_id=project_id,
        )
    return all_passed, step_results, fb_self, fb_super, fb_ext


def execute_with_fallbacks(
    task_id: str,
    subtask_id: str,
    subtask_short_id: str,
    subtask: dict[str, Any],
    subtask_type: str | None,
    steps: list[dict[str, Any]],
    project_path: str,
    project_id: str,
    agent_slug: str,
    prompt: str,
    all_passed: bool,
    step_results: list[dict[str, Any]],
    self_fix_attempts: int,
    supervisor_guided_attempts: int,
    extensions_granted: int,
    agent_override: str | None,
) -> tuple[bool, list[dict[str, Any]], str, int, int, int]:
    """Execute fallback agents if primary agent failed."""
    if all_passed or agent_override:
        return all_passed, step_results, agent_slug, self_fix_attempts, supervisor_guided_attempts, extensions_granted

    fallback_agents = get_fallback_agents(subtask_type, agent_slug)
    for fallback_slug in fallback_agents:
        try:
            fb_passed, fb_results, fb_self, fb_super, fb_ext = try_fallback_agent(
                task_id, subtask_id, subtask_short_id, subtask,
                steps, project_path, project_id, fallback_slug,
                agent_slug, prompt,
                self_fix_attempts + supervisor_guided_attempts,
            )
            if fb_passed:
                return (
                    fb_passed, fb_results, fallback_slug,
                    self_fix_attempts + fb_self,
                    supervisor_guided_attempts + fb_super,
                    extensions_granted + fb_ext,
                )
        except Exception as fb_err:
            logger.warning("Cross-agent fallback failed", fallback=fallback_slug, error=str(fb_err))

    return all_passed, step_results, agent_slug, self_fix_attempts, supervisor_guided_attempts, extensions_granted
