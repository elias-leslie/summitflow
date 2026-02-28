"""Plan defect handling for steps."""

from __future__ import annotations

import typer

from ..client import APIError, STClient
from ..context import require_task_id
from ..output import handle_api_error, output_success


def mark_plan_defect(
    subtask_id: str,
    step_number: int,
    fix_step: int,
    task_id: str | None = None,
) -> None:
    """Mark a step as a plan defect with a linked fix step.

    Use this when a step's plan is fundamentally wrong. This allows the subtask
    to be passed without the broken step blocking progress.

    Provide --fix N pointing to an already-passed fix step.

    If no task_id is provided, uses the active context from 'st work'.

    Examples:
        st step defect 1.1 4 --fix 6 -t task-abc123
        st step defect 2.3 1 --fix 4
    """
    task_id = require_task_id(task_id)
    client = STClient()

    _mark_as_defect(client, task_id, subtask_id, step_number, fix_step)
    output_success(f"{subtask_id}.{step_number}|defect→{fix_step}")


def _mark_as_defect(
    client: STClient,
    task_id: str,
    subtask_id: str,
    step_number: int,
    fix_step_num: int,
) -> None:
    """Mark original step as plan_defect."""
    try:
        client.update_step_status(
            task_id, subtask_id, step_number, status="plan_defect", fix_step_number=fix_step_num
        )
    except APIError as e:
        handle_api_error(e)
        raise typer.Exit(1) from None
