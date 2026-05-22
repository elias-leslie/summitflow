"""Session monitor helpers for the sessions CLI commands."""

from __future__ import annotations

import time
from typing import Any

import typer

from ..client import STClient
from ..output import is_compact, output_json
from .sessions_filter import normalize_status_filter, session_matches_status_alias
from .sessions_format import monitor_summary


def monitor_more(project_flag: str) -> str:
    """Return the 'MORE:' hint line for monitor overview output."""
    return (
        f"MORE:"
        f"detail=st sessions monitor <sid>{project_flag} -n 20; "
        f"full=st session-events <sid>{project_flag} --verbose; "
        f"errors=st sessions monitor <sid>{project_flag} --errors; "
        f"json=st sessions monitor{project_flag} --json"
    )


def monitor_detail_more(short_id: str, project_flag: str) -> str:
    """Return the 'MORE:' hint line for single-session monitor output."""
    return (
        "MORE:"
        f"events=st session-events {short_id}{project_flag} --verbose; "
        f"errors=st sessions monitor {short_id}{project_flag} --errors; "
        f"raw=st sessions show {short_id}{project_flag} --raw; "
        f"json=st sessions monitor {short_id}{project_flag} --json"
    )


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
    """Delegate to exec_monitor for task-ID targets."""
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


def render_monitor_sessions(sessions: list[dict[str, Any]]) -> None:
    """Print a compact MONITOR block for a list of sessions."""
    print(f"MONITOR[{len(sessions)}]")
    for session in sessions:
        print(monitor_summary(session))
    print(monitor_more(_monitor_project_flag(sessions)))


def _monitor_project_flag(sessions: list[dict[str, Any]]) -> str:
    project = next((str(s.get("project_id")) for s in sessions if s.get("project_id")), None)
    return f" -P {project}" if project and project != "-" else ""


def list_monitor_sessions(
    client: STClient,
    *,
    status_filter: str,
    limit: int,
    agent_slug: str | None,
    project_id: str | None,
) -> list[dict[str, Any]]:
    """List sessions for the monitor overview, applying status alias filtering."""
    sessions = client.list_sessions(
        status=normalize_status_filter(status_filter),
        limit=limit,
        page=1,
        agent_slug=agent_slug,
        project_id=project_id,
    )
    return [s for s in sessions if session_matches_status_alias(s, status_filter)]


def _render_or_output_monitor_sessions(
    sessions: list[dict[str, Any]], *, json_output: bool
) -> bool:
    if json_output or not is_compact():
        output_json(sessions)
        return True
    render_monitor_sessions(sessions)
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
    """Run the monitor overview, optionally following in a loop."""
    sessions = list_monitor_sessions(
        client,
        status_filter=status_filter,
        limit=limit,
        agent_slug=agent_slug,
        project_id=project_id,
    )
    if _render_or_output_monitor_sessions(sessions, json_output=json_output) or not follow:
        return
    while True:
        time.sleep(2)
        sessions = list_monitor_sessions(
            client,
            status_filter=status_filter,
            limit=limit,
            agent_slug=agent_slug,
            project_id=project_id,
        )
        render_monitor_sessions(sessions)
