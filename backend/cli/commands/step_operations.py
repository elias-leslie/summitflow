"""Core step operations: pass, new, update, delete."""

from __future__ import annotations

from typing import Any

import typer

from ..client import APIError, STClient
from ..context import require_task_id
from ..output import handle_api_error, output_success


def pass_step(
    subtask_id: str,
    step_number: int,
    task_id: str | None = None,
    already_verified: bool = False,
) -> None:
    """Mark a step as passed.

    Runs the verify_command (exit 0 = pass).
    If verification fails, guides you toward fixing the implementation
    or creating a fix subtask if the plan is wrong.

    If no task_id is provided, uses the active context from 'st work'.

    Examples:
        st step pass 1.1 1 --task task-abc123
        st step pass 1.1 1    # Uses active context
    """
    task_id = require_task_id(task_id)
    client = STClient()

    try:
        client.update_step(task_id, subtask_id, step_number, passes=True,
                           already_verified=already_verified)
    except APIError as e:
        detail: dict[str, Any] = e.detail if isinstance(e.detail, dict) else {}
        if detail.get("verification_failed"):
            _handle_verification_failure(detail, subtask_id, step_number)
        handle_api_error(e)
        return

    output_success(f"{subtask_id}.{step_number}")


def _handle_verification_failure(
    detail: dict[str, Any],
    subtask_id: str,
    step_number: int,
) -> None:
    """Handle verification failure with TOON-efficient output."""
    exit_code = detail.get("exit_code", 1)
    output = detail.get("output", "").strip() or "(empty)"
    cwd = detail.get("cwd") or "(unknown)"
    cmd = detail.get("verify_command") or "(unknown)"

    if len(output) > 100:
        output = output[:100] + "..."
    if len(cmd) > 80:
        cmd = cmd[:80] + "..."

    typer.echo(f"STEP_FAIL:{subtask_id}.{step_number}|exit={exit_code}", err=True)
    typer.echo(f"  cwd: {cwd}", err=True)
    typer.echo(f"  cmd: {cmd}", err=True)
    typer.echo(f"  got: {output}", err=True)
    typer.echo(
        f"FIX: 1) impl 2) st step defect {subtask_id} {step_number} "
        f"-v 'correct_cmd'",
        err=True,
    )
    raise typer.Exit(1) from None


def new_step(
    subtask_id: str,
    description: str,
    verify_command: str,
    task_id: str | None = None,
) -> None:
    """Create a single step with required verification.

    Every step must have a verify_command (exit 0 = pass).
    If no task_id is provided, uses the active context from 'st work'.

    Examples:
        st step new 1.1 "Add login endpoint" -v "rg 'def login' api.py" --task task-abc123
        st step new 1.1 "Run tests" -v "dt pytest"    # Uses active context
    """
    task_id = require_task_id(task_id)
    client = STClient()

    try:
        result = client.create_step_with_verification(
            task_id, subtask_id, description, verify_command
        )
    except APIError as e:
        handle_api_error(e)
        return

    step_num = result.get("step_number", "?")
    output_success(f"{subtask_id}.{step_num}")


def update_step(
    subtask_id: str,
    step_number: int,
    description: str | None = None,
    verify_command: str | None = None,
    task_id: str | None = None,
) -> None:
    """Update step description only.

    NOTE: verify_command is immutable after creation.
    If verification is wrong, create a fix subtask instead of modifying the plan.

    If no task_id is provided, uses the active context from 'st work'.

    Examples:
        st step update 1.1 1 -d "Clearer description" --task task-abc123
        st step update 1.1 1 -d "Clearer description"    # Uses active context
    """
    if verify_command is not None:
        _error_immutable_verification()

    if not description:
        typer.echo("Error: --desc/-d is required (only description can be updated)", err=True)
        raise typer.Exit(1)

    task_id = require_task_id(task_id)
    client = STClient()

    try:
        client.update_step_fields(
            task_id,
            subtask_id,
            step_number,
            description=description,
        )
    except APIError as e:
        handle_api_error(e)
        return

    output_success(f"{subtask_id}.{step_number}")


def _error_immutable_verification() -> None:
    """Show error message for immutable verification attempts."""
    typer.echo(
        "Error: verify_command is immutable after creation.\n"
        "\n"
        "Verification gates define the contract. If the step fails:\n"
        "  1. Fix your implementation to match the expected behavior\n"
        "  2. If the plan is wrong, create a fix subtask: st subtask create <id> ...\n"
        "  3. Log the issue: st log <task-id> 'Plan defect: ...'\n"
        "\n"
        "Do NOT modify verification to make failing steps pass.",
        err=True,
    )
    raise typer.Exit(1)


def delete_step(
    subtask_id: str,
    step_number: int,
    task_id: str | None = None,
    force: bool = False,
) -> None:
    """Delete a step from a subtask.

    If the step has already passed verification, --force is required.
    Deleting passed steps will INVALIDATE the parent subtask's passes status
    as a safeguard against gaming the verification system.

    If no task_id is provided, uses the active context from 'st work'.

    Examples:
        st step delete 1.1 3 --task task-abc123
        st step delete 1.1 3             # Uses active context
        st step delete 1.1 3 --force     # Force delete passed step
    """
    task_id = require_task_id(task_id)
    client = STClient()

    try:
        result = client.delete_step(task_id, subtask_id, step_number, force=force)
    except APIError as e:
        detail: dict[str, Any] = e.detail if isinstance(e.detail, dict) else {}
        if detail.get("requires_force"):
            _error_force_required(subtask_id, step_number)
        handle_api_error(e)
        return

    _show_deletion_result(result, subtask_id, step_number)


def _error_force_required(subtask_id: str, step_number: int) -> None:
    """Show error for force-required deletion."""
    typer.echo(
        f"BLOCKED: Step {subtask_id}.{step_number} has passed verification.\n"
        f"  Use --force to delete (will invalidate subtask passes status).\n"
        f"  This is a safeguard against gaming the verification system.",
        err=True,
    )
    raise typer.Exit(1) from None


def _show_deletion_result(
    result: dict[str, Any],
    subtask_id: str,
    step_number: int,
) -> None:
    """Show deletion result with audit info."""
    was_passed = result.get("was_passed", False)
    subtask_invalidated = result.get("subtask_invalidated", False)

    if subtask_invalidated:
        typer.echo(
            f"DEL {subtask_id}.{step_number} (was passed, subtask invalidated)",
            err=True,
        )
    elif was_passed:
        typer.echo(f"DEL {subtask_id}.{step_number} (was passed)")
    else:
        print(f"DEL {subtask_id}.{step_number}")
