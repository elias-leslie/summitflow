"""Persona CLI — manage the first-class persona identity.

Commands:
  st persona show                    — Full persona overview
  st persona personality             — Print personality document
  st persona personality --edit      — Open $EDITOR to modify personality
  st persona personality --set TEXT  — Set personality directly
  st persona name                    — Show current name
  st persona name "NewName"          — Set new name
"""

from __future__ import annotations

import os
import subprocess
import tempfile
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

    print(f"persona | {persona.get('name', '?')} | agent={persona.get('agent_slug', '?')}")
    print(f"  voice={persona.get('voice_id', '?')} enabled={persona.get('voice_enabled', False)}")
    print(f"  heartbeat={persona.get('heartbeat_interval_minutes', 0)}m")
    print(f"  personality_v{persona.get('version', 0)}: {personality_preview}")


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
