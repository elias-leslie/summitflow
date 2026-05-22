"""Session compact-format and monitor-summary helpers for the sessions CLI commands."""

from __future__ import annotations

from typing import Any, cast

from .sessions_filter import live_state as _live_state


def session_field(session: dict[str, Any], *keys: str) -> str:
    """Return the first non-empty value for the given keys, or '-'."""
    for key in keys:
        if value := session.get(key):
            return str(value)
    return "-"


def compact_session_line(session: dict[str, Any]) -> str:
    """Format a session as a single compact line for CLI output."""
    session_id = str(session.get("id") or "-")
    project_id = str(session.get("project_id") or "-")
    status = str(session.get("status") or "-")
    agent = str(session.get("agent_slug") or "-")
    task_id = str(session.get("task_id") or "-")
    state = _live_state(session)
    updated = str(session.get("updated_at") or "-")
    return (
        f"SES {project_id} | {status} | {agent} | {session_id[:8]} | "
        f"task={task_id} state={state} updated={updated}"
    )


def live_activity_summary(live: dict[str, Any]) -> dict[str, str]:
    """Return a flat summary dict of live_activity fields."""
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
    cmd = str(
        live.get("current_command")
        or live.get("last_command")
        or live.get("last_validation_command")
        or "-"
    )
    return cmd[:117] + "..." if len(cmd) > 120 else cmd


def _live_activity_files(live: dict[str, Any]) -> str:
    touched = live.get("files_touched")
    return (
        ",".join(str(p) for p in touched[-3:])[:140]
        if isinstance(touched, list) and touched
        else "-"
    )


def _live_activity_reason_codes(live: dict[str, Any]) -> str:
    codes = live.get("lifecycle_reason_codes")
    return ",".join(str(c) for c in codes[:4]) if isinstance(codes, list) and codes else "-"


def _live_activity_quiet(live: dict[str, Any]) -> str:
    return f"{live['quiet_for_seconds']}s" if live.get("quiet_for_seconds") is not None else "-"


def _live_activity_error(live: dict[str, Any]) -> str:
    error_excerpt = live.get("last_tool_error_excerpt") or live.get("stall_reason")
    return f"|err={str(error_excerpt)[:120]}" if error_excerpt else ""


def monitor_summary_fields(live: object) -> dict[str, str]:
    """Return monitor summary fields from a live_activity object (or empty if missing)."""
    if isinstance(live, dict):
        return live_activity_summary(cast(dict[str, Any], live))
    return empty_monitor_summary()


def empty_monitor_summary() -> dict[str, str]:
    """Return a blank monitor summary dict."""
    return {
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


def monitor_summary(session: dict[str, Any]) -> str:
    """Format a session as a single compact MON line."""
    session_id = str(session.get("id") or "-")
    project_id = str(session.get("project_id") or "-")
    status = str(session.get("status") or "-")
    agent = str(session.get("agent_slug") or "-")
    live = session.get("live_activity")
    provider = session_field(session, "effective_provider", "requested_provider", "provider")
    model = session_field(session, "effective_model", "requested_model", "model").split("/")[-1]
    state = _live_state(session)
    summary = monitor_summary_fields(live)
    task_id = session_field(session, "task_id", "external_id")
    return (
        f"MON {project_id}|{agent}|{session_id[:8]}|{status}/{state}|"
        f"{summary['health']}/{summary['phase']}|model={provider}/{model}|task={task_id}|"
        f"quiet={summary['quiet']}|tool={summary['tool']}|cmd={summary['command']}|"
        f"topic={summary['topic']}|files={summary['files']}|"
        f"codes={summary['reason_codes']}{summary['error']}"
    )
