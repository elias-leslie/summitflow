"""Subtask commands for the CLI."""

from __future__ import annotations

import re
from typing import Annotated

import typer

from ..client import APIError, STClient
from ..lib.usage import usage
from ..output import handle_api_error, output_error, output_subtasks, output_success

# Re-export for backward compatibility
from .subtask_citations import log_citations_cmd

app = typer.Typer(help="Subtask management commands")

_CITATION_TOKEN_RE = re.compile(r"[MG]:[a-f0-9]{8}[+-]?")


def _normalize_inline_citations(citations: list[str]) -> list[str]:
    if not citations:
        return []
    normalized: list[str] = []
    for citation in citations:
        matches = _CITATION_TOKEN_RE.findall(citation)
        normalized.extend(matches or [citation.strip()])
    return list(dict.fromkeys(item for item in normalized if item))


@app.command("create")
@usage(
    surface="st.subtask.create",
    cmd='st subtask create 1.2 -d "description" --phase implementation',
    when="break a claimed task into discrete subtasks for verification",
    precautions=(
        "subtask IDs are dotted (1.1, 1.2, 2.1); parent task UUID is separate",
        "phase ∈ {implementation, verification, cleanup, ...}",
    ),
    tier="reference",
)
def create_subtask(
    subtask_id: str,
    description: Annotated[str, typer.Option("-d", "--description")],
    task_id: Annotated[str | None, typer.Option("--task", "-t")] = None,
    phase: Annotated[str, typer.Option("--phase")] = "implementation",
) -> None:
    """Create a subtask for a task. Uses active context if no --task given."""
    from ..context import require_task_id

    task_id = require_task_id(task_id)

    client = STClient()
    try:
        client.create_subtask(
            task_id=task_id,
            subtask_id=subtask_id,
            description=description,
            phase=phase,
        )
    except APIError as e:
        handle_api_error(e)
        return

    output_success(subtask_id)


def pass_subtask_internal(
    subtask_id: str,
    task_id: str,
    citations: list[str] | None = None,
    acknowledge_none: bool = False,
) -> None:
    """Internal helper used by `st done <subtask-id> -t <task-id>`.

    Records citations (or acknowledges none) and marks the subtask passed.
    The standalone `st subtask pass` verb is gone — use `st done` instead.
    """
    client = STClient()

    if citations and acknowledge_none:
        output_error("Use either citations or acknowledge_none, not both.")
        raise typer.Exit(1)

    try:
        if citations:
            client.log_citations(task_id, subtask_id, _normalize_inline_citations(citations))
        elif acknowledge_none:
            client.acknowledge_no_citations(task_id, subtask_id)
    except APIError as e:
        handle_api_error(e)
        return

    try:
        client.update_subtask(task_id, subtask_id, passes=True)
    except APIError as e:
        handle_api_error(e)
        return

    output_success(subtask_id)


@app.command("clear")
def clear_subtask(
    subtask_id: str,
    task_id: Annotated[str | None, typer.Option("--task", "-t")] = None,
) -> None:
    """Clear a subtask's passed state."""
    from ..context import require_task_id

    task_id = require_task_id(task_id)
    client = STClient()

    try:
        client.update_subtask(task_id, subtask_id, passes=False)
    except APIError as e:
        handle_api_error(e)
        return

    output_success(subtask_id)


@app.command("delete")
def delete_subtask(
    subtask_id: str,
    task_id: Annotated[str | None, typer.Option("--task", "-t")] = None,
) -> None:
    """Delete a subtask. Uses active context if no --task given."""
    from ..context import require_task_id

    task_id = require_task_id(task_id)
    client = STClient()

    try:
        client.delete_subtask(task_id, subtask_id)
    except APIError as e:
        handle_api_error(e)
        return

    print(f"DEL {subtask_id}")


@app.command("list")
def list_subtasks(
    task_id: Annotated[str | None, typer.Argument(help="Task ID")] = None,
    include_steps: Annotated[
        bool,
        typer.Option("--steps/--no-steps", help="Include step data in JSON output."),
    ] = True,
) -> None:
    """List subtasks for a task. Uses active context if no task ID is given."""
    from ..context import require_task_id

    task_id = require_task_id(task_id)
    client = STClient()
    try:
        response = client.get_subtasks(task_id, include_steps=include_steps)
    except APIError as e:
        handle_api_error(e)
        return
    subtasks = response.get("subtasks") or []
    summary = response.get("summary")
    output_subtasks(subtasks, summary if isinstance(summary, dict) else None)


# Register citations command
app.command("citations")(log_citations_cmd)
