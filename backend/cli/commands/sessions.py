"""Agent session and ownership commands for the CLI."""

from __future__ import annotations

import json
from typing import Annotated, Any, cast

import typer

from .._observability import refresh_agent_observability
from ..client import APIError, STClient
from ..config import get_project_override
from ..details import current_root, display_path, write_details
from ..output import handle_api_error, is_compact, output_json
from .sessions_overlap import render_overlap_list
from .sessions_ownership import render_ownership_list

app = typer.Typer(
    help="Agent session management",
    invoke_without_command=True,
    no_args_is_help=False,
)


_ACTIVE_STATUS_ALIASES = {"running", "stale", "reapable"}
_LIVE_STATUS_ALIASES = {"stale", "reapable"}


def _normalize_status_filter(status_filter: str | None) -> str | None:
    """Normalize CLI-friendly session status aliases to Agent Hub values."""
    if not status_filter:
        return None
    normalized = status_filter.strip().lower()
    if normalized in _ACTIVE_STATUS_ALIASES:
        return "active"
    return normalized


def _session_matches_status_alias(session: dict[str, Any], status_filter: str | None) -> bool:
    if not status_filter:
        return True
    normalized = status_filter.strip().lower()
    if normalized not in _LIVE_STATUS_ALIASES:
        return True

    live = session.get("live_activity")
    if not isinstance(live, dict):
        return False

    state = _session_live_state(session).strip().lower()
    if normalized == "reapable":
        return bool(live.get("reapable")) or state == "reapable"
    return bool(live.get("is_stale")) or bool(live.get("reapable")) or state in {
        "reapable",
        "stale",
        "stalled",
    }


def _render_session_list(
    status_filter: str | None,
    limit: int,
    agent_slug: str | None,
    parent_session_id: str | None,
    project_id: str | None,
    include_unassigned: bool = True,
) -> None:
    refresh_agent_observability()
    client = STClient(require_project=False)
    normalized_status = _normalize_status_filter(status_filter)
    resolved_project_id = project_id or get_project_override()

    try:
        sessions = client.list_sessions(
            status=normalized_status,
            limit=limit,
            page=1,
            agent_slug=agent_slug,
            parent_session_id=parent_session_id,
            project_id=resolved_project_id,
        )
    except APIError as e:
        handle_api_error(e)
        return

    sessions = [
        session
        for session in sessions
        if _session_matches_status_alias(session, status_filter)
    ]

    if not include_unassigned:
        sessions = [session for session in sessions if session.get("agent_slug")]

    if is_compact():
        _output_session_list_compact(sessions)
        return
    output_json(sessions)


def _session_live_state(session: dict[str, Any]) -> str:
    live = session.get("live_activity")
    if isinstance(live, dict):
        raw = live.get("lifecycle_state") or live.get("status") or live.get("state")
        if raw:
            return str(raw)
    return str(session.get("status") or "-")


def _session_line(session: dict[str, Any]) -> str:
    session_id = str(session.get("id") or "-")
    short_id = session_id[:8]
    project_id = str(session.get("project_id") or "-")
    status = str(session.get("status") or "-")
    agent = str(session.get("agent_slug") or "-")
    task_id = str(session.get("task_id") or "-")
    live_state = _session_live_state(session)
    updated = str(session.get("updated_at") or "-")
    return (
        f"SES {project_id} | {status} | {agent} | {short_id} | "
        f"task={task_id} state={live_state} updated={updated}"
    )


def _output_session_list_compact(sessions: list[dict[str, Any]]) -> None:
    print(f"SESSIONS[{len(sessions)}]")
    for session in sessions:
        print(_session_line(session))


