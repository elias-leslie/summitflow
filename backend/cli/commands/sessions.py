"""Agent session and ownership commands for the CLI."""

from __future__ import annotations

import json
import math
from collections.abc import Iterable
from typing import Annotated, cast

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
from .sessions_diagnostics import render_diagnostics as _render_diagnostics
from .sessions_filter import normalize_status_filter, session_matches_status_alias
from .sessions_format import compact_session_line, monitor_summary
from .sessions_monitor import (
    monitor_detail_more as _monitor_detail_more,
)
from .sessions_monitor import (
    monitor_overview as _monitor_overview,
)
from .sessions_monitor import (
    monitor_task_target as _monitor_task_target,
)
from .sessions_overlap import render_overlap_list
from .sessions_ownership import render_ownership_list
from .sessions_reap import (
    close_reapable_sessions as _close_reapable_sessions,
)
from .sessions_reap import (
    list_all_active_sessions as _list_all_active_sessions,
)
from .sessions_reap import (
    reapable_session_payload as _reapable_session_payload,
)
from .sessions_reap import (
    reapable_sessions as _reapable_sessions,
)

SessionStatusOption = Annotated[str | None, typer.Option("-s", "--status")]
SessionLimitOption = Annotated[int, typer.Option("--limit")]
SessionAgentOption = Annotated[str | None, typer.Option("--agent")]
ParentSessionOption = Annotated[str | None, typer.Option("--parent-session")]
ProjectOption = Annotated[str | None, typer.Option("--project", "-P")]
ProjectLookupOption = Annotated[
    str | None,
    typer.Option("--project", "-P", help="Project scope for short session ID lookup."),
]
IncludeUnassignedOption = Annotated[
    bool,
    typer.Option(
        "--include-unassigned",
        help="Include imported/unassigned sessions without an agent slug",
    ),
]
RawSessionOption = Annotated[bool, typer.Option("--raw", help="Print full raw session JSON.")]
MonitorTargetArg = Annotated[
    str | None,
    typer.Argument(help="Task ID, session ID/prefix, or empty for active sessions"),
]
MonitorProjectOption = Annotated[str | None, typer.Option("--project", "-P", help="Project scope")]
MonitorStatusOption = Annotated[
    str,
    typer.Option("--status", "-s", help="Session status for overview"),
]
MonitorAgentOption = Annotated[
    str | None,
    typer.Option("--agent", help="Agent slug filter for overview"),
]
MonitorFollowOption = Annotated[
    bool,
    typer.Option("-f", "--follow", help="Follow events in real time"),
]
MonitorLimitOption = Annotated[
    int,
    typer.Option("-n", "--limit", help="Maximum events to show"),
]
MonitorDebugOption = Annotated[
    bool,
    typer.Option("--debug", help="Include debug-level events"),
]
MonitorErrorsOption = Annotated[
    bool,
    typer.Option("--errors", help="Show only error events for a session target"),
]
MonitorHistoryOption = Annotated[
    bool,
    typer.Option("--history", help="Include older linked Agent Hub sessions"),
]
JsonOutputOption = Annotated[bool, typer.Option("--json", help="Output as JSON")]
ReapDryRunOption = Annotated[
    bool,
    typer.Option("--dry-run", help="Preview reapable sessions without closing them"),
]

app = typer.Typer(
    help=(
        "Agent session management. Use `st sessions monitor` for agentic "
        "monitoring: active overview, task current attempt, or session detail."
    ),
    invoke_without_command=True,
    no_args_is_help=False,
)

def _event_total(payload: dict[str, object]) -> int:
    return int(cast(int | str | bytes | bytearray, payload.get("total") or 0))


def _event_records(payload: dict[str, object]) -> list[dict[str, object]]:
    return list(cast(Iterable[dict[str, object]], payload.get("events") or []))


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
    normalized_status = normalize_status_filter(status_filter)
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

    sessions = [s for s in sessions if session_matches_status_alias(s, status_filter)]
    if not include_unassigned:
        sessions = [s for s in sessions if s.get("agent_slug")]

    if is_compact():
        print(f"SESSIONS[{len(sessions)}]")
        for session in sessions:
            print(compact_session_line(session))
        return
    output_json(sessions)


def _recent_session_events(
    session_id: str, *, limit: int, event_type: str | None
) -> list[dict[str, object]]:
    """Return the most recent session events, fetching the last page if needed."""
    page_size = max(min(limit, 500), 1)
    first = cast(
        dict[str, object],
        get_session_events(session_id, event_type=event_type, page=1, page_size=page_size),
    )
    total = _event_total(first)
    if total <= page_size:
        return _event_records(first)
    page = max(math.ceil(total / page_size), 1)
    latest = cast(
        dict[str, object],
        get_session_events(session_id, event_type=event_type, page=page, page_size=page_size),
    )
    return _event_records(latest)


