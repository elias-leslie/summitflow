"""JSON output formatters for CLI.

All output functions emit JSON for AI agent consumption.
Default: compact JSON (single-line). Use --human for pretty-printed.
"""

from __future__ import annotations

import json
import sys
from typing import TYPE_CHECKING, Any

import typer

if TYPE_CHECKING:
    from .client import APIError

# Module-level flag for human-readable output
_human_output: bool = False


def set_human_output(enabled: bool) -> None:
    """Enable or disable human-readable (pretty-printed) output."""
    global _human_output
    _human_output = enabled


def output_json(data: Any) -> None:
    """Output data as JSON to stdout.

    Default: compact single-line JSON for AI consumption.
    With --human flag: pretty-printed with indent=2.
    """
    indent = 2 if _human_output else None
    print(json.dumps(data, default=str, indent=indent))


def output_task(task: dict[str, Any]) -> None:
    """Output a single task as JSON."""
    output_json(task)


def output_task_list(tasks: list[dict[str, Any]]) -> None:
    """Output a list of tasks as JSON."""
    output_json({"tasks": tasks, "total": len(tasks)})


def output_deps(deps: list[dict[str, Any]]) -> None:
    """Output dependency list as JSON."""
    output_json(deps)


def output_capabilities(caps: list[dict[str, Any]]) -> None:
    """Output capabilities as JSON."""
    output_json(caps)


def output_tests(tests: list[dict[str, Any]]) -> None:
    """Output tests as JSON."""
    output_json(tests)


def output_error(message: str) -> None:
    """Output error message to stderr as JSON."""
    print(json.dumps({"error": message}), file=sys.stderr)


def output_success(message: str) -> None:
    """Output success message as JSON."""
    output_json({"success": True, "message": message})


def output_warning(message: str) -> None:
    """Output warning message to stderr as JSON."""
    print(json.dumps({"warning": message}), file=sys.stderr)


def handle_api_error(e: APIError) -> None:
    """Handle API error and exit.

    Args:
        e: APIError exception from client
    """
    output_error(e.detail)
    raise typer.Exit(1)
