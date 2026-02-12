"""Task progress log functionality."""

from __future__ import annotations

from datetime import UTC, datetime

import typer

from ..client import APIError, STClient
from ..output import handle_api_error, output_json


def append_task_log(
    message: str,
    task_id: str,
    client: STClient,
) -> None:
    """Append a log entry to a task's progress log."""
    entry = _build_log_entry(message)

    try:
        result = client.append_log(task_id, entry)
    except APIError as e:
        handle_api_error(e)
        raise typer.Exit(1) from None

    output_json(result)


def _build_log_entry(message: str) -> str:
    """Build a timestamped log entry."""
    timestamp = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    return f"[{timestamp}] {message}"
