"""Agent session and ownership commands for the CLI."""

from __future__ import annotations

import json
from typing import Annotated, Any

import typer

from .._observability import refresh_agent_observability
from ..client import APIError, STClient
from ..config import get_project_override
from ..details import current_root, display_path, write_details
from ..lib.usage import usage
from ..output import handle_api_error, is_compact, output_json
from . import sessions_monitor as _sessions_monitor
from . import sessions_reap as _sessions_reap
from ._session_resolver import resolve_session_id as _resolve_session_id
from .session_events_client import get_session_events
from .sessions_monitor import monitor_sessions as _monitor_sessions
from .sessions_overlap import render_overlap_list
from .sessions_ownership import render_ownership_list
from .sessions_reap import _list_all_active_sessions as _reap_list_all_active_sessions
from .sessions_reap import reap_sessions as _reap_sessions
from .sessions_shared import live_state as _live_state
from .sessions_shared import normalize_status_filter as _normalize_status_filter
from .sessions_shared import session_matches_status_alias as _session_matches_status_alias

_list_all_active_sessions = _reap_list_all_active_sessions

app = typer.Typer(
    help=(
        "Agent session management. Use `st sessions monitor` for agentic "
        "monitoring: active overview, task current attempt, or session detail."
    ),
    invoke_without_command=True,
    no_args_is_help=False,
)



def _compact_session_line(session: dict[str, Any]) -> str:
    session_id = str(session.get("id") or "-")
    project_id = str(session.get("project_id") or "-")
    status = str(session.get("status") or "-")
    agent = str(session.get("agent_slug") or "-")
    task_id = str(session.get("task_id") or "-")
    live_state = _live_state(session)
    updated = str(session.get("updated_at") or "-")
    return (
        f"SES {project_id} | {status} | {agent} | {session_id[:8]} | "
        f"task={task_id} state={live_state} updated={updated}"
    )


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

    sessions = [s for s in sessions if _session_matches_status_alias(s, status_filter)]
    if not include_unassigned:
        sessions = [s for s in sessions if s.get("agent_slug")]

    if is_compact():
        print(f"SESSIONS[{len(sessions)}]")
        for session in sessions:
            print(_compact_session_line(session))
        return
    output_json(sessions)


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
    project_id: Annotated[str | None, typer.Option("--project", "-P", help="Project scope for short session ID lookup.")] = None,
    raw: Annotated[bool, typer.Option("--raw", help="Print full raw session JSON.")] = False,
) -> None:
    """Show details of a specific session.

    Works from any directory — no project context required.

    Examples:
        st sessions show abc123
    """
    client = STClient(require_project=False)
    resolved_id = _resolve_session_id(session_id, client, project_id=project_id)

    try:
        session = client.get_session(resolved_id)
    except APIError as e:
        handle_api_error(e)
        return

    if raw or not is_compact():
        output_json(session)
        return
    root = current_root()
    details = write_details(root, f"session-{resolved_id[:8]}", json.dumps(session, default=str, indent=2))
    print(f"SESSION:{session.get('id', resolved_id)}|project={session.get('project_id', '-')}|status={session.get('status', '-')}|details:{display_path(root, details)}")


@app.command("close")
def close_session(
    session_id: str,
    project_id: Annotated[str | None, typer.Option("--project", "-P", help="Project scope for short session ID lookup.")] = None,
) -> None:
    """Close an active session.

    Works from any directory — no project context required.
    """
    client = STClient(require_project=False)
    resolved_id = _resolve_session_id(session_id, client, project_id=project_id)

    try:
        result = client.close_session(resolved_id)
    except APIError as e:
        handle_api_error(e)
        return

    output_json(result)



@app.command("monitor")
def monitor_sessions(
    ctx: typer.Context,
    target: Annotated[str | None, typer.Argument(help="Task ID, session ID/prefix, or empty for active sessions")] = None,
    project_id: Annotated[str | None, typer.Option("--project", "-P", help="Project scope")] = None,
    status_filter: Annotated[str, typer.Option("--status", "-s", help="Session status for overview")] = "active",
    agent_slug: Annotated[str | None, typer.Option("--agent", help="Agent slug filter for overview")] = None,
    follow: Annotated[bool, typer.Option("-f", "--follow", help="Follow events in real time")] = False,
    limit: Annotated[int, typer.Option("-n", "--limit", help="Maximum events to show")] = 20,
    debug: Annotated[bool, typer.Option("--debug", help="Include debug-level events")] = False,
    errors: Annotated[bool, typer.Option("--errors", help="Show only error events for a session target")] = False,
    history: Annotated[bool, typer.Option("--history", help="Include older linked Agent Hub sessions")] = False,
    json_output: Annotated[bool, typer.Option("--json", help="Output as JSON")] = False,
) -> None:
    """Monitor agentic work: active sessions, one session, or one task."""
    _sync_monitor_test_patches()
    _monitor_sessions(ctx, target=target, project_id=project_id, status_filter=status_filter, agent_slug=agent_slug, follow=follow, limit=limit, debug=debug, errors=errors, history=history, json_output=json_output)


def _sync_monitor_test_patches() -> None:
    _sessions_monitor.STClient = STClient
    _sessions_monitor.get_session_events = get_session_events


@app.command("reap")
def reap_sessions(
    project_id: Annotated[str | None, typer.Option("--project", "-P")] = None,
    dry_run: Annotated[bool, typer.Option("--dry-run", help="Preview reapable sessions without closing them")] = False,
) -> None:
    """Close only sessions already marked reapable by Agent Hub lifecycle state."""
    _sync_reap_test_patches()
    _reap_sessions(project_id=project_id, dry_run=dry_run)


def _sync_reap_test_patches() -> None:
    _sessions_reap.STClient = STClient
    _sessions_reap.output_json = output_json


@app.command("ownership")
@usage(
    surface="st.sessions.ownership",
    cmd="st sessions ownership -P <project>",
    when="check lane truth when st pulse --gate reports blocked",
    precautions=("don't inspect routinely; only when pulse names ownership as the blocker",),
    task_types=("devops",),
    tier="reference",
)
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
