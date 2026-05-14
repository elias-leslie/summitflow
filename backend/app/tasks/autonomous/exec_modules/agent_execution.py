"""Agent execution and session management."""

from __future__ import annotations

from agent_hub import CompletionResponse

from ....logging_config import get_logger
from ....services.agent_hub_client import get_sync_client
from .agent_helpers import (
    call_complete,
    create_session,
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
        agent_slug=agent_slug, session_id=agent_session_id,
    )
    emit_log(
        task_id, "info", f"Agent session started: {agent_session_id}",
        source="orchestrator", project_id=project_id,
    )
    response = call_complete(
        client, prompt, agent_slug, project_path, project_id,
        task_id, agent_session_id,
        include_roles=AUTOCODE_ROLES,
    )
    agent_session_id = update_session_if_changed(
        task_id, response.session_id, agent_session_id
    )
    post_initial_response(task_id, subtask_short_id, response, project_id)
    return response, agent_session_id
