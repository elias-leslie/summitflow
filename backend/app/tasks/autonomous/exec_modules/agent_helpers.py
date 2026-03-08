"""Helper functions for agent execution."""

from __future__ import annotations

import uuid
from typing import Any

from agent_hub import CompletionResponse

from ....constants import CONTEXT_FRESHNESS_THRESHOLD
from ....storage.subtasks import acknowledge_no_citations, log_citations
from ....storage.tasks.core import add_agent_hub_session
from ._agent_kwargs import build_complete_kwargs  # re-exported for callers
from .events import emit_log, emit_progress_log


def create_session(task_id: str, session_id: str | None = None) -> str:
    """Create or ensure agent session ID is tracked."""
    if session_id is None:
        session_id = str(uuid.uuid4())
    add_agent_hub_session(task_id, session_id)
    return session_id


def update_session_if_changed(
    task_id: str, response_session_id: str | None, current_session_id: str
) -> str:
    """Update session ID if Agent Hub returned a different one."""
    if response_session_id and response_session_id != current_session_id:
        add_agent_hub_session(task_id, response_session_id)
        return response_session_id
    return current_session_id


def handle_progress_log(
    task_id: str,
    subtask_short_id: str,
    response: CompletionResponse,
    project_id: str,
) -> None:
    """Surface progress log to execution timeline."""
    if response.progress_log:
        emit_progress_log(
            task_id, subtask_short_id, response.progress_log, project_id=project_id
        )


def log_initial_completion_fallback(
    task_id: str, subtask_short_id: str, response: CompletionResponse, project_id: str
) -> None:
    """Log completion for agents without progress log support."""
    if response.progress_log:
        return
    response_preview = response.content[:300] if response.content else "(no response)"
    emit_log(
        task_id, "info", f"Agent completed subtask {subtask_short_id}",
        source="agent", project_id=project_id,
    )
    emit_log(
        task_id, "debug", f"Agent response: {response_preview}",
        source="agent", project_id=project_id, visibility="internal",
    )


def log_context_usage(
    task_id: str, response: CompletionResponse, project_id: str, phase: str = "check"
) -> None:
    """Log context window usage information."""
    ctx = response.context_usage
    if not ctx:
        return
    if phase == "initial":
        level = "warn" if ctx.percent_used >= CONTEXT_FRESHNESS_THRESHOLD else "info"
        emit_log(
            task_id, level,
            f"Context usage after initial execution: {ctx.percent_used:.0f}% "
            f"({ctx.used_tokens}/{ctx.limit_tokens} tokens)",
            source="orchestrator", project_id=project_id,
        )
    else:
        emit_log(
            task_id, "debug",
            f"Context usage: {ctx.percent_used:.0f}% "
            f"({ctx.used_tokens}/{ctx.limit_tokens} tokens)",
            source="orchestrator", project_id=project_id, visibility="internal",
        )


def check_context_reset_needed(
    task_id: str, response: CompletionResponse, project_id: str
) -> bool:
    """Check if context window needs reset; create new session if so."""
    ctx = response.context_usage
    if not ctx or ctx.percent_used < CONTEXT_FRESHNESS_THRESHOLD:
        return False
    emit_log(
        task_id, "warn",
        f"Context window at {ctx.percent_used:.0f}% "
        f"({ctx.used_tokens}/{ctx.limit_tokens} tokens). "
        "Starting fresh session for next attempt.",
        source="orchestrator", project_id=project_id,
    )
    new_session_id = str(uuid.uuid4())
    add_agent_hub_session(task_id, new_session_id)
    return True


def log_memory_citations(
    task_id: str, response: CompletionResponse, project_id: str
) -> None:
    """Log memory citations used during execution."""
    if not response.cited_uuids:
        return
    citations_str = ", ".join(response.cited_uuids[:5])
    if len(response.cited_uuids) > 5:
        citations_str += f" (+{len(response.cited_uuids) - 5} more)"
    emit_log(
        task_id, "info", f"Memory cited: {citations_str}",
        source="memory", project_id=project_id,
    )


def record_citations(
    task_id: str, subtask_short_id: str, response: CompletionResponse
) -> None:
    """Record citations from Agent Hub response for ACE-aligned feedback."""
    from ....services.agent_hub_client import get_sync_client

    if response.cited_uuids:
        client = get_sync_client()
        log_citations(task_id, subtask_short_id, response.cited_uuids, client=client)
    else:
        acknowledge_no_citations(task_id, subtask_short_id)


def call_complete(
    client: Any,
    prompt: str,
    agent_slug: str,
    project_path: str,
    project_id: str,
    task_id: str,
    session_id: str,
    max_turns: int,
    include_roles: list[str],
    model_override: str | None = None,
) -> CompletionResponse:
    """Invoke client.complete with standard kwargs."""
    return client.complete(
        **build_complete_kwargs(
            prompt=prompt,
            agent_slug=agent_slug,
            project_path=project_path,
            project_id=project_id,
            task_id=task_id,
            session_id=session_id,
            max_turns=max_turns,
            model_override=model_override,
            include_roles=include_roles,
        )
    )


def post_initial_response(
    task_id: str,
    subtask_short_id: str,
    response: CompletionResponse,
    project_id: str,
) -> None:
    """Handle post-response logging for initial execution."""
    handle_progress_log(task_id, subtask_short_id, response, project_id)
    log_initial_completion_fallback(task_id, subtask_short_id, response, project_id)
    log_context_usage(task_id, response, project_id, phase="initial")
    log_memory_citations(task_id, response, project_id)
    record_citations(task_id, subtask_short_id, response)


def post_fix_response(
    task_id: str,
    subtask_short_id: str,
    response: CompletionResponse,
    project_id: str,
    current_session_id: str,
) -> str:
    """Handle post-response logic for fix execution; returns (possibly reset) session ID."""
    handle_progress_log(task_id, subtask_short_id, response, project_id)
    emit_log(
        task_id, "info", "Agent fix attempt completed",
        source="agent", project_id=project_id,
    )
    if check_context_reset_needed(task_id, response, project_id):
        return create_session(task_id)
    log_context_usage(task_id, response, project_id, phase="check")
    return current_session_id
