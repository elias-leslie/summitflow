"""Persona CLI — manage the first-class persona identity."""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Annotated, Any

import typer

from ..output import output_error

app = typer.Typer(help="Manage the persona identity")
_Opt = typer.Option
_Arg = typer.Argument


def _read_file(path: str) -> str:
    """Read content from a file, exiting on missing file."""
    p = Path(path)
    if not p.is_file():
        output_error(f"File not found: {path}")
        raise typer.Exit(1)
    return p.read_text(encoding="utf-8")


def _field_status(persona: dict[str, Any], field: str) -> str:
    """Return 'set (N chars)' or 'unset' for a persona field."""
    val = persona.get(field)
    return f"set ({len(val)} chars)" if val else "unset"


def _print_persona(persona: dict[str, Any]) -> None:
    """Print persona overview in compact format."""
    preview = ""
    if persona.get("personality"):
        lines = persona["personality"].strip().splitlines()
        preview = lines[0][:60] if lines else ""
    print(f"persona | {persona.get('name', '?')} | agent={persona.get('agent_slug', '?')}")
    print(f"  voice={persona.get('voice_id', '?')} enabled={persona.get('voice_enabled', False)}")
    print(f"  heartbeat={persona.get('heartbeat_interval_minutes', 0)}m")
    mode = persona.get("session_reset_mode", "off")
    if mode == "daily":
        detail = f" hour={persona.get('session_reset_hour', 0)}"
    elif mode == "idle":
        detail = f" idle={persona.get('session_reset_idle_minutes', 30)}m"
    else:
        detail = ""
    print(f"  session_reset={mode}{detail}")
    print(f"  personality_v{persona.get('version', 0)}: {preview}")
    print(f"  heartbeat_instructions: {_field_status(persona, 'heartbeat_instructions')}")
    print(f"  user_context: {_field_status(persona, 'user_context')}")
    if persona.get("onboarding_phase"):
        print(f"  onboarding_phase: {persona['onboarding_phase']}")


@app.command()
def show() -> None:
    """Show full persona configuration."""
    from .persona_api import get_persona
    try:
        _print_persona(get_persona())
    except Exception as e:
        output_error(f"Failed to fetch persona: {e}")
        raise typer.Exit(1) from e


def _apply_file_and_scalar_fields(
    fields: dict[str, Any],
    heartbeat_instructions: str | None,
    user_context: str | None,
    voice_enabled: bool | None,
    voice_id: str | None,
    heartbeat_interval: int | None,
    session_reset_mode: str | None,
    session_reset_hour: int | None,
    greeting: str | None,
) -> None:
    """Populate fields dict from provided update arguments."""
    if heartbeat_instructions is not None:
        fields["heartbeat_instructions"] = _read_file(heartbeat_instructions)
    if user_context is not None:
        fields["user_context"] = _read_file(user_context)
    if voice_enabled is not None:
        fields["voice_enabled"] = voice_enabled
    if voice_id is not None:
        fields["voice_id"] = voice_id
    if heartbeat_interval is not None:
        fields["heartbeat_interval_minutes"] = heartbeat_interval
    if session_reset_mode is not None:
        fields["session_reset_mode"] = session_reset_mode
    if session_reset_hour is not None:
        fields["session_reset_hour"] = session_reset_hour
    if greeting is not None:
        fields["greeting"] = greeting


