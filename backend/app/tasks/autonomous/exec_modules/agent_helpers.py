"""Helper functions for agent execution."""

from __future__ import annotations

import subprocess
import uuid
from typing import Any

from agent_hub import CompletionResponse

from ....constants import CONTEXT_FRESHNESS_THRESHOLD
from ....storage.subtasks import acknowledge_no_citations, log_citations
from ....storage.tasks.core import add_agent_hub_session
from .events import emit_log, emit_progress_log


def create_session(task_id: str, session_id: str | None = None) -> str:
    """Create or ensure agent session ID is tracked.

    Args:
        task_id: Task identifier
        session_id: Optional existing session ID

    Returns:
        Session ID (existing or newly created)
    """
    if session_id is None:
        session_id = str(uuid.uuid4())
    add_agent_hub_session(task_id, session_id)
    return session_id


def update_session_if_changed(
    task_id: str, response_session_id: str | None, current_session_id: str
) -> str:
    """Update session ID if Agent Hub returned a different one.

    Args:
        task_id: Task identifier
        response_session_id: Session ID from response
        current_session_id: Current session ID

    Returns:
        Updated session ID
    """
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
    """Surface progress log to execution timeline.

    Args:
        task_id: Task identifier
        subtask_short_id: Subtask short identifier
        response: Agent Hub response
        project_id: Project identifier
    """
    if response.progress_log:
        emit_progress_log(
            task_id, subtask_short_id, response.progress_log, project_id=project_id
        )


def log_initial_completion_fallback(
    task_id: str, subtask_short_id: str, response: CompletionResponse, project_id: str
) -> None:
    """Log completion for agents without progress log support.

    Args:
        task_id: Task identifier
        subtask_short_id: Subtask short identifier
        response: Agent Hub response
        project_id: Project identifier
    """
    if response.progress_log:
        return

    response_preview = response.content[:300] if response.content else "(no response)"
    emit_log(
        task_id,
        "info",
        f"Agent completed subtask {subtask_short_id}",
        source="agent",
        project_id=project_id,
    )
    emit_log(
        task_id,
        "debug",
        f"Agent response: {response_preview}",
        source="agent",
        project_id=project_id,
        visibility="internal",
    )


def log_context_usage(
    task_id: str, response: CompletionResponse, project_id: str, phase: str = "check"
) -> None:
    """Log context window usage information.

    Args:
        task_id: Task identifier
        response: Agent Hub response
        project_id: Project identifier
        phase: "initial" for detailed logging, "check" for threshold-based logging
    """
    ctx = response.context_usage
    if not ctx:
        return

    if phase == "initial":
        level = "warn" if ctx.percent_used >= CONTEXT_FRESHNESS_THRESHOLD else "info"
        emit_log(
            task_id,
            level,
            f"Context usage after initial execution: {ctx.percent_used:.0f}% "
            f"({ctx.used_tokens}/{ctx.limit_tokens} tokens)",
            source="orchestrator",
            project_id=project_id,
        )
    else:  # phase == "check"
        emit_log(
            task_id,
            "debug",
            f"Context usage: {ctx.percent_used:.0f}% "
            f"({ctx.used_tokens}/{ctx.limit_tokens} tokens)",
            source="orchestrator",
            project_id=project_id,
            visibility="internal",
        )


def check_context_reset_needed(
    task_id: str, response: CompletionResponse, project_id: str
) -> bool:
    """Check if context window needs reset and create new session if needed.

    Args:
        task_id: Task identifier
        response: Agent Hub response
        project_id: Project identifier

    Returns:
        True if new session was created, False otherwise
    """
    ctx = response.context_usage
    if not ctx or ctx.percent_used < CONTEXT_FRESHNESS_THRESHOLD:
        return False

    emit_log(
        task_id,
        "warn",
        f"Context window at {ctx.percent_used:.0f}% "
        f"({ctx.used_tokens}/{ctx.limit_tokens} tokens). "
        "Starting fresh session for next attempt.",
        source="orchestrator",
        project_id=project_id,
    )
    new_session_id = str(uuid.uuid4())
    add_agent_hub_session(task_id, new_session_id)
    return True


def log_memory_citations(
    task_id: str, response: CompletionResponse, project_id: str
) -> None:
    """Log memory citations used during execution.

    Args:
        task_id: Task identifier
        response: Agent Hub response
        project_id: Project identifier
    """
    if not response.cited_uuids:
        return

    citations_str = ", ".join(response.cited_uuids[:5])
    if len(response.cited_uuids) > 5:
        citations_str += f" (+{len(response.cited_uuids) - 5} more)"
    emit_log(
        task_id,
        "info",
        f"Memory cited: {citations_str}",
        source="memory",
        project_id=project_id,
    )


def record_citations(
    task_id: str, subtask_short_id: str, response: CompletionResponse
) -> None:
    """Record citations from Agent Hub response for ACE-aligned feedback.

    Args:
        task_id: Task identifier
        subtask_short_id: Subtask short identifier
        response: Agent Hub response
    """
    from ....services.agent_hub_client import get_sync_client

    if response.cited_uuids:
        client = get_sync_client()
        log_citations(task_id, subtask_short_id, response.cited_uuids, client=client)
    else:
        acknowledge_no_citations(task_id, subtask_short_id)


def _detect_git_branch(project_path: str) -> str | None:
    """Detect current git branch from project path."""
    try:
        result = subprocess.run(
            ["git", "-C", project_path, "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            return result.stdout.strip() or None
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass
    return None


def build_complete_kwargs(
    prompt: str,
    agent_slug: str,
    project_path: str,
    project_id: str,
    task_id: str,
    session_id: str,
    max_turns: int,
    tier_preference: str | None = None,
    model_override: str | None = None,
    include_roles: list[str] | None = None,
) -> dict[str, Any]:
    """Build kwargs dict for Agent Hub complete call.

    Args:
        prompt: User message content
        agent_slug: Agent identifier
        project_path: Working directory path
        project_id: Project identifier
        task_id: Task identifier for tracing
        session_id: Agent session ID
        max_turns: Maximum conversation turns
        tier_preference: Optional tier preference
        model_override: Optional model ID override
        include_roles: Roles to include in conversation

    Returns:
        Dictionary of kwargs for client.complete()
    """
    # Detect git branch for continuity scoping
    current_branch = _detect_git_branch(project_path)

    kwargs: dict[str, Any] = {
        "messages": [{"role": "user", "content": prompt}],
        "agent_slug": agent_slug,
        "working_dir": project_path,
        "max_turns": max_turns,
        "execute_tools": True,
        "project_id": project_id,
        "use_memory": True,
        "memory_group_id": f"project:{project_id}",
        "trace_id": task_id,
        "include_roles": include_roles or [],
        "session_id": session_id,
    }
    if current_branch:
        kwargs["current_branch"] = current_branch
    if model_override:
        kwargs["model"] = model_override
    if tier_preference:
        kwargs["tier_preference"] = tier_preference
    return kwargs
