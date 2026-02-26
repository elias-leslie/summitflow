"""Agent execution and session management."""

from __future__ import annotations

from typing import Any

from agent_hub import CompletionResponse

from ....logging_config import get_logger
from ....services.agent_hub_client import get_sync_client
from .agent_helpers import (
    call_complete,
    create_session,
    post_fix_response,
    post_initial_response,
    update_session_if_changed,
)
from .events import emit_log

logger = get_logger(__name__)

AUTOCODE_ROLES = ["system", "autocode"]


def execute_agent_initial(
    task_id: str,
    subtask_short_id: str,
    prompt: str,
    agent_slug: str,
    project_path: str,
    project_id: str,
    tier_preference: str | None = None,
) -> tuple[CompletionResponse, str | None]:
    """Execute initial agent call for subtask.

    Returns:
        Tuple of (response, agent_session_id)
    """
    client = get_sync_client()
    agent_session_id = create_session(task_id)
    emit_log(
        task_id, "info",
        f"Calling agent ({agent_slug}) for subtask {subtask_short_id}...",
        source="orchestrator", project_id=project_id,
    )
    logger.info(
        "Calling Agent Hub complete (agentic mode)",
        agent_slug=agent_slug, max_turns=50, session_id=agent_session_id,
    )
    emit_log(
        task_id, "info", f"Agent session started: {agent_session_id}",
        source="orchestrator", project_id=project_id,
    )
    response = call_complete(
        client, prompt, agent_slug, project_path, project_id,
        task_id, agent_session_id, max_turns=50,
        include_roles=AUTOCODE_ROLES, tier_preference=tier_preference,
    )
    agent_session_id = update_session_if_changed(
        task_id, response.session_id, agent_session_id
    )
    post_initial_response(task_id, subtask_short_id, response, project_id)
    return response, agent_session_id


def execute_agent_fix(
    task_id: str,
    subtask_short_id: str,
    fix_prompt: str,
    agent_slug: str,
    project_path: str,
    project_id: str,
    agent_session_id: str | None,
    model_override: str | None = None,
    tier_preference: str | None = None,
) -> tuple[CompletionResponse, str | None]:
    """Execute agent fix attempt.

    Args:
        model_override: Optional model ID to use instead of agent's primary model.
            Used for model escalation during supervisor-guided attempts.

    Returns:
        Tuple of (response, agent_session_id)
    """
    client = get_sync_client()
    if agent_session_id is None:
        agent_session_id = create_session(task_id)
        session_type = "new session"
    else:
        session_type = "continuing session"
    emit_log(
        task_id, "info",
        f"Calling agent for fix attempt ({session_type} {agent_session_id})...",
        source="orchestrator", project_id=project_id,
    )
    response = call_complete(
        client, fix_prompt, agent_slug, project_path, project_id,
        task_id, agent_session_id, max_turns=25, include_roles=AUTOCODE_ROLES,
        tier_preference=tier_preference, model_override=model_override,
    )
    agent_session_id = update_session_if_changed(
        task_id, response.session_id, agent_session_id
    )
    agent_session_id = post_fix_response(
        task_id, subtask_short_id, response, project_id, agent_session_id
    )
    return response, agent_session_id


def execute_agent_feedback(
    task_id: str,
    project_path: str,
    project_id: str,
    results: list[dict[str, Any]],
    agent_slug: str = "coder",
    tier_preference: str | None = None,
) -> None:
    """Collect feedback from agent after task execution.

    Creates a short session and asks the agent for friction/idea/praise feedback.
    Fire-and-forget — failures are logged but never block task completion.
    """
    from .prompts import build_feedback_prompt

    try:
        client = get_sync_client()
        feedback_session_id = create_session(task_id)
        prompt = build_feedback_prompt(results)
        emit_log(
            task_id, "info",
            f"Requesting agent feedback (session {feedback_session_id})",
            source="orchestrator", project_id=project_id,
        )
        call_complete(
            client, prompt, agent_slug, project_path, project_id,
            task_id, feedback_session_id, max_turns=3,
            include_roles=AUTOCODE_ROLES, tier_preference=tier_preference,
        )
        emit_log(
            task_id, "info", "Agent feedback collection completed",
            source="orchestrator", project_id=project_id,
        )
    except Exception as e:
        logger.warning("Agent feedback collection failed", task_id=task_id, error=str(e))
