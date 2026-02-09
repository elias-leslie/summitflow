"""Agent execution and session management."""

from __future__ import annotations

import uuid
from typing import Any

from ....constants import CONTEXT_FRESHNESS_THRESHOLD
from ....logging_config import get_logger
from ....services.agent_hub_client import get_sync_client
from ....storage.subtasks import acknowledge_no_citations, log_citations
from .events import emit_log, emit_progress_log

logger = get_logger(__name__)

AUTOCODE_ROLES = ["system", "autocode"]


def execute_agent_initial(
    task_id: str,
    subtask_short_id: str,
    prompt: str,
    agent_slug: str,
    project_path: str,
    project_id: str,
) -> tuple[Any, str | None]:
    """Execute initial agent call for subtask.

    Returns:
        Tuple of (response, agent_session_id)
    """
    from ....storage.tasks.core import add_agent_hub_session

    client = get_sync_client()
    emit_log(
        task_id,
        "info",
        f"Calling agent ({agent_slug}) for subtask {subtask_short_id}...",
        source="orchestrator",
        project_id=project_id,
    )

    # Pre-create session ID so events are queryable during execution
    agent_session_id = str(uuid.uuid4())
    add_agent_hub_session(task_id, agent_session_id)

    logger.info(
        "Calling Agent Hub complete (agentic mode)",
        agent_slug=agent_slug,
        max_turns=50,
        session_id=agent_session_id,
    )
    emit_log(
        task_id,
        "info",
        f"Agent session started: {agent_session_id}",
        source="orchestrator",
        project_id=project_id,
    )

    response = client.complete(
        messages=[{"role": "user", "content": prompt}],
        agent_slug=agent_slug,
        working_dir=project_path,
        max_turns=50,
        execute_tools=True,
        project_id=project_id,
        use_memory=True,
        trace_id=task_id,
        include_roles=AUTOCODE_ROLES,
        session_id=agent_session_id,
    )

    # Update session ID if Agent Hub returned a different one
    if response.session_id and response.session_id != agent_session_id:
        add_agent_hub_session(task_id, response.session_id)
        agent_session_id = response.session_id

    # Surface progress_log to execution timeline
    if response.progress_log:
        emit_progress_log(
            task_id, subtask_short_id, response.progress_log, project_id=project_id
        )
    else:
        # Fallback for agents that don't support incremental progress
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

    # Log context window usage after initial execution
    ctx = response.context_usage
    if ctx:
        level = "warn" if ctx.percent_used >= CONTEXT_FRESHNESS_THRESHOLD else "info"
        emit_log(
            task_id,
            level,
            f"Context usage after initial execution: {ctx.percent_used:.0f}% "
            f"({ctx.used_tokens}/{ctx.limit_tokens} tokens)",
            source="orchestrator",
            project_id=project_id,
        )

    # Log memory citations used
    if response.cited_uuids:
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

    # Log citations from Agent Hub response for ACE-aligned feedback
    # Must acknowledge citations (or lack thereof) before subtask can pass
    if response.cited_uuids:
        log_citations(task_id, subtask_short_id, response.cited_uuids, client=client)
    else:
        # No citations used - acknowledge this for the citation gate
        acknowledge_no_citations(task_id, subtask_short_id)

    return response, agent_session_id


def execute_agent_fix(
    task_id: str,
    subtask_short_id: str,
    fix_prompt: str,
    agent_slug: str,
    project_path: str,
    project_id: str,
    agent_session_id: str | None,
) -> tuple[Any, str | None]:
    """Execute agent fix attempt.

    Returns:
        Tuple of (response, agent_session_id)
    """
    from ....storage.tasks.core import add_agent_hub_session

    client = get_sync_client()
    continuation = agent_session_id is not None

    if not continuation:
        agent_session_id = str(uuid.uuid4())
        add_agent_hub_session(task_id, agent_session_id)

    emit_log(
        task_id,
        "info",
        f"Calling agent for fix attempt ({'continuing session' if continuation else 'new session'} {agent_session_id})...",
        source="orchestrator",
        project_id=project_id,
    )

    fix_kwargs: dict[str, Any] = {
        "messages": [{"role": "user", "content": fix_prompt}],
        "agent_slug": agent_slug,
        "working_dir": project_path,
        "max_turns": 25,
        "execute_tools": True,
        "project_id": project_id,
        "use_memory": True,
        "trace_id": task_id,
        "include_roles": AUTOCODE_ROLES,
        "session_id": agent_session_id,
    }

    response = client.complete(**fix_kwargs)

    # Update session ID if Agent Hub returned a different one
    if response.session_id and response.session_id != agent_session_id:
        add_agent_hub_session(task_id, response.session_id)
        agent_session_id = response.session_id

    # Surface progress_log to execution timeline
    if response.progress_log:
        emit_progress_log(
            task_id, subtask_short_id, response.progress_log, project_id=project_id
        )

    emit_log(
        task_id,
        "info",
        "Agent fix attempt completed",
        source="agent",
        project_id=project_id,
    )

    # Check context window usage - start fresh session if approaching limit
    ctx = response.context_usage
    if ctx and ctx.percent_used >= CONTEXT_FRESHNESS_THRESHOLD:
        emit_log(
            task_id,
            "warn",
            f"Context window at {ctx.percent_used:.0f}% "
            f"({ctx.used_tokens}/{ctx.limit_tokens} tokens). "
            "Starting fresh session for next attempt.",
            source="orchestrator",
            project_id=project_id,
        )
        agent_session_id = str(uuid.uuid4())
        add_agent_hub_session(task_id, agent_session_id)
    elif ctx:
        emit_log(
            task_id,
            "debug",
            f"Context usage: {ctx.percent_used:.0f}% "
            f"({ctx.used_tokens}/{ctx.limit_tokens} tokens)",
            source="orchestrator",
            project_id=project_id,
            visibility="internal",
        )

    return response, agent_session_id
