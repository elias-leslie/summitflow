"""Session reap command implementation."""

from __future__ import annotations

from typing import Annotated, Any, cast

import typer

from .._observability import refresh_agent_observability
from ..client import APIError, STClient
from ..output import handle_api_error, output_json


def _list_all_active_sessions(
    client: STClient,
    *,
    project_id: str | None,
    page_size: int = 100,
) -> list[dict[str, object]]:
    refresh_agent_observability()
    sessions: list[dict[str, object]] = []
    page = 1
    while True:
        batch = client.list_sessions(
            status="active",
            limit=page_size,
            page=page,
            project_id=project_id,
        )
        if not batch:
            break
        sessions.extend(batch)
        if len(batch) < page_size:
            break
        page += 1
    return sessions


def _reapable_sessions(sessions: list[dict[str, object]]) -> list[dict[str, object]]:
    result: list[dict[str, object]] = []
    for session in sessions:
        live = session.get("live_activity")
        if not isinstance(live, dict):
            continue
        live_dict = cast(dict[str, Any], live)
        if bool(live_dict.get("reapable")) or live_dict.get("lifecycle_state") == "reapable":
            result.append(session)
    return result


def _reapable_session_payload(session: dict[str, object]) -> dict[str, object]:
    live = session.get("live_activity")
    return {
        "id": session.get("id"),
        "project_id": session.get("project_id"),
        "agent_slug": session.get("agent_slug"),
        "session_type": session.get("session_type"),
        "reapable_reason": (
            cast(dict[str, Any], live).get("reapable_reason") if isinstance(live, dict) else None
        ),
    }


def _output_dry_run(
    project_id: str | None,
    candidates: list[dict[str, object]],
) -> None:
    """Render the dry-run preview of reapable sessions as JSON."""
    output_json(
        {
            "project_id": project_id,
            "dry_run": True,
            "reapable_count": len(candidates),
            "reapable_sessions": [_reapable_session_payload(session) for session in candidates],
        }
    )


def reap_sessions(
    project_id: Annotated[str | None, typer.Option("--project", "-P")] = None,
    dry_run: Annotated[
        bool,
        typer.Option("--dry-run", help="Preview reapable sessions without closing them"),
    ] = False,
) -> None:
    """Close only sessions already marked reapable by Agent Hub lifecycle state."""
    client = STClient(require_project=False)
    target_project_id = project_id or getattr(client, "project_id", None)

    try:
        candidates = _reapable_sessions(
            _list_all_active_sessions(client, project_id=target_project_id)
        )
    except APIError as e:
        handle_api_error(e)
        return

    if dry_run:
        _output_dry_run(target_project_id, candidates)
        return

    closed, failed = _close_reapable_sessions(client, candidates)

    output_json(
        {
            "project_id": target_project_id,
            "dry_run": False,
            "reapable_count": len(candidates),
            "closed_count": len(closed),
            "closed_sessions": closed,
            "failed_count": len(failed),
            "failed_sessions": failed,
        }
    )


def _close_reapable_sessions(client: STClient, candidates: list[dict[str, object]]) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    closed: list[dict[str, object]] = []
    failed: list[dict[str, object]] = []
    for session in candidates:
        session_id = session.get("id")
        if not isinstance(session_id, str) or not session_id:
            continue
        try:
            closed.append(client.close_session(session_id))
        except APIError as e:
            failed.append(_reapable_session_failure(session_id, e))
    return closed, failed


def _reapable_session_failure(session_id: str, error: APIError) -> dict[str, object]:
    return {"id": session_id, "error": str(error.detail)}
