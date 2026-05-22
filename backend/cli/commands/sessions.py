"""Agent session and ownership commands for the CLI."""

from __future__ import annotations

import json
import math
from collections import Counter
from typing import Annotated, Any

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

app = typer.Typer(
    help=(
        "Agent session management. Use `st sessions monitor` for agentic "
        "monitoring: active overview, task current attempt, or session detail."
    ),
    invoke_without_command=True,
    no_args_is_help=False,
)

_ERROR_TEXT_MARKERS = (
    "traceback",
    "error",
    "exception",
    "failed",
    "test:fail",
    "valueerror",
    "typeerror",
    "use 'st check",
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
) -> list[dict[str, Any]]:
    """Return the most recent session events, fetching the last page if needed."""
    page_size = max(min(limit, 500), 1)
    first = get_session_events(session_id, event_type=event_type, page=1, page_size=page_size)
    total = int(first.get("total") or 0)
    if total <= page_size:
        return list(first.get("events") or [])
    page = max(math.ceil(total / page_size), 1)
    latest = get_session_events(session_id, event_type=event_type, page=page, page_size=page_size)
    return list(latest.get("events") or [])


def _event_text(event: dict[str, Any]) -> str:
    parts: list[str] = []
    for key in ("content", "tool_output", "message", "error"):
        value = event.get(key)
        if value is None:
            continue
        if isinstance(value, str):
            parts.append(value)
        else:
            try:
                parts.append(json.dumps(value, default=str, sort_keys=True))
            except TypeError:
                parts.append(str(value))
    return "\n".join(parts)


def _event_signature(event: dict[str, Any]) -> str:
    text = _event_text(event)
    if not text:
        return "-"
    normalized = " ".join(text.replace("\n", " ").split())
    return normalized if len(normalized) <= 180 else normalized[:177] + "..."


def _is_error_like(event: dict[str, Any], signature: str) -> bool:
    if str(event.get("event_type") or "").lower() == "error":
        return True
    lower = signature.lower()
    return any(marker in lower for marker in _ERROR_TEXT_MARKERS)


def _diagnostic_rows(
    events: list[dict[str, Any]],
) -> tuple[
    list[tuple[str, int, dict[str, Any]]],
    list[tuple[str, int, dict[str, Any]]],
]:
    signatures: list[str] = []
    first_by_signature: dict[str, dict[str, Any]] = {}
    for event in events:
        signature = _event_signature(event)
        if signature == "-":
            continue
        signatures.append(signature)
        first_by_signature.setdefault(signature, event)

    counts = Counter(signatures)
    error_rows = [
        (sig, count, first_by_signature[sig])
        for sig, count in counts.items()
        if _is_error_like(first_by_signature[sig], sig)
    ]
    error_rows.sort(key=lambda row: (-row[1], row[0]))
    repeat_rows = [
        (sig, count, first_by_signature[sig])
        for sig, count in counts.most_common()
        if count >= 3
    ]
    return error_rows, repeat_rows


def _render_session_diagnostics(session_id: str, *, limit: int) -> None:
    sample_limit = max(min(limit * 25, 500), min(limit, 500), 100)
    events = _recent_session_events(session_id, limit=sample_limit, event_type=None)
    error_rows, repeat_rows = _diagnostic_rows(events)
    row_limit = max(limit, 1)
    print(_diagnostic_header(session_id, events, error_rows, repeat_rows))
    _print_diagnostic_rows("ERR", error_rows[:row_limit])
    _print_diagnostic_rows(
        "REPEAT",
        repeat_rows[: max(row_limit - min(len(error_rows), row_limit), 0)],
    )


def _diagnostic_header(
    session_id: str,
    events: list[dict[str, Any]],
    error_rows: list[tuple[str, int, dict[str, Any]]],
    repeat_rows: list[tuple[str, int, dict[str, Any]]],
) -> str:
    return (
        f"DIAG session={session_id[:8]} events_sampled={len(events)} "
        f"errors={len(error_rows)} repeats={len(repeat_rows)}"
    )


def _print_diagnostic_rows(prefix: str, rows: list[tuple[str, int, dict[str, Any]]]) -> None:
    for signature, count, event in rows:
        print(
            f"{prefix} x{count}|type={event.get('event_type', '-')}|"
            f"tool={event.get('tool_name', '-')}|{signature}"
        )


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
        _render_session_diagnostics(resolved_id, limit=limit)
        return
    if follow:
        follow_session_events(resolved_id, None, debug, limit)
        return
    for event in _recent_session_events(resolved_id, limit=limit, event_type=None):
        print(format_event(event, verbose=debug))


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
    project_id: Annotated[
        str | None,
        typer.Option("--project", "-P", help="Project scope for short session ID lookup."),
    ] = None,
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
    project_id: Annotated[
        str | None,
        typer.Option("--project", "-P", help="Project scope for short session ID lookup."),
    ] = None,
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
    target: Annotated[
        str | None,
        typer.Argument(help="Task ID, session ID/prefix, or empty for active sessions"),
    ] = None,
    project_id: Annotated[
        str | None, typer.Option("--project", "-P", help="Project scope")
    ] = None,
    status_filter: Annotated[
        str, typer.Option("--status", "-s", help="Session status for overview")
    ] = "active",
    agent_slug: Annotated[
        str | None, typer.Option("--agent", help="Agent slug filter for overview")
    ] = None,
    follow: Annotated[
        bool, typer.Option("-f", "--follow", help="Follow events in real time")
    ] = False,
    limit: Annotated[
        int, typer.Option("-n", "--limit", help="Maximum events to show")
    ] = 20,
    debug: Annotated[
        bool, typer.Option("--debug", help="Include debug-level events")
    ] = False,
    errors: Annotated[
        bool, typer.Option("--errors", help="Show only error events for a session target")
    ] = False,
    history: Annotated[
        bool, typer.Option("--history", help="Include older linked Agent Hub sessions")
    ] = False,
    json_output: Annotated[
        bool, typer.Option("--json", help="Output as JSON")
    ] = False,
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

    if target:
        _monitor_single_session(
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
        return
    except KeyboardInterrupt:
        print("[Stopped]")


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