@app.callback()
def sessions_callback(
    ctx: typer.Context,
    status_filter: Annotated[str | None, typer.Option("-s", "--status")] = None,
    limit: Annotated[int, typer.Option("--limit")] = 20,
    agent_slug: Annotated[str | None, typer.Option("--agent")] = None,
    parent_session_id: Annotated[str | None, typer.Option("--parent-session")] = None,
    project_id: Annotated[str | None, typer.Option("--project", "-P")] = None,
) -> None:
    """List agent sessions when no subcommand is provided."""
    if ctx.invoked_subcommand is not None:
        return
    _render_session_list(
        status_filter,
        limit,
        agent_slug,
        parent_session_id,
        project_id,
        include_unassigned=True,
    )


@app.command("list")
def list_sessions(
    status_filter: Annotated[str | None, typer.Option("-s", "--status")] = None,
    include_unassigned: Annotated[
        bool,
        typer.Option(
            "--include-unassigned",
            help="Include imported/unassigned sessions without an agent slug",
        ),
    ] = True,
    limit: Annotated[int, typer.Option("--limit")] = 20,
    agent_slug: Annotated[str | None, typer.Option("--agent")] = None,
    parent_session_id: Annotated[str | None, typer.Option("--parent-session")] = None,
    project_id: Annotated[str | None, typer.Option("--project", "-P")] = None,
) -> None:
    """List agent sessions.

    Works from any directory; use --project to filter by project.

    Examples:
        st sessions
        st sessions list
        st sessions list --status active
        st sessions list -s active --include-unassigned
    """
    _render_session_list(
        status_filter,
        limit,
        agent_slug,
        parent_session_id,
        project_id,
        include_unassigned=include_unassigned,
    )


@app.command("show")
def show_session(
    session_id: str,
    raw: Annotated[bool, typer.Option("--raw", help="Print full raw session JSON.")] = False,
) -> None:
    """Show details of a specific session.

    Works from any directory — no project context required.

    Examples:
        st sessions show abc123
    """
    client = STClient(require_project=False)

    try:
        session = client.get_session(session_id)
    except APIError as e:
        handle_api_error(e)
        return

    if raw or not is_compact():
        output_json(session)
        return
    root = current_root()
    details = write_details(root, f"session-{session_id[:8]}", json.dumps(session, default=str, indent=2))
    print(f"SESSION:{session.get('id', session_id)}|project={session.get('project_id', '-')}|status={session.get('status', '-')}|details:{display_path(root, details)}")


@app.command("close")
def close_session(
    session_id: str,
) -> None:
    """Close an active session.

    Works from any directory — no project context required.
    """
    client = STClient(require_project=False)

    try:
        result = client.close_session(session_id)
    except APIError as e:
        handle_api_error(e)
        return

    output_json(result)


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
            "reapable_sessions": [
                {
                    "id": session.get("id"),
                    "project_id": session.get("project_id"),
                    "agent_slug": session.get("agent_slug"),
                    "session_type": session.get("session_type"),
                    "reapable_reason": (
                        cast(dict[str, Any], session.get("live_activity")).get("reapable_reason")
                        if isinstance(session.get("live_activity"), dict)
                        else None
                    ),
                }
                for session in candidates
            ],
        }
    )


@app.command("reap")
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

    closed: list[dict[str, object]] = []
    failed: list[dict[str, object]] = []
    for session in candidates:
        session_id = session.get("id")
        if not isinstance(session_id, str) or not session_id:
            continue
        try:
            closed.append(client.close_session(session_id))
        except APIError as e:
            failed.append({"id": session_id, "error": str(e.detail)})

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


@app.command("ownership")
def list_ownership(
    project_id: Annotated[str | None, typer.Option("--project", "-P")] = None,
) -> None:
    """List live active ownership lanes across projects or for one project."""
    render_ownership_list(STClient(require_project=False), project_id)


@app.command("overlap")
def list_overlaps(
    project_id: Annotated[str | None, typer.Option("--project", "-P")] = None,
) -> None:
    """List current scope overlaps across active ownership lanes."""
    render_overlap_list(STClient(require_project=False), project_id)