def _monitor_single_session(
    session_id: str,
    *,
    project_id: str | None,
    limit: int,
    debug: bool,
    errors: bool,
    follow: bool,
) -> None:
    """Print monitor output for a single session by ID or short prefix."""
    client = STClient(require_project=False)
    resolved_id = _resolve_session_id(session_id, client, project_id=project_id)
    try:
        session = client.get_session(resolved_id)
    except APIError as e:
        handle_api_error(e)
        return

    print(monitor_summary(session))
    session_project = str(session.get("project_id") or project_id or "-")
    project_flag = f" -P {session_project}" if session_project and session_project != "-" else ""
    short_id = resolved_id[:8]
    print(_monitor_detail_more(short_id, project_flag))
    if errors:
        sample_limit = max(min(limit * 25, 500), min(limit, 500), 100)
        events = _recent_session_events(resolved_id, limit=sample_limit, event_type=None)
        _render_diagnostics(resolved_id, events, limit=limit)
        return
    if follow:
        follow_session_events(resolved_id, None, debug, limit)
        return
    for event in _recent_session_events(resolved_id, limit=limit, event_type=None):
        print(format_event(event, verbose=debug))


def _monitor_target(
    ctx: typer.Context,
    target: str,
    *,
    project_id: str | None,
    follow: bool,
    limit: int,
    debug: bool,
    errors: bool,
    history: bool,
    json_output: bool,
) -> None:
    if target.startswith("task-"):
        _monitor_task_target(
            ctx,
            target,
            follow=follow,
            limit=limit,
            debug=debug,
            history=history,
            json_output=json_output,
        )
        return
    _monitor_single_session(
        target,
        project_id=project_id,
        limit=limit,
        debug=debug,
        errors=errors,
        follow=follow,
    )


def _monitor_overview_command(
    project_id: str | None,
    *,
    status_filter: str,
    limit: int,
    agent_slug: str | None,
    json_output: bool,
    follow: bool,
) -> None:
    client = STClient(require_project=False)
    resolved_project_id = project_id or get_project_override()
    try:
        _monitor_overview(
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
    except KeyboardInterrupt:
        print("[Stopped]")


@app.callback()
def sessions_callback(
    ctx: typer.Context,
    status_filter: SessionStatusOption = None,
    limit: SessionLimitOption = 20,
    agent_slug: SessionAgentOption = None,
    parent_session_id: ParentSessionOption = None,
    project_id: ProjectOption = None,
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
    status_filter: SessionStatusOption = None,
    include_unassigned: IncludeUnassignedOption = True,
    limit: SessionLimitOption = 20,
    agent_slug: SessionAgentOption = None,
    parent_session_id: ParentSessionOption = None,
    project_id: ProjectOption = None,
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
    project_id: ProjectLookupOption = None,
    raw: RawSessionOption = False,
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
    details = write_details(
        root, f"session-{resolved_id[:8]}", json.dumps(session, default=str, indent=2)
    )
    print(
        f"SESSION:{session.get('id', resolved_id)}|project={session.get('project_id', '-')}"
        f"|status={session.get('status', '-')}|details:{display_path(root, details)}"
    )


@app.command("close")
def close_session(
    session_id: str,
    project_id: ProjectLookupOption = None,
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
    target: MonitorTargetArg = None,
    project_id: MonitorProjectOption = None,
    status_filter: MonitorStatusOption = "active",
    agent_slug: MonitorAgentOption = None,
    follow: MonitorFollowOption = False,
    limit: MonitorLimitOption = 20,
    debug: MonitorDebugOption = False,
    errors: MonitorErrorsOption = False,
    history: MonitorHistoryOption = False,
    json_output: JsonOutputOption = False,
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
    if target:
        _monitor_target(
            ctx,
            target,
            project_id=project_id,
            follow=follow,
            limit=limit,
            debug=debug,
            errors=errors,
            history=history,
            json_output=json_output,
        )
        return

    _monitor_overview_command(
        project_id,
        status_filter=status_filter,
        limit=limit,
        agent_slug=agent_slug,
        json_output=json_output,
        follow=follow,
    )


@app.command("reap")
def reap_sessions(
    project_id: ProjectOption = None,
    dry_run: ReapDryRunOption = False,
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
        output_json(
            {
                "project_id": target_project_id,
                "dry_run": True,
                "reapable_count": len(candidates),
                "reapable_sessions": [_reapable_session_payload(s) for s in candidates],
            }
        )
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
    project_id: ProjectOption = None,
) -> None:
    """List live active ownership lanes across projects or for one project."""
    render_ownership_list(STClient(require_project=False), project_id)


@app.command("overlap")
def list_overlaps(
    project_id: ProjectOption = None,
) -> None:
    """List current scope overlaps across active ownership lanes."""
    render_overlap_list(STClient(require_project=False), project_id)
