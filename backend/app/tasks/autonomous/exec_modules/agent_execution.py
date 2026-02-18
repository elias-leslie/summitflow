"""Agent execution and session management."""

from __future__ import annotations

from typing import Any

from agent_hub import CompletionResponse

from ....logging_config import get_logger
from ....services.agent_hub_client import get_sync_client
from .agent_helpers import (
    build_complete_kwargs,
    check_context_reset_needed,
    create_session,
    handle_progress_log,
    log_context_usage,
    log_initial_completion_fallback,
    log_memory_citations,
    record_citations,
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
    agent_session_id = create_session(task_id)  # Queryable during execution
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
    response = client.complete(
        **build_complete_kwargs(
            prompt=prompt,
            agent_slug=agent_slug,
            project_path=project_path,
            project_id=project_id,
            task_id=task_id,
            session_id=agent_session_id,
            max_turns=50,
            tier_preference=tier_preference,
            include_roles=AUTOCODE_ROLES,
        )
    )
    agent_session_id = update_session_if_changed(
        task_id, response.session_id, agent_session_id
    )
    # Surface progress and logging
    handle_progress_log(task_id, subtask_short_id, response, project_id)
    log_initial_completion_fallback(task_id, subtask_short_id, response, project_id)
    log_context_usage(task_id, response, project_id, phase="initial")
    log_memory_citations(task_id, response, project_id)
    record_citations(task_id, subtask_short_id, response)
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
    response = client.complete(
        **build_complete_kwargs(
            prompt=fix_prompt,
            agent_slug=agent_slug,
            project_path=project_path,
            project_id=project_id,
            task_id=task_id,
            session_id=agent_session_id,
            max_turns=25,
            tier_preference=tier_preference,
            model_override=model_override,
            include_roles=AUTOCODE_ROLES,
        )
    )
    agent_session_id = update_session_if_changed(
        task_id, response.session_id, agent_session_id
    )
    handle_progress_log(task_id, subtask_short_id, response, project_id)
    emit_log(
        task_id, "info", "Agent fix attempt completed",
        source="agent", project_id=project_id,
    )
    # Check context window usage - start fresh session if approaching limit
    if check_context_reset_needed(task_id, response, project_id):
        agent_session_id = create_session(task_id)
    else:
        log_context_usage(task_id, response, project_id, phase="check")
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

    Args:
        task_id: Task identifier
        project_path: Working directory path
        project_id: Project identifier
        results: Subtask execution results (for context in prompt)
        agent_slug: Agent to ask for feedback
        tier_preference: Optional model tier preference
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

        client.complete(
            **build_complete_kwargs(
                prompt=prompt,
                agent_slug=agent_slug,
                project_path=project_path,
                project_id=project_id,
                task_id=task_id,
                session_id=feedback_session_id,
                max_turns=3,
                tier_preference=tier_preference,
                include_roles=AUTOCODE_ROLES,
            )
        )

        emit_log(
            task_id, "info", "Agent feedback collection completed",
            source="orchestrator", project_id=project_id,
        )
    except Exception as e:
        # Never block on feedback failures
        logger.warning("Agent feedback collection failed", task_id=task_id, error=str(e))
