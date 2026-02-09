"""Plan defect handling for steps with incorrect verification."""

from __future__ import annotations

from typing import Any

import typer

from ..client import APIError, STClient
from ..context import require_task_id
from ..output import handle_api_error, output_success


def mark_plan_defect(
    subtask_id: str,
    step_number: int,
    fix_step: int | None = None,
    verify_command: str | None = None,
    expected_output: str | None = None,
    task_id: str | None = None,
) -> None:
    """Mark a step as a plan defect with a linked fix step.

    Use this when a step's verification is fundamentally wrong (wrong path,
    wrong API, impossible expected_output). This allows the subtask to be
    passed without fixing the broken verification.

    Two modes:

    1. Inline (recommended): provide -v and -e to create+pass a fix step automatically.
       st step defect 1.1 4 -v "correct_cmd" -e "correct_expect" -t task-xxx

    2. Reference: provide --fix N pointing to an already-passed fix step.
       st step defect 1.1 4 --fix 6 -t task-xxx

    If no task_id is provided, uses the active context from 'st work'.

    Examples:
        st step defect 1.1 4 -v "rg 'def login' api.py" -e "Found" -t task-abc123
        st step defect 2.3 1 --fix 4
    """
    has_inline = verify_command is not None or expected_output is not None
    has_ref = fix_step is not None

    _validate_defect_mode(has_inline, has_ref, verify_command, expected_output)

    task_id = require_task_id(task_id)
    client = STClient()

    if has_inline:
        assert verify_command is not None
        assert expected_output is not None
        _handle_inline_fix(
            client, task_id, subtask_id, step_number, verify_command, expected_output
        )
    else:
        assert fix_step is not None
        _handle_reference_fix(client, task_id, subtask_id, step_number, fix_step)


def _validate_defect_mode(
    has_inline: bool,
    has_ref: bool,
    verify_command: str | None,
    expected_output: str | None,
) -> None:
    """Validate that exactly one defect mode is used."""
    if has_inline and has_ref:
        typer.echo("Error: provide either --fix OR both -v/-e, not both.", err=True)
        raise typer.Exit(1)

    if not has_inline and not has_ref:
        typer.echo("Error: provide --fix N (existing fix step) or -v/-e (inline fix).", err=True)
        raise typer.Exit(1)

    if has_inline and (verify_command is None or expected_output is None):
        typer.echo(
            "Error: both -v (verify) and -e (expected) are required for inline fix.", err=True
        )
        raise typer.Exit(1)


def _handle_inline_fix(
    client: STClient,
    task_id: str,
    subtask_id: str,
    step_number: int,
    verify_command: str,
    expected_output: str,
) -> None:
    """Handle inline fix: create fix step, pass it, mark original as defect."""
    fix_step_num = _create_fix_step(
        client, task_id, subtask_id, step_number, verify_command, expected_output
    )

    _pass_fix_step(client, task_id, subtask_id, fix_step_num)

    _mark_as_defect(client, task_id, subtask_id, step_number, fix_step_num)

    output_success(f"{subtask_id}.{step_number}|defect→{fix_step_num}")


def _create_fix_step(
    client: STClient,
    task_id: str,
    subtask_id: str,
    step_number: int,
    verify_command: str,
    expected_output: str,
) -> int:
    """Create a fix step with corrected verification."""
    try:
        result = client.create_step_with_verification(
            task_id,
            subtask_id,
            f"Fix: corrected verification for step {step_number}",
            verify_command,
            expected_output,
        )
    except APIError as e:
        handle_api_error(e)
        raise typer.Exit(1) from None

    fix_step_num = result.get("step_number")
    if not isinstance(fix_step_num, int):
        typer.echo("Error: failed to get fix step number from API response.", err=True)
        raise typer.Exit(1)

    return fix_step_num


def _pass_fix_step(
    client: STClient,
    task_id: str,
    subtask_id: str,
    fix_step_num: int,
) -> None:
    """Pass the fix step (runs verify_command — quality gate preserved)."""
    try:
        client.update_step(task_id, subtask_id, fix_step_num, passes=True)
    except APIError as e:
        detail: dict[str, Any] = e.detail if isinstance(e.detail, dict) else {}
        if detail.get("verification_failed"):
            _error_fix_verification_failed(subtask_id, fix_step_num, detail)
        handle_api_error(e)
        raise typer.Exit(1) from None


def _error_fix_verification_failed(
    subtask_id: str,
    fix_step_num: int,
    detail: dict[str, Any],
) -> None:
    """Show error when fix step verification fails."""
    output = detail.get("output", "").strip() or "(empty)"
    if len(output) > 100:
        output = output[:100] + "..."

    typer.echo(
        f"Fix step {subtask_id}.{fix_step_num} verification FAILED. "
        f"Fix your -v/-e and retry.",
        err=True,
    )
    typer.echo(f"  got: {output}", err=True)
    raise typer.Exit(1) from None


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


def _handle_reference_fix(
    client: STClient,
    task_id: str,
    subtask_id: str,
    step_number: int,
    fix_step: int,
) -> None:
    """Handle reference fix: mark original as defect pointing to existing fix."""
    try:
        client.update_step_status(
            task_id, subtask_id, step_number, status="plan_defect", fix_step_number=fix_step
        )
    except APIError as e:
        handle_api_error(e)
        raise typer.Exit(1) from None

    output_success(f"{subtask_id}.{step_number}|defect→{fix_step}")
