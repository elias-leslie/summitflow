"""Emit task lifecycle events to Agent Hub session_events.

Surfaces review verdicts, quality gate results, and task state transitions
in the Agent Hub timeline alongside regular execution events.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

import httpx

from ....logging_config import get_logger
from ....services._agent_hub_config import (
    AGENT_HUB_URL,
    build_agent_hub_headers,
)

logger = get_logger(__name__)

_TIMEOUT = 5  # seconds — don't block pipeline on slow Agent Hub


def _jsonable(value: Any) -> Any:
    """Return a JSON-serializable representation for session event payloads."""
    if hasattr(value, "model_dump"):
        return _jsonable(value.model_dump())
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, list | tuple | set):
        return [_jsonable(item) for item in value]
    if isinstance(value, datetime | date):
        return value.isoformat()
    if isinstance(value, str | int | float | bool) or value is None:
        return value
    return str(value)


def _get_headers() -> dict[str, str]:
    """Headers for Agent Hub API calls."""
    return build_agent_hub_headers(
        request_source="sf-pipeline",
        extra_headers={"Content-Type": "application/json"},
    )


def _get_session_ids(task_id: str) -> list[str]:
    """Get Agent Hub session IDs linked to a task."""
    try:
        from ....storage.tasks.sessions import get_agent_hub_sessions

        return get_agent_hub_sessions(task_id)
    except Exception:
        logger.debug("Failed to get session IDs for task %s", task_id, exc_info=True)
        return []


def emit_lifecycle_event(
    task_id: str,
    event_type: str,
    content: str,
    *,
    tool_name: str | None = None,
    tool_output: dict[str, Any] | None = None,
    agent_id: str | None = None,
) -> None:
    """Post a lifecycle event to all Agent Hub sessions linked to this task.

    Fire-and-forget — never blocks or fails the pipeline.
    """
    session_ids = _get_session_ids(task_id)
    if not session_ids:
        return

    url_base = AGENT_HUB_URL
    headers = _get_headers()
    payload: dict[str, Any] = {
        "event_type": event_type,
        "content": content,
    }
    if tool_name:
        payload["tool_name"] = tool_name
    if tool_output:
        payload["tool_output"] = _jsonable(tool_output)
    if agent_id:
        payload["agent_id"] = agent_id
    payload = _jsonable(payload)

    for session_id in session_ids:
        try:
            httpx.post(
                f"{url_base}/api/sessions/{session_id}/events",
                json=payload,
                headers=headers,
                timeout=_TIMEOUT,
            )
        except Exception:
            logger.debug(
                "Failed to emit lifecycle event to AH session %s",
                session_id,
                exc_info=True,
            )


def emit_review_verdict(
    task_id: str,
    verdict: str,
    concerns: list[str] | None = None,
) -> None:
    """Emit a review verdict event to Agent Hub timeline."""
    summary = f"Review verdict: {verdict}"
    if concerns:
        summary += f" — {'; '.join(concerns[:3])}"
    emit_lifecycle_event(
        task_id,
        event_type="tool_result",
        content=summary,
        tool_name="review_verdict",
        tool_output={"verdict": verdict, "concerns": concerns or []},
        agent_id="reviewer",
    )


def emit_quality_gate_result(
    task_id: str,
    passed: bool,
    detail: str = "",
) -> None:
    """Emit a quality gate pass/fail event to Agent Hub timeline."""
    status = "PASSED" if passed else "FAILED"
    content = f"Quality gate: {status}"
    if detail:
        content += f" — {detail}"
    emit_lifecycle_event(
        task_id,
        event_type="tool_result",
        content=content,
        tool_name="quality_gate",
        tool_output={"passed": passed, "detail": detail},
        agent_id="orchestrator",
    )


def emit_prompt_harness_snapshot(
    task_id: str,
    snapshot: dict[str, Any],
) -> None:
    """Emit prompt-composition snapshot metadata for session observability."""
    emit_lifecycle_event(
        task_id,
        event_type="tool_result",
        content=f"Prompt harness snapshot: {snapshot.get('mode', 'code_only')}",
        tool_name="prompt_harness",
        tool_output=snapshot,
        agent_id="orchestrator",
    )


def emit_runtime_evaluator_result(
    task_id: str,
    result: dict[str, Any],
) -> None:
    """Emit compact runtime-evaluator output for session observability."""
    emit_lifecycle_event(
        task_id,
        event_type="tool_result",
        content=f"Runtime evaluator: {result.get('summary', result.get('mode', 'runtime_eval'))}",
        tool_name="runtime_evaluator",
        tool_output=result,
        agent_id="orchestrator",
    )


def emit_task_transition(
    task_id: str,
    new_status: str,
    reason: str = "",
) -> None:
    """Emit a task state transition event to Agent Hub timeline."""
    content = f"Task → {new_status}"
    if reason:
        content += f": {reason}"
    emit_lifecycle_event(
        task_id,
        event_type="tool_result",
        content=content,
        tool_name="task_transition",
        tool_output={"status": new_status, "reason": reason},
        agent_id="orchestrator",
    )