@app.command()
def update(
    heartbeat_instructions: Annotated[str | None, _Opt("--heartbeat-instructions", "-H", help="File with heartbeat instructions")] = None,
    user_context: Annotated[str | None, _Opt("--user-context", "-U", help="File with user context")] = None,
    voice_enabled: Annotated[bool | None, _Opt("--voice-enabled/--no-voice", help="Toggle voice")] = None,
    voice_id: Annotated[str | None, _Opt("--voice-id", help="Voice ID string")] = None,
    heartbeat_interval: Annotated[int | None, _Opt("--heartbeat-interval", help="Minutes between heartbeats (0-1440)")] = None,
    session_reset_mode: Annotated[str | None, _Opt("--session-reset-mode", help="off, daily, or idle")] = None,
    session_reset_hour: Annotated[int | None, _Opt("--session-reset-hour", help="Hour (0-23) for daily reset")] = None,
    greeting: Annotated[str | None, _Opt("--greeting", help="Greeting message")] = None,
    limits: Annotated[str | None, _Opt("--limits", help="JSON file for limits")] = None,
) -> None:
    """Update persona fields. Text fields accept file paths."""
    from .persona_api import update_persona
    fields: dict[str, Any] = {}
    _apply_file_and_scalar_fields(
        fields, heartbeat_instructions, user_context, voice_enabled, voice_id,
        heartbeat_interval, session_reset_mode, session_reset_hour, greeting,
    )
    if limits is not None:
        content = _read_file(limits)
        try:
            fields["limits"] = json.loads(content)
        except json.JSONDecodeError as e:
            output_error(f"Invalid JSON in limits file: {e}")
            raise typer.Exit(1) from e
    if not fields:
        output_error("No fields specified. Use --help to see available flags.")
        raise typer.Exit(1)
    try:
        result = update_persona(fields)
        print(f"Persona updated (version {result.get('version', '?')})")
        for key, val in fields.items():
            if isinstance(val, str) and len(val) > 50:
                print(f"  {key}: set ({len(val)} chars)")
            else:
                print(f"  {key}: {val}")
    except Exception as e:
        output_error(f"Failed to update persona: {e}")
        raise typer.Exit(1) from e


def _edit_text_in_editor(current_text: str, suffix: str = ".md") -> str | None:
    """Open text in $EDITOR via a temp file; return new text or None if unchanged."""
    editor = os.environ.get("EDITOR", "vi")
    with tempfile.NamedTemporaryFile(suffix=suffix, mode="w", encoding="utf-8", delete=False) as f:
        f.write(current_text)
        tmp_path = f.name
    try:
        subprocess.run([editor, tmp_path], check=True)
        new_text = Path(tmp_path).read_text(encoding="utf-8")
        if new_text.strip() == current_text.strip():
            return None
        return new_text
    except subprocess.CalledProcessError as e:
        output_error("Editor exited with error")
        raise typer.Exit(1) from e
    finally:
        os.unlink(tmp_path)


def _edit_personality_in_editor(current: dict[str, Any]) -> None:
    """Open personality in $EDITOR and persist changes."""
    from .persona_api import update_personality
    new_text = _edit_text_in_editor(current.get("personality") or "")
    if new_text is None:
        print("No changes made.")
        return
    result = update_personality(new_text, reason="Edited via st persona personality --edit")
    print(f"Personality updated (version {result.get('version', '?')})")


def _maybe_report_dispatch(
    client: Any, project: str | None, reported: bool
) -> bool:
    """Show dispatch hint once; return updated reported flag."""
    if reported or not client:
        return reported
    hint = _get_dispatch_hint(client, project)
    if hint:
        print(f"\n  {hint}", end="", flush=True)
        return True
    return reported


@app.command()
def personality(
    edit: Annotated[bool, _Opt("--edit", "-e", help="Open $EDITOR to modify personality")] = False,
    set_text: Annotated[str | None, _Opt("--set", "-s", help="Set personality text directly")] = None,
) -> None:
    """Print or modify the personality document."""
    from .persona_api import get_personality, update_personality
    if edit and set_text is not None:
        output_error("--edit and --set are mutually exclusive")
        raise typer.Exit(1)
    if set_text is not None:
        try:
            result = update_personality(set_text, reason="Set via st persona personality --set")
            print(f"Personality updated (version {result.get('version', '?')})")
        except Exception as e:
            output_error(f"Failed to update personality: {e}")
            raise typer.Exit(1) from e
        return
    if edit:
        try:
            current = get_personality()
        except Exception as e:
            output_error(f"Failed to fetch personality: {e}")
            raise typer.Exit(1) from e
        _edit_personality_in_editor(current)
        return
    try:
        data = get_personality()
    except Exception as e:
        output_error(f"Failed to fetch personality: {e}")
        raise typer.Exit(1) from e
    print(data["personality"] if data.get("personality") else "(No personality document set)")


