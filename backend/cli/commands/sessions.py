"""Agent session and ownership commands for the CLI."""

from __future__ import annotations

import json
import math
import time
from collections import Counter
from typing import Annotated, Any, cast

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
from .sessions_overlap import render_overlap_list
from .sessions_ownership import render_ownership_list

app = typer.Typer(
    help=(
        "Agent session management. Use `st sessions monitor` for agentic "
        "monitoring: active overview, task current attempt, or session detail."
    ),
    invoke_without_command=True,
    no_args_is_help=False,
)

_LIVE_STATUS_ALIASES = {"stale", "reapable"}
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


def _normalize_status_filter(status_filter: str | None) -> str | None:
    """Normalize CLI-friendly session status aliases to Agent Hub values."""
    if not status_filter:
        return None
    normalized = status_filter.strip().lower()
    if normalized in {"running", "stale", "reapable"}:
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
    live_state = str(live.get("lifecycle_state") or live.get("status") or live.get("state") or session.get("status") or "-").strip().lower()
    if normalized == "reapable":
        return bool(live.get("reapable")) or live_state == "reapable"
    return bool(live.get("is_stale")) or bool(live.get("reapable")) or live_state in {
        "reapable",
        "stale",
        "stalled",
    }


def _live_state(session: dict[str, Any]) -> str:
    live = session.get("live_activity")
    if not isinstance(live, dict):
        return str(session.get("status") or "-")
    return str(
        live.get("lifecycle_state") or live.get("status") or live.get("state") or session.get("status") or "-"
    ).strip()


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


def _session_field(session: dict[str, Any], *keys: str) -> str:
    for key in keys:
        if value := session.get(key):
            return str(value)
    return "-"


def _live_activity_summary(live: dict[str, Any]) -> dict[str, str]:
    cmd = str(live.get("current_command") or live.get("last_command") or live.get("last_validation_command") or "-")
    if len(cmd) > 120:
        cmd = cmd[:117] + "..."
    touched = live.get("files_touched")
    files = ",".join(str(p) for p in touched[-3:])[:140] if isinstance(touched, list) and touched else "-"
    codes = live.get("lifecycle_reason_codes")
    reason_codes = ",".join(str(c) for c in codes[:4]) if isinstance(codes, list) and codes else "-"
    quiet = f"{live['quiet_for_seconds']}s" if live.get("quiet_for_seconds") is not None else "-"
    error_excerpt = live.get("last_tool_error_excerpt") or live.get("stall_reason")
    return {
        "phase": str(live.get("phase") or "-"),
        "health": str(live.get("health") or live.get("status") or "-"),
        "quiet": quiet,
        "tool": str(live.get("current_tool_name") or live.get("last_tool_name") or "-"),
        "command": cmd,
        "topic": str(live.get("current_topic") or live.get("last_topic") or "-"),
        "files": files,
        "reason_codes": reason_codes,
        "error": f"|err={str(error_excerpt)[:120]}" if error_excerpt else "",
    }


def _monitor_more(project_flag: str) -> str:
    return (
        f"MORE:"
        f"detail=st sessions monitor <sid>{project_flag} -n 20; "
        f"full=st session-events <sid>{project_flag} --verbose; "
        f"errors=st sessions monitor <sid>{project_flag} --errors; "
        f"json=st sessions monitor{project_flag} --json"
    )


def _monitor_detail_more(short_id: str, project_flag: str) -> str:
    return (
        "MORE:"
        f"events=st session-events {short_id}{project_flag} --verbose; "
        f"errors=st sessions monitor {short_id}{project_flag} --errors; "
        f"raw=st sessions show {short_id}{project_flag} --raw; "
        f"json=st sessions monitor {short_id}{project_flag} --json"
    )


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


