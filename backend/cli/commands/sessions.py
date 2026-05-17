"""Agent session and ownership commands for the CLI."""

from __future__ import annotations

from typing import Annotated

import typer

from .._observability import refresh_agent_observability
from ..client import APIError, STClient
from ..config import get_project_override
from ..details import current_root, display_path, write_details
from ..lib.usage import usage
from ..output import handle_api_error, is_compact, output_json
from ._session_resolver import resolve_session_id as _resolve_session_id
from .session_events_client import get_session_events
from .session_events_follow import follow_session_events
from .session_events_formatter import format_event
from .sessions_list import render_session_list
from .sessions_monitor import (
    monitor_overview,
    monitor_single_session,
)
from .sessions_overlap import render_overlap_list
from .sessions_ownership import render_ownership_list
from .sessions_reap import _list_all_active_sessions, reap_sessions

app = typer.Typer(
    help=(
        "Agent session management. Use `st sessions monitor` for agentic "
        "monitoring: active overview, task current attempt, or session detail."
    ),
    invoke_without_command=True,
    no_args_is_help=False,
)


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
    refresh_agent_observability()
    client = STClient(require_project=False)
    render_session_list(
        status_filter,
        limit,
        agent_slug,
        parent_session_id,
        project_id,
        include_unassigned=True,
        client=client,
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
    refresh_agent_observability()
    client = STClient(require_project=False)
    render_session_list(
        status_filter,
        limit,
        agent_slug,
        parent_session_id,
        project_id,
        include_unassigned=include_unassigned,
        client=client,
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
    details = write_details(root, f"session-{resolved_id[:8]}", __import__("json").dumps(session, default=str, indent=2))
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
    """Monitor agentic work: active sessions, one session, or one task.

    Default examples:
      st sessions monitor -P agent-hub
      st sessions monitor task-abc123
      st sessions monitor 1bc090d2 -P agent-hub

    Output is compact and diagnostic-first: status/lifecycle, health/phase,
    model, task/external id, quiet time, tool/command, topic, touched files,
    lifecycle codes, and error/stall excerpt when present.
    """
    if target and target.startswith("task-"):
        from .exec_monitor import exec_log_command

        exec_log_command(
            ctx,
            task_id=target,
            follow=follow,
            limit=limit,
            debug=debug,
            history=history,
            json_output=json_output,
        )
        return

    if target:
        monitor_single_session(
            target,
            project_id=project_id,
            limit=limit,
            debug=debug,
            errors=errors,
            follow=follow,
        )
        return

    client = STClient(require_project=False)
    resolved_project_id = project_id or get_project_override()
    try:
        monitor_overview(
            client,
            project_id=resolved_project_id,
            status_filter=status_filter,
            limit=limit,
            agent_slug=agent_slug,
            json_output=json_output,
            follow=follow,
        )
    except APIError as e:
        handle_api_error(e)
        return
    except KeyboardInterrupt:
        print("[Stopped]")


@app.command("reap")
def reap_sessions_cmd(
    project_id: Annotated[str | None, typer.Option("--project", "-P")] = None,
    dry_run: Annotated[
        bool,
        typer.Option("--dry-run", help="Preview reapable sessions without closing them"),
    ] = False,
) -> None:
    """Close only sessions already marked reapable by Agent Hub lifecycle state."""
    client = STClient(require_project=False)
    reap_sessions(client, project_id=project_id, dry_run=dry_run)


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
