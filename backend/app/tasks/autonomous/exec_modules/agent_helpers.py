"""Helper functions for agent execution."""

from __future__ import annotations

import uuid
from time import sleep
from typing import Any

import httpx
from agent_hub import CompletionResponse

from ....constants import CONTEXT_FRESHNESS_THRESHOLD
from ....storage.subtasks import acknowledge_no_citations, get_subtask, log_citations
from ....storage.tasks.core import add_agent_hub_session, get_task
from ._agent_kwargs import build_complete_kwargs  # re-exported for callers
from .events import emit_log, emit_progress_log
from .interruption import ExecutionInterrupted

_AGENT_FAILURE_FINISH_REASONS = {"error", "failed", "cancelled"}
_COMPLETE_RETRY_DELAYS_SECONDS = (2.0, 4.0, 8.0, 16.0)
_TRANSIENT_COMPLETE_ERROR_TEXT = (
    "connection refused",
    "server disconnected",
    "connection reset",
    "temporarily unavailable",
    "bad gateway",
    "service unavailable",
    "gateway timeout",
    "http 502",
    "http 503",
    "http 504",
)
_TRANSIENT_COMPLETION_FAILURE_TEXT = (
    "completion cancelled unexpectedly",
    "final assistant summary",
    "tool execution cancelled",
    "sdk cancelled",
    "provider request cancelled",
)
# "completed" omitted: agent-declared success via `st done` must not abort
# the retry checkpoint — see interruption._INTERRUPT_STATUSES.
_STOPPED_TASK_RETRY_STATUSES = {"paused", "cancelled", "failed", "abandoned", "closed"}


def agent_completion_failure(response: CompletionResponse) -> str | None:
    """Return a compact failure reason when Agent Hub did not produce a usable response."""
    finish_reason = str(getattr(response, "finish_reason", "") or "").strip().lower()
    content = str(getattr(response, "content", "") or "").strip()
    if finish_reason in _AGENT_FAILURE_FINISH_REASONS:
        return content[:500] or f"Agent Hub completion ended with finish_reason={finish_reason}"
    if content.startswith("Session interrupted"):
        return content[:500]
    if content.startswith("Tool activity recorded without a final assistant summary"):
        return content[:500]
    return None


def _rotate_session_after_interruption(
    task_id: str,
    kwargs: dict[str, Any],
    current_session_id: str,
) -> str:
    """Use a fresh Agent Hub session after runtime interruption retries."""
    new_session_id = str(uuid.uuid4())
    add_agent_hub_session(task_id, new_session_id)
    kwargs["session_id"] = new_session_id
    return new_session_id


def _abort_retry_if_task_stopped(task_id: str, project_id: str, checkpoint: str) -> None:
    task = get_task(task_id)
    status = str((task or {}).get("status") or "").strip().lower()
    if status not in _STOPPED_TASK_RETRY_STATUSES:
        return
    emit_log(
        task_id,
        "info",
        f"Agent retry checkpoint reached: {checkpoint}; task status is {status}",
        source="orchestrator",
        project_id=project_id,
    )
    raise ExecutionInterrupted(status, f"task_status={status}")


def _is_transient_agent_hub_complete_error(error: Exception) -> bool:
    if isinstance(error, httpx.TimeoutException | httpx.TransportError):
        return True
    if isinstance(error, httpx.HTTPStatusError):
        return error.response.status_code in {502, 503, 504}
    text = str(error).lower()
    return any(marker in text for marker in _TRANSIENT_COMPLETE_ERROR_TEXT)


def _is_transient_agent_hub_failure_response(response: CompletionResponse) -> bool:
    """Return True for Agent Hub responses that represent retryable runtime loss."""
    failure = agent_completion_failure(response)
    if not failure:
        return False
    text = failure.lower()
    return any(marker in text for marker in _TRANSIENT_COMPLETION_FAILURE_TEXT)


def _complete_retry_delay(attempt: int) -> float | None:
    if attempt >= len(_COMPLETE_RETRY_DELAYS_SECONDS):
        return None
    return _COMPLETE_RETRY_DELAYS_SECONDS[attempt]


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


def _emit_response_log(
    task_id: str,
    subtask_short_id: str,
    level: str,
    message: str,
    response_preview: str,
    project_id: str,
) -> None:
    """Emit agent response log pair (user + debug)."""
    emit_log(
        task_id, level, message,
        source="agent", project_id=project_id,
    )
    emit_log(
        task_id, "debug", f"Agent response: {response_preview}",
        source="agent", project_id=project_id, visibility="internal",
    )