def _monitor_summary(session: dict[str, Any]) -> str:
    session_id = str(session.get("id") or "-")
    project_id = str(session.get("project_id") or "-")
    status = str(session.get("status") or "-")
    agent = str(session.get("agent_slug") or "-")
    live = session.get("live_activity")
    provider = _session_field(session, "effective_provider", "requested_provider", "provider")
    model = _session_field(session, "effective_model", "requested_model", "model").split("/")[-1]
    live_state = _live_state(session)
    summary = _live_activity_summary(cast(dict[str, Any], live)) if isinstance(live, dict) else {
        "phase": "-", "health": "-", "quiet": "-", "tool": "-",
        "command": "-", "topic": "-", "files": "-", "reason_codes": "-", "error": "",
    }
    task_id = _session_field(session, "task_id", "external_id")
    return (
        f"MON {project_id}|{agent}|{session_id[:8]}|{status}/{live_state}|"
        f"{summary['health']}/{summary['phase']}|model={provider}/{model}|task={task_id}|quiet={summary['quiet']}|"
        f"tool={summary['tool']}|cmd={summary['command']}|topic={summary['topic']}|files={summary['files']}|"
        f"codes={summary['reason_codes']}{summary['error']}"
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


def _monitor_task_target(
    ctx: typer.Context,
    target: str,
    *,
    follow: bool,
    limit: int,
    debug: bool,
    history: bool,
    json_output: bool,
) -> None:
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



def _render_monitor_sessions(sessions: list[dict[str, Any]]) -> None:
    print(f"MONITOR[{len(sessions)}]")
    for session in sessions:
        print(_monitor_summary(session))
    project = next((str(s.get("project_id")) for s in sessions if s.get("project_id")), None)
    project_flag = f" -P {project}" if project and project != "-" else ""
    print(_monitor_more(project_flag))


def _recent_session_events(session_id: str, *, limit: int, event_type: str | None) -> list[dict[str, Any]]:
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
        (signature, count, first_by_signature[signature])
        for signature, count in counts.items()
        if _is_error_like(first_by_signature[signature], signature)
    ]
    error_rows.sort(key=lambda row: (-row[1], row[0]))
    repeat_rows = [
        (signature, count, first_by_signature[signature])
        for signature, count in counts.most_common()
        if count >= 3
    ]
    return error_rows, repeat_rows


def _render_session_diagnostics(session_id: str, *, limit: int) -> None:
    sample_limit = max(min(limit * 25, 500), min(limit, 500), 100)
    events = _recent_session_events(session_id, limit=sample_limit, event_type=None)
    error_rows, repeat_rows = _diagnostic_rows(events)
    row_limit = max(limit, 1)
    print(
        f"DIAG session={session_id[:8]} events_sampled={len(events)} "
        f"errors={len(error_rows)} repeats={len(repeat_rows)}"
    )
    for signature, count, event in error_rows[:row_limit]:
        print(f"ERR x{count}|type={event.get('event_type', '-')}|tool={event.get('tool_name', '-')}|{signature}")
    for signature, count, event in repeat_rows[: max(row_limit - min(len(error_rows), row_limit), 0)]:
        print(f"REPEAT x{count}|type={event.get('event_type', '-')}|tool={event.get('tool_name', '-')}|{signature}")


def _monitor_single_session(
    session_id: str,
    *,
    project_id: str | None,
    limit: int,
    debug: bool,
    errors: bool,
    follow: bool,
) -> None:
    client = STClient(require_project=False)
    resolved_id = _resolve_session_id(session_id, client, project_id=project_id)
    try:
        session = client.get_session(resolved_id)
    except APIError as e:
        handle_api_error(e)
        return
    print(_monitor_summary(session))
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


def _list_monitor_sessions(
    client: STClient,
    *,
    status_filter: str,
    limit: int,
    agent_slug: str | None,
    project_id: str | None,
) -> list[dict[str, Any]]:
    sessions = client.list_sessions(
        status=_normalize_status_filter(status_filter),
        limit=limit,
        page=1,
        agent_slug=agent_slug,
        project_id=project_id,
    )
    return [s for s in sessions if _session_matches_status_alias(s, status_filter)]


def _monitor_overview(
    client: STClient,
    *,
    project_id: str | None,
    status_filter: str,
    limit: int,
    agent_slug: str | None,
    json_output: bool,
    follow: bool,
) -> None:
    def _render_or_output(sessions: list[dict[str, Any]]) -> bool:
        if json_output or not is_compact():
            output_json(sessions)
            return True
        _render_monitor_sessions(sessions)
        return False

    sessions = _list_monitor_sessions(
        client, status_filter=status_filter, limit=limit, agent_slug=agent_slug, project_id=project_id
    )
    if _render_or_output(sessions) or not follow:
        return
    while True:
        time.sleep(2)
        sessions = _list_monitor_sessions(
            client, status_filter=status_filter, limit=limit, agent_slug=agent_slug, project_id=project_id
        )
        _render_monitor_sessions(sessions)


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
            "reapable_sessions": [_reapable_session_payload(session) for session in candidates],
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
            failed.append({"id": session_id, "error": str(e.detail)})
    return closed, failed


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
