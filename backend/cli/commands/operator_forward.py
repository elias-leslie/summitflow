"""Shared helpers for canonical st command wrappers around existing tools."""

from __future__ import annotations

import shutil
import subprocess
from collections.abc import Sequence
from pathlib import Path

import typer

from app.utils.shared_paths import resolve_script

from ..output import output_error


def resolve_command(command: str) -> str:
    """Resolve a wrapper command from PATH or SummitFlow scripts."""
    if command.endswith(".sh") or command in {"sf-browser", "proxmox-vm.sh"}:
        script = resolve_script(command)
        if script.exists():
            return str(script)

    from_path = shutil.which(command)
    if from_path:
        return str(Path(from_path).resolve())

    output_error(f"Missing operator tool: {command}")
    raise typer.Exit(127) from None


def run_forwarded(command: str, args: Sequence[str]) -> None:
    """Run a resolved command with streamed stdout/stderr and matching exit code."""
    resolved = resolve_command(command)
    result = subprocess.run([resolved, *args], check=False)
    raise typer.Exit(result.returncode) from None


def run_forwarded_with_input(command: str, args: Sequence[str], input_text: str) -> None:
    """Run a resolved command with stdin text and matching exit code."""
    resolved = resolve_command(command)
    result = subprocess.run([resolved, *args], input=input_text, text=True, check=False)
    raise typer.Exit(result.returncode) from None
