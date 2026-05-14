"""Session monitor rendering and diagnostics helpers."""

from __future__ import annotations

import json
import math
from collections import Counter
from typing import Any

from ..client import APIError, STClient
from ..output import handle_api_error, is_compact, output_json
from ._session_resolver import resolve_session_id as _resolve_session_id
from .session_events_follow import follow_session_events
from .session_events_formatter import format_event
from .sessions_list import (
    _normalize_status_filter,
    _session_live_state,
    _session_matches_status_alias,
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


def _project_arg(project_id: str | None) -> str:
    return f" -P {project_id}" if project_id and project_id != "-" else ""


def _session_value(session: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = session.get(key)
        if value:
            return str(value)
    return "-"


def _live_summary_fields(live: dict[str, Any]) -> dict[str, str]:
    command = str(
        live.get("current_command")
        or live.get("last_command")
        or live.get("last_validation_command")
        or "-"
    )
    if len(command) > 120:
        command = command[:117] + "..."

    files = "-"
    touched = live.get("files_touched")
    if isinstance(touched, list) and touched:
        files = ",".join(str(path) for path in touched[-3:])[:140]

    reason_codes = "-"
    codes = live.get("lifecycle_reason_codes")
    if isinstance(codes, list) and codes:
        reason_codes = ",".join(str(code) for code in codes[:4])

    quiet = "-"
    if live.get("quiet_for_seconds") is not None:
        quiet = f"{live.get('quiet_for_seconds')}s"

    error_excerpt = live.get("last_tool_error_excerpt") or live.get("stall_reason")
    return {
        "phase": str(live.get("phase") or "-"),
        "health": str(live.get("health") or live.get("status") or "-"),
        "quiet": quiet,
        "tool": str(live.get("current_tool_name") or live.get("last_tool_name") or "-"),
        "command": command,
        "topic": str(live.get("current_topic") or live.get("last_topic") or "-"),
        "files": files,
        "reason_codes": reason_codes,
        "error": f"|err={str(error_excerpt)[:120]}" if error_excerpt else "",
    }


def _session_monitor_summary(session: dict[str, Any]) -> str:
    session_id = str(session.get("id") or "-")
    project_id = str(session.get("project_id") or "-")
    status = str(session.get("status") or "-")
    agent = str(session.get("agent_slug") or "-")
    provider = _session_value(session, "effective_provider", "requested_provider", "provider")
    model = _session_value(session, "effective_model", "requested_model", "model").split("/")[-1]
    summary: dict[str, str] = {
        "phase": "-",
        "health": "-",
        "quiet": "-",
        "tool": "-",
        "command": "-",
        "topic": "-",
        "files": "-",
        "reason_codes": "-",
        "error": "",
    }
    live = session.get("live_activity")
    if isinstance(live, dict):
        summary.update(_live_summary_fields(live))
    task_id = _session_value(session, "task_id", "external_id")
    state = _session_live_state(session)
    return (
        f"MON {project_id}|{agent}|{session_id[:8]}|{status}/{state}|"
        f"{summary['health']}/{summary['phase']}|model={provider}/{model}|task={task_id}|quiet={summary['quiet']}|"
        f"tool={summary['tool']}|cmd={summary['command']}|topic={summary['topic']}|files={summary['files']}|"
        f"codes={summary['reason_codes']}{summary['error']}"
    )


def _render_monitor_sessions(sessions: list[dict[str, Any]]) -> None:
    print(f"MONITOR[{len(sessions)}]")
    for session in sessions:
        print(_session_monitor_summary(session))
    project = next((str(s.get("project_id")) for s in sessions if s.get("project_id")), None)
    project_flag = _project_arg(project)
    print(
        "MORE:"
        f"detail=st sessions monitor <sid>{project_flag} -n 20; "
        f"full=st session-events <sid>{project_flag} --verbose; "
        f"errors=st sessions monitor <sid>{project_flag} --errors; "
        f"json=st sessions monitor{project_flag} --json"
    )


def _recent_session_events(
    session_id: str,
    *,
    limit: int,
    event_type: str | None,
    get_session_events_fn: Any,
) -> list[dict[str, Any]]:
    page_size = max(min(limit, 500), 1)
    first = get_session_events_fn(session_id, event_type=event_type, page=1, page_size=page_size)
    total = int(first.get("total") or 0)
    if total <= page_size:
        return list(first.get("events") or [])
    page = max(math.ceil(total / page_size), 1)
    latest = get_session_events_fn(session_id, event_type=event_type, page=page, page_size=page_size)
    return list(latest.get("events") or [])


def _clip(text: str, length: int = 180) -> str:
    normalized = " ".join(text.replace("\n", " ").split())
    if len(normalized) <= length:
        return normalized
    return normalized[: length - 3] + "..."


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
    return _clip(text, 180)


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


def _print_diagnostic_rows(prefix: str, rows: list[tuple[str, int, dict[str, Any]]]) -> None:
    for signature, count, event in rows:
        event_type = str(event.get("event_type") or "-")
        tool = str(event.get("tool_name") or "-")
        print(f"{prefix} x{count}|type={event_type}|tool={tool}|{signature}")


def render_session_diagnostics(
    session_id: str,
    *,
    limit: int,
    get_session_events_fn: Any | None = None,
) -> None:
    from .session_events_client import get_session_events as _default_get_session_events

    _get_events = get_session_events_fn if get_session_events_fn is not None else _default_get_session_events
    sample_limit = max(min(limit * 25, 500), min(limit, 500), 100)
    events = _recent_session_events(session_id, limit=sample_limit, event_type=None, get_session_events_fn=_get_events)
    error_rows, repeat_rows = _diagnostic_rows(events)
    row_limit = max(limit, 1)
    print(
        f"DIAG session={session_id[:8]} events_sampled={len(events)} "
        f"errors={len(error_rows)} repeats={len(repeat_rows)}"
    )
    _print_diagnostic_rows("ERR", error_rows[:row_limit])
    remaining = row_limit - min(len(error_rows), row_limit)
    _print_diagnostic_rows("REPEAT", repeat_rows[: max(remaining, 0)])


def monitor_single_session(
    session_id: str,
    *,
    project_id: str | None,
    limit: int,
    debug: bool,
    errors: bool,
    follow: bool,
    get_session_events_fn: Any | None = None,
) -> None:
    from .session_events_client import get_session_events as _default_get_session_events

    _get_events = get_session_events_fn if get_session_events_fn is not None else _default_get_session_events
    client = STClient(require_project=False)
    resolved_id = _resolve_session_id(session_id, client, project_id=project_id)
    try:
        session = client.get_session(resolved_id)
    except APIError as e:
        handle_api_error(e)
        return
    print(_session_monitor_summary(session))
    session_project = str(session.get("project_id") or project_id or "-")
    project_flag = _project_arg(session_project)
    short_id = resolved_id[:8]
    print(
        "MORE:"
        f"events=st session-events {short_id}{project_flag} --verbose; "
        f"errors=st sessions monitor {short_id}{project_flag} --errors; "
        f"raw=st sessions show {short_id}{project_flag} --raw; "
        f"json=st sessions monitor {short_id}{project_flag} --json"
    )
    if errors:
        render_session_diagnostics(resolved_id, limit=limit, get_session_events_fn=_get_events)
        return
    if follow:
        follow_session_events(resolved_id, None, debug, limit)
        return
    for event in _recent_session_events(resolved_id, limit=limit, event_type=None, get_session_events_fn=_get_events):
        print(format_event(event, verbose=debug))


def list_monitor_sessions(
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


def render_or_output_monitor_sessions(
    sessions: list[dict[str, Any]],
    *,
    json_output: bool,
) -> bool:
    if json_output or not is_compact():
        output_json(sessions)
        return True
    _render_monitor_sessions(sessions)
    return False


def monitor_overview(
    client: STClient,
    *,
    project_id: str | None,
    status_filter: str,
    limit: int,
    agent_slug: str | None,
    json_output: bool,
    follow: bool,
) -> None:
    sessions = list_monitor_sessions(
        client,
        status_filter=status_filter,
        limit=limit,
        agent_slug=agent_slug,
        project_id=project_id,
    )
    if render_or_output_monitor_sessions(sessions, json_output=json_output) or not follow:
        return
    import time

    while True:
        time.sleep(2)
        sessions = list_monitor_sessions(
            client,
            status_filter=status_filter,
            limit=limit,
            agent_slug=agent_slug,
            project_id=project_id,
        )
        _render_monitor_sessions(sessions)
