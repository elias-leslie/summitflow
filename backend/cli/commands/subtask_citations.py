"""Subtask citation commands."""

from __future__ import annotations

from typing import Annotated

import typer

from ..client import APIError, STClient
from ..output import handle_api_error, output_error, output_success

app = typer.Typer(help="Citation management for subtasks")


def _validate_citations_args(citations: list[str] | None, none: bool) -> None:
    """Validate mutual exclusivity and completeness of citation args."""
    if none and citations:
        output_error("Cannot use --none with citations. Choose one.")
        raise typer.Exit(1)
    if not none and not citations:
        output_error("Provide citations or use --none to confirm none were needed.")
        raise typer.Exit(1)


def _handle_no_citations(client: STClient, task_id: str, subtask_id: str) -> None:
    """Acknowledge that no memory citations were applicable."""
    try:
        result = client.acknowledge_no_citations(task_id, subtask_id)
    except APIError as e:
        handle_api_error(e)
        return

    if result.get("acknowledged"):
        output_success(
            f"Confirmed: no memories from <memory-context> applied to subtask {subtask_id}. "
            "If this is incorrect, cite the relevant memories now."
        )
    else:
        output_error("Failed to acknowledge")
        raise typer.Exit(1)


def _handle_log_citations(
    client: STClient, task_id: str, subtask_id: str, citations: list[str]
) -> None:
    """Log episode citations for a subtask."""
    try:
        result = client.log_citations(task_id, subtask_id, citations)
    except APIError as e:
        handle_api_error(e)
        return

    logged = result.get("logged", 0)
    output_success(f"Logged {logged} citations for subtask {subtask_id}")


@app.command("citations")
def log_citations_cmd(
    citations: Annotated[
        list[str] | None,
        typer.Argument(help="Citations in suffix notation (M:abc123+ G:def456-)"),
    ] = None,
    subtask_id: Annotated[str | None, typer.Option("--subtask", "-s", help="Subtask ID")] = None,
    task_id: Annotated[str | None, typer.Option("--task", "-t", help="Task ID")] = None,
    none: Annotated[bool, typer.Option("--none", help="Confirm no memories were needed")] = False,
) -> None:
    """Log memory citations: M:<id>+ helpful, G:<id>- harmful, M:<id> used.

    --none only when no injected memory applied. Task defaults to the active context.

    \b
    st subtask citations M:abc12345+ G:def67890- -s 1.1
    st subtask citations --none -s 1.1
    """
    from ..context import require_task_id

    task_id = require_task_id(task_id)
    if not subtask_id:
        output_error("Subtask ID required (--subtask/-s)")
        raise typer.Exit(1)

    _validate_citations_args(citations, none)

    client = STClient()

    if none:
        _handle_no_citations(client, task_id, subtask_id)
    else:
        assert citations is not None
        _handle_log_citations(client, task_id, subtask_id, citations)