@app.command()
def name(
    new_name: Annotated[str | None, _Arg(help="New name for the persona")] = None,
) -> None:
    """Show or set the persona's display name."""
    from .persona_api import get_persona, update_persona
    if new_name is not None:
        try:
            result = update_persona({"name": new_name})
            print(f"Name updated: {result.get('name', new_name)}")
        except Exception as e:
            output_error(f"Failed to update name: {e}")
            raise typer.Exit(1) from e
        return
    try:
        persona = get_persona()
        print(persona.get("name", "Unknown"))
    except Exception as e:
        output_error(f"Failed to fetch persona: {e}")
        raise typer.Exit(1) from e


def _edit_instructions_in_editor(current: dict[str, Any]) -> None:
    """Open heartbeat instructions in $EDITOR and persist changes."""
    from .persona_api import update_persona
    new_text = _edit_text_in_editor(current.get("heartbeat_instructions") or "")
    if new_text is None:
        print("No changes made.")
        return
    result = update_persona({"heartbeat_instructions": new_text})
    print(f"Heartbeat instructions updated (version {result.get('version', '?')})")


@app.command()
def instructions(
    edit: Annotated[bool, _Opt("--edit", "-e", help="Open $EDITOR to modify")] = False,
    set_text: Annotated[str | None, _Opt("--set", "-s", help="Set heartbeat instructions directly")] = None,
) -> None:
    """Print or modify heartbeat instructions."""
    from .persona_api import get_persona, update_persona
    if edit and set_text is not None:
        output_error("--edit and --set are mutually exclusive")
        raise typer.Exit(1)
    if set_text is not None:
        try:
            result = update_persona({"heartbeat_instructions": set_text})
            print(f"Heartbeat instructions updated (version {result.get('version', '?')})")
        except Exception as e:
            output_error(f"Failed to update heartbeat instructions: {e}")
            raise typer.Exit(1) from e
        return
    try:
        persona = get_persona()
    except Exception as e:
        output_error(f"Failed to fetch persona: {e}")
        raise typer.Exit(1) from e
    if edit:
        _edit_instructions_in_editor(persona)
        return
    text = persona.get("heartbeat_instructions")
    print(text if text else "(No heartbeat instructions set)")


@app.command()
def heartbeat(
    watch: Annotated[bool, _Opt("--watch", "-w", help="Poll until heartbeat completes")] = False,
    project: Annotated[str | None, _Opt("--project", "-P", help="Target project for this manual heartbeat")] = None,
) -> None:
    """Trigger a heartbeat. With --watch, poll until it finishes."""
    import time

    from ..client import STClient
    from .persona_api import get_heartbeat_status, trigger_heartbeat

    try:
        result = trigger_heartbeat(project)
        print(f"Heartbeat {result.get('status', 'dispatched')}: {result.get('message', '')}")
    except Exception as e:
        error_msg = str(e)
        if "409" in error_msg:
            print("Heartbeat already running")
        elif "400" in error_msg:
            output_error("Onboarding not complete")
            raise typer.Exit(1) from e
        elif "403" in error_msg:
            output_error("Heartbeat permission is off")
            raise typer.Exit(1) from e
        else:
            output_error(f"Trigger failed: {e}")
            raise typer.Exit(1) from e

    if not watch:
        return

    # Poll until done
    pulse_client = STClient(require_project=False) if project else None
    reported_dispatch = False
    print("Watching...", end="", flush=True)
    while True:
        time.sleep(10)
        try:
            status = get_heartbeat_status()
            if not status.get("running"):
                print()  # newline after progress dots
                _print_heartbeat_result(status)
                return
            reported_dispatch = _maybe_report_dispatch(pulse_client, project, reported_dispatch)
            elapsed = status.get("elapsed_seconds", 0)
            print(f"\r  Running... {elapsed}s elapsed", end="", flush=True)
        except Exception:
            print(".", end="", flush=True)


