"""Stable JSON and status output primitives for ST extensions."""

from __future__ import annotations

import json
import sys
from typing import Any

import typer

from . import state
from .config import Config
from .http import APIError


def output_json(data: Any) -> None:
    print(json.dumps(data, default=str, indent=2 if state.is_human() else None))


def output_error(message: str) -> None:
    if state.is_compact():
        print(f"ERROR {message}", file=sys.stderr)
    else:
        print(json.dumps({"error": message}), file=sys.stderr)


def output_success(message: str) -> None:
    if state.is_compact():
        print(f"PASS {message}")
    else:
        output_json({"success": True, "message": message})


def output_warning(message: str) -> None:
    if state.is_compact():
        print(f"WARN {message}", file=sys.stderr)
    else:
        print(json.dumps({"warning": message}), file=sys.stderr)


def handle_api_error(error: APIError) -> None:
    detail = error.detail
    if isinstance(detail, dict):
        message = detail.get("message", str(detail))
        available_agents = detail.get("available_agents", [])
        if available_agents:
            output_error(message)
            print("\nAvailable agents:", file=sys.stderr)
            for agent in available_agents:
                print(f"  {agent}", file=sys.stderr)
            raise typer.Exit(1)
        output_error(str(message))
        raise typer.Exit(1)
    if isinstance(detail, list):
        messages = [item.get("msg", str(item)) for item in detail if isinstance(item, dict)]
        output_error("; ".join(messages) if messages else str(detail))
        raise typer.Exit(1)
    output_error(str(detail))
    raise typer.Exit(1)


def require_explicit_project(config: Config) -> None:
    """Compatibility no-op; project resolution is enforced by ``get_config``."""
    _ = config

