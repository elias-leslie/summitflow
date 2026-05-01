"""Core output primitives: JSON, status messages, error handling."""

from __future__ import annotations

import json
import sys
from typing import TYPE_CHECKING, Any

import typer

if TYPE_CHECKING:
    from .client import APIError
    from .config import Config


def output_json(data: Any) -> None:
    """Output data as JSON to stdout."""
    from ._output_state import _human_output as _ho

    indent = 2 if _ho else None
    print(json.dumps(data, default=str, indent=indent))


def output_error(message: str) -> None:
    """Output error message to stderr."""
    from ._output_state import _compact_output as _co

    if _co:
        print(f"ERROR {message}", file=sys.stderr)
    else:
        print(json.dumps({"error": message}), file=sys.stderr)


def output_success(message: str) -> None:
    """Output success message."""
    from ._output_state import _compact_output as _co

    if _co:
        print(f"PASS {message}")
    else:
        output_json({"success": True, "message": message})


def output_warning(message: str) -> None:
    """Output warning message to stderr."""
    from ._output_state import _compact_output as _co

    if _co:
        print(f"WARN {message}", file=sys.stderr)
    else:
        print(json.dumps({"warning": message}), file=sys.stderr)


def handle_api_error(e: APIError) -> None:
    """Handle API error and exit."""
    detail = e.detail
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
    elif isinstance(detail, list):
        # Pydantic validation errors: extract msg from each error
        messages = [err.get("msg", str(err)) for err in detail if isinstance(err, dict)]
        output_error("; ".join(messages) if messages else str(detail))
        raise typer.Exit(1)
    output_error(detail)
    raise typer.Exit(1)


def require_explicit_project(config: Config) -> None:
    """Exit with error if project was resolved from cwd (not explicit flag/env)."""
    if config.source not in ("cwd",):
        return

    from .config import get_available_projects

    available = get_available_projects()
    available_str = ", ".join(available) if available else "(could not fetch)"
    print(
        f"Error: Write commands require explicit project.\n"
        f"Usage: st -P <project> <command> ...\n"
        f"Detected: {config.project_id} (from cwd)\n"
        f"Available: {available_str}",
        file=sys.stderr,
    )
    raise typer.Exit(1)