def log_initial_completion_fallback(
    task_id: str, subtask_short_id: str, response: CompletionResponse, project_id: str
) -> None:
    """Log completion for agents without progress log support."""
    if response.progress_log:
        return
    response_preview = response.content[:300] if response.content else "(no response)"
    failure = agent_completion_failure(response)
    if failure:
        _emit_response_log(
            task_id, subtask_short_id, "warn",
            f"Agent interrupted subtask {subtask_short_id}: {failure[:180]}",
            response_preview, project_id,
        )
        return
    _emit_response_log(
        task_id, subtask_short_id, "info",
        f"Agent completed subtask {subtask_short_id}",
        response_preview, project_id,
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

    if get_subtask(task_id, subtask_short_id) is None:
        return
    if response.cited_uuids:
        client = get_sync_client()
        log_citations(task_id, subtask_short_id, response.cited_uuids, client=client)
    else:
        acknowledge_no_citations(task_id, subtask_short_id)


def _try_complete(client: Any, kwargs: dict[str, Any]) -> CompletionResponse:
    """Single attempt to call client.complete."""
    return client.complete(**kwargs)


def _retry_after_exception(
    task_id: str,
    project_id: str,
    attempt: int,
    exc: Exception,
) -> float:
    """Validate transient exception is retryable and return delay."""
    if not _is_transient_agent_hub_complete_error(exc):
        raise exc
    delay = _complete_retry_delay(attempt)
    _abort_retry_if_task_stopped(task_id, project_id, "agent_hub_complete_error_retry")
    if delay is None:
        emit_log(
            task_id,
            "error",
            "Agent Hub complete unavailable after "
            f"{attempt + 1} attempts: {str(exc)[:160]}",
            source="orchestrator",
            project_id=project_id,
        )
        raise exc
    emit_log(
        task_id,
        "warn",
        "Agent Hub complete unavailable; "
        f"retrying in {delay:g}s (attempt {attempt + 2}): "
        f"{str(exc)[:160]}",
        source="orchestrator",
        project_id=project_id,
    )
    return delay


def _retry_after_transient_response(
    task_id: str,
    project_id: str,
    attempt: int,
    response: CompletionResponse,
    kwargs: dict[str, Any],
    current_session_id: str,
) -> tuple[str, float]:
    """Rotate session, validate retryable, and return (new_session_id, delay)."""
    delay = _complete_retry_delay(attempt)
    failure = agent_completion_failure(response) or "transient interruption"
    _abort_retry_if_task_stopped(task_id, project_id, "agent_hub_interruption_retry")
    if delay is None:
        emit_log(
            task_id,
            "error",
            "Agent Hub complete returned transient interruption after "
            f"{attempt + 1} attempts: {failure[:160]}",
            source="orchestrator",
            project_id=project_id,
        )
        return current_session_id, 0.0
    new_session_id = _rotate_session_after_interruption(
        task_id, kwargs, current_session_id
    )
    emit_log(
        task_id,
        "warn",
        "Agent Hub complete returned transient interruption; "
        f"retrying in {delay:g}s (attempt {attempt + 2}): "
        f"{failure[:160]} Fresh session: {new_session_id}",
        source="orchestrator",
        project_id=project_id,
    )
    return new_session_id, delay


def call_complete(
    client: Any,
    prompt: str,
    agent_slug: str,
    project_path: str,
    project_id: str,
    task_id: str,
    session_id: str,
    max_turns: int | None = None,
    include_roles: list[str] | None = None,
) -> CompletionResponse:
    """Invoke client.complete with standard kwargs and transient service retry."""
    kwargs = build_complete_kwargs(
        prompt=prompt,
        agent_slug=agent_slug,
        project_path=project_path,
        project_id=project_id,
        task_id=task_id,
        session_id=session_id,
        max_turns=max_turns,
        include_roles=include_roles,
    )
    current_session_id = session_id
    attempt = 0
    while True:
        try:
            response = _try_complete(client, kwargs)
        except Exception as exc:
            delay = _retry_after_exception(task_id, project_id, attempt, exc)
            sleep(delay)
            attempt += 1
            continue
        if not _is_transient_agent_hub_failure_response(response):
            return response
        new_session_id, delay = _retry_after_transient_response(
            task_id, project_id, attempt, response, kwargs, current_session_id
        )
        if delay == 0.0:
            return response
        current_session_id = new_session_id
        sleep(delay)
        attempt += 1


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
