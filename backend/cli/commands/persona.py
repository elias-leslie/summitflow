"""Persona CLI — manage the first-class persona identity.

Commands:
  st persona show                    — Full persona overview
  st persona update --field FILE     — Update any persona field from a file
  st persona personality             — Print personality document
  st persona personality --edit      — Open $EDITOR to modify personality
  st persona personality --set TEXT  — Set personality directly
  st persona name                    — Show current name
  st persona name "NewName"          — Set new name
"""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Annotated

import typer

from ..output import output_error

app = typer.Typer(help="Manage the persona identity")
_Opt = typer.Option
_Arg = typer.Argument


@app.command()
def show() -> None:
    """Show full persona configuration."""
    from .persona_api import get_persona

    try:
        persona = get_persona()
    except Exception as e:
        output_error(f"Failed to fetch persona: {e}")
        raise typer.Exit(1) from e

    # TOON-style compact output
    personality_preview = ""
    if persona.get("personality"):
        lines = persona["personality"].strip().splitlines()
        personality_preview = lines[0][:60] if lines else ""

    def _field_status(field: str) -> str:
        val = persona.get(field)
        if val:
            return f"set ({len(val)} chars)"
        return "unset"

    print(f"persona | {persona.get('name', '?')} | agent={persona.get('agent_slug', '?')}")
    print(f"  voice={persona.get('voice_id', '?')} enabled={persona.get('voice_enabled', False)}")
    print(f"  heartbeat={persona.get('heartbeat_interval_minutes', 0)}m")
    reset_mode = persona.get("session_reset_mode", "off")
    reset_detail = ""
    if reset_mode == "daily":
        reset_detail = f" hour={persona.get('session_reset_hour', 0)}"
    elif reset_mode == "idle":
        reset_detail = f" idle={persona.get('session_reset_idle_minutes', 30)}m"
    print(f"  session_reset={reset_mode}{reset_detail}")
    print(f"  personality_v{persona.get('version', 0)}: {personality_preview}")
    print(f"  heartbeat_instructions: {_field_status('heartbeat_instructions')}")
    print(f"  user_context: {_field_status('user_context')}")
    if persona.get("onboarding_phase"):
        print(f"  onboarding_phase: {persona['onboarding_phase']}")


def _read_file(path: str) -> str:
    """Read content from a file path."""
    p = Path(path)
    if not p.is_file():
        output_error(f"File not found: {path}")
        raise typer.Exit(1)
    return p.read_text()


@app.command()
def update(
    heartbeat_instructions: Annotated[str | None, _Opt("--heartbeat-instructions", "-H", help="File containing heartbeat instructions")] = None,
    user_context: Annotated[str | None, _Opt("--user-context", "-U", help="File containing user context")] = None,
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

    fields: dict = {}

    # Text fields — read from file
    if heartbeat_instructions is not None:
        fields["heartbeat_instructions"] = _read_file(heartbeat_instructions)
    if user_context is not None:
        fields["user_context"] = _read_file(user_context)

    # Scalar fields
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
        for key in fields:
            val = fields[key]
            if isinstance(val, str) and len(val) > 50:
                print(f"  {key}: set ({len(val)} chars)")
            else:
                print(f"  {key}: {val}")
    except Exception as e:
        output_error(f"Failed to update persona: {e}")
        raise typer.Exit(1) from e


@app.command()
def personality(
    edit: Annotated[bool, _Opt("--edit", "-e", help="Open $EDITOR to modify personality")] = False,
    set_text: Annotated[str | None, _Opt("--set", "-s", help="Set personality text directly")] = None,
) -> None:
    """Print or modify the personality document."""
    from .persona_api import get_personality, update_personality

    if set_text is not None:
        # Direct set
        try:
            result = update_personality(set_text, reason="Set via st persona personality --set")
            print(f"Personality updated (version {result.get('version', '?')})")
        except Exception as e:
            output_error(f"Failed to update personality: {e}")
            raise typer.Exit(1) from e
        return

    if edit:
        # Open in $EDITOR
        try:
            current = get_personality()
        except Exception as e:
            output_error(f"Failed to fetch personality: {e}")
            raise typer.Exit(1) from e

        editor = os.environ.get("EDITOR", "vi")
        with tempfile.NamedTemporaryFile(suffix=".md", mode="w", delete=False) as f:
            f.write(current.get("personality") or "")
            tmp_path = f.name

        try:
            subprocess.run([editor, tmp_path], check=True)
            with open(tmp_path) as f:
                new_personality = f.read()

            if new_personality.strip() == (current.get("personality") or "").strip():
                print("No changes made.")
                return

            result = update_personality(new_personality, reason="Edited via st persona personality --edit")
            print(f"Personality updated (version {result.get('version', '?')})")
        except subprocess.CalledProcessError as e:
            output_error("Editor exited with error")
            raise typer.Exit(1) from e
        finally:
            os.unlink(tmp_path)
        return

    # Default: print current personality
    try:
        data = get_personality()
    except Exception as e:
        output_error(f"Failed to fetch personality: {e}")
        raise typer.Exit(1) from e

    if data.get("personality"):
        print(data["personality"])
    else:
        print("(No personality document set)")


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

    # Show current name
    try:
        persona = get_persona()
        print(persona.get("name", "Unknown"))
    except Exception as e:
        output_error(f"Failed to fetch persona: {e}")
        raise typer.Exit(1) from e