def _print_heartbeat_result(status: dict[str, Any]) -> None:
    """Print heartbeat completion summary with session metrics."""
    sid = status.get("last_session_id", "?")
    last_run = status.get("last_run", "?")
    turns = status.get("last_turns")
    tool_calls = status.get("last_tool_calls")
    fmt = status.get("last_format_compliant")
    had_error = status.get("last_had_error")
    auto_journal = status.get("last_auto_journaled")

    print(f"Heartbeat complete | session={sid}")
    parts = [f"last_run={last_run}"]
    if turns is not None:
        parts.append(f"turns={turns}")
    if tool_calls is not None:
        parts.append(f"tool_calls={tool_calls}")
    if fmt is not None:
        parts.append(f"format_ok={'yes' if fmt else 'NO'}")
    if had_error is not None:
        parts.append(f"errors={'YES' if had_error else 'none'}")
    if auto_journal:
        parts.append("auto_journaled=yes")
    print(f"  {' | '.join(parts)}")


def _get_dispatch_hint(client: Any, project_id: str | None) -> str | None:
    """Return a one-line dispatch hint from the canonical project pulse."""
    if not project_id:
        return None

    payload = client.get(client._global_url(f"/projects/{project_id}/pulse"))
    running_tasks = payload.get("running_tasks", []) if isinstance(payload, dict) else []
    active_owners = payload.get("active_owners", []) if isinstance(payload, dict) else []
    active_sessions = payload.get("active_sessions", []) if isinstance(payload, dict) else []
    if not running_tasks:
        return None

    task = running_tasks[0] if isinstance(running_tasks[0], dict) else {}
    owner = active_owners[0] if active_owners and isinstance(active_owners[0], dict) else {}
    session = active_sessions[0] if active_sessions and isinstance(active_sessions[0], dict) else {}
    task_id = task.get("id") or "?"
    title = str(task.get("title") or "")[:70]
    agent_slug = owner.get("agent_slug") or session.get("agent_slug") or "agent"
    session_id = str(owner.get("session_id") or session.get("id") or "")[:8]
    return f"Dispatch detected: {task_id} | {agent_slug} | {session_id} | {title}"


@app.command()
def activity(
    hours: Annotated[int, _Opt("--hours", "-H", help="Lookback hours (default 24)")] = 24,
    limit: Annotated[int, _Opt("--limit", "-n", help="Max sessions to show")] = 10,
) -> None:
    """Show recent persona activity sessions."""
    from .persona_api import get_activity

    # Map hours to time_range string
    if hours <= 6:
        time_range = "6h"
    elif hours <= 24:
        time_range = "24h"
    elif hours <= 168:
        time_range = "7d"
    else:
        time_range = "30d"

    try:
        data = get_activity(time_range=time_range, page_size=limit)
    except Exception as e:
        output_error(f"Failed to fetch activity: {e}")
        raise typer.Exit(1) from e

    sessions = data.get("sessions", [])
    total = data.get("total", 0)
    if not sessions:
        print(f"No activity in last {time_range}")
        return

    print(f"Activity ({len(sessions)}/{total} sessions, {time_range}):")
    for s in sessions:
        ts = s.get("created_at", "?")
        if isinstance(ts, str) and len(ts) > 19:
            ts = ts[:19]  # Trim to YYYY-MM-DDTHH:MM:SS
        stype = s.get("session_type", "?")
        summary = s.get("summary_oneliner") or "(no summary)"
        status = s.get("status", "?")
        msgs = s.get("message_count", 0)
        print(f"  {ts} | {stype:<11} | {status:<10} | {msgs:>3} msgs | {summary[:60]}")


@app.command()
def status() -> None:
    """Show heartbeat state and persona overview."""
    from .persona_api import get_heartbeat_status, get_persona

    try:
        hb = get_heartbeat_status()
        persona = get_persona()
    except Exception as e:
        output_error(f"Failed to fetch status: {e}")
        raise typer.Exit(1) from e

    # Heartbeat line
    running = hb.get("running", False)
    state = "running" if running else "idle"
    last = hb.get("last_run", "never")
    interval = hb.get("interval_minutes", 0)
    elapsed = hb.get("elapsed_seconds")

    if running and elapsed is not None:
        hb_line = f"Heartbeat: {state} ({elapsed}s) | Last: {last} | Interval: {interval}m"
    else:
        hb_line = f"Heartbeat: {state} | Last: {last} | Interval: {interval}m"

    print(hb_line)

    # Persona line
    name = persona.get("name", "?")
    onboarding = persona.get("onboarding_phase", "?")
    print(f"Persona: {name} | Onboarding: {onboarding}")
