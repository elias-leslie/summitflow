"""Session monitor command implementation."""

from __future__ import annotations

import json
import math
import time
from collections import Counter
from typing import Annotated, Any, cast

import typer

from ..client import APIError, STClient
from ..config import get_project_override
from ..output import handle_api_error, is_compact, output_json
from ._session_resolver import resolve_session_id as _resolve_session_id
from .session_events_client import get_session_events
from .session_events_follow import follow_session_events
from .session_events_formatter import format_event
from .sessions_shared import live_state as _live_state
from .sessions_shared import normalize_status_filter as _normalize_status_filter
from .sessions_shared import session_matches_status_alias as _session_matches_status_alias

_ERROR_TEXT_MARKERS = (
    "traceback", "error", "exception", "failed", "test:fail",
    "valueerror", "typeerror", "use 'st check",
)

def _session_field(session: dict[str, Any], *keys: str) -> str:
    for key in keys:
        if value := session.get(key):
            return str(value)
    return "-"


def _live_activity_summary(live: dict[str, Any]) -> dict[str, str]:
    return {
        "phase": str(live.get("phase") or "-"),
        "health": str(live.get("health") or live.get("status") or "-"),
        "quiet": _live_activity_quiet(live),
        "tool": str(live.get("current_tool_name") or live.get("last_tool_name") or "-"),
        "command": _live_activity_command(live),
        "topic": str(live.get("current_topic") or live.get("last_topic") or "-"),
        "files": _live_activity_files(live),
        "reason_codes": _live_activity_reason_codes(live),
        "error": _live_activity_error(live),
    }


def _live_activity_command(live: dict[str, Any]) -> str:
    cmd = str(live.get("current_command") or live.get("last_command") or live.get("last_validation_command") or "-")
    return cmd[:117] + "..." if len(cmd) > 120 else cmd


def _live_activity_files(live: dict[str, Any]) -> str:
    touched = live.get("files_touched")
    return ",".join(str(p) for p in touched[-3:])[:140] if isinstance(touched, list) and touched else "-"


def _live_activity_reason_codes(live: dict[str, Any]) -> str:
    codes = live.get("lifecycle_reason_codes")
    return ",".join(str(c) for c in codes[:4]) if isinstance(codes, list) and codes else "-"


def _live_activity_quiet(live: dict[str, Any]) -> str:
    return f"{live['quiet_for_seconds']}s" if live.get("quiet_for_seconds") is not None else "-"


def _live_activity_error(live: dict[str, Any]) -> str:
    error_excerpt = live.get("last_tool_error_excerpt") or live.get("stall_reason")
    return f"|err={str(error_excerpt)[:120]}" if error_excerpt else ""


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
    summary = _monitor_summary_fields(live)
    task_id = _session_field(session, "task_id", "external_id")
    return (
        f"MON {project_id}|{agent}|{session_id[:8]}|{status}/{live_state}|"
        f"{summary['health']}/{summary['phase']}|model={provider}/{model}|task={task_id}|quiet={summary['quiet']}|"
        f"tool={summary['tool']}|cmd={summary['command']}|topic={summary['topic']}|files={summary['files']}|"
        f"codes={summary['reason_codes']}{summary['error']}"
    )


def _monitor_summary_fields(live: object) -> dict[str, str]:
    if isinstance(live, dict):
        return _live_activity_summary(cast(dict[str, Any], live))
    return _empty_monitor_summary()


def _empty_monitor_summary() -> dict[str, str]:
    return {"phase": "-", "health": "-", "quiet": "-", "tool": "-", "command": "-", "topic": "-", "files": "-", "reason_codes": "-", "error": ""}


def monitor_task_target(
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
    print(_monitor_more(_monitor_project_flag(sessions)))


def _monitor_project_flag(sessions: list[dict[str, Any]]) -> str:
    project = next((str(s.get("project_id")) for s in sessions if s.get("project_id")), None)
    return f" -P {project}" if project and project != "-" else ""


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
        print(f"{prefix} x{count}|type={event.get('event_type', '-')}|tool={event.get('tool_name', '-')}|{signature}")


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
    sessions = _list_monitor_sessions(
        client, status_filter=status_filter, limit=limit, agent_slug=agent_slug, project_id=project_id
    )
    if _render_or_output_monitor_sessions(sessions, json_output=json_output) or not follow:
        return
    while True:
        time.sleep(2)
        sessions = _list_monitor_sessions(
            client, status_filter=status_filter, limit=limit, agent_slug=agent_slug, project_id=project_id
        )
        _render_monitor_sessions(sessions)


def _render_or_output_monitor_sessions(sessions: list[dict[str, Any]], *, json_output: bool) -> bool:
    if json_output or not is_compact():
        output_json(sessions)
        return True
    _render_monitor_sessions(sessions)
    return False


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
        monitor_task_target(
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
