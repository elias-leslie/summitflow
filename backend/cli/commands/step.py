"""Step commands for the CLI."""

from __future__ import annotations

from typing import Annotated, Any

import typer

from ..client import APIError, STClient
from ..output import handle_api_error, output_steps, output_success

app = typer.Typer(help="Step management commands")


@app.command("pass")
def pass_step(
    subtask_id: str,
    step_number: int,
    task_id: Annotated[str | None, typer.Option("--task", "-t")] = None,
) -> None:
    """Mark a step as passed.

    Runs the verify_command and checks for expected_output.
    If verification fails, guides you toward fixing the implementation
    or creating a fix subtask if the plan is wrong.

    If no task_id is provided, uses the active context from 'st work'.

    Examples:
        st step pass 1.1 1 --task task-abc123
        st step pass 1.1 1    # Uses active context
    """
    from ..context import require_task_id

    task_id = require_task_id(task_id)
    client = STClient()

    try:
        client.update_step(task_id, subtask_id, step_number, passes=True)
    except APIError as e:
        # Check if this is a verification failure
        detail: dict[str, Any] = e.detail if isinstance(e.detail, dict) else {}
        if detail.get("verification_failed"):
            # TOON-efficient verification failure output
            exit_code = detail.get("exit_code", 1)
            output = detail.get("output", "").strip() or "(empty)"
            # Truncate output to first 100 chars
            if len(output) > 100:
                output = output[:100] + "..."
            typer.echo(f"STEP_FAIL:{subtask_id}.{step_number}|exit={exit_code}", err=True)
            typer.echo(f"  got: {output}", err=True)
            typer.echo(
                f"FIX: 1) impl 2) st step new {subtask_id} 'Fix:...' -v 'cmd' -e 'expect' "
                f"3) st step defect {subtask_id} {step_number} --fix N",
                err=True,
            )
            raise typer.Exit(1) from None
        handle_api_error(e)
        return

    output_success(f"{subtask_id}.{step_number}")


@app.command("new")
def new_step(
    subtask_id: str,
    description: str,
    verify_command: Annotated[
        str, typer.Option("--verify", "-v", help="Bash command to verify completion")
    ],
    expected_output: Annotated[
        str, typer.Option("--expected", "-e", help="What success looks like")
    ],
    task_id: Annotated[str | None, typer.Option("--task", "-t")] = None,
) -> None:
    """Create a single step with required verification.

    Every step must have a verify_command (exit 0 = pass) and expected_output.
    If no task_id is provided, uses the active context from 'st work'.

    Examples:
        st step new 1.1 "Add login endpoint" -v "rg 'def login' api.py" -e "Function exists" --task task-abc123
        st step new 1.1 "Run tests" -v "dt pytest" -e "All tests pass"    # Uses active context
    """
    from ..context import require_task_id

    task_id = require_task_id(task_id)
    client = STClient()

    try:
        result = client.create_step_with_verification(
            task_id, subtask_id, description, verify_command, expected_output
        )
    except APIError as e:
        handle_api_error(e)
        return

    step_num = result.get("step_number", "?")
    output_success(f"{subtask_id}.{step_num}")


@app.command("update")
def update_step(
    subtask_id: str,
    step_number: int,
    verify_command: Annotated[
        str | None,
        typer.Option("--verify", "-v", help="[BLOCKED] Verification commands are immutable"),
    ] = None,
    expected_output: Annotated[
        str | None,
        typer.Option("--expected", "-e", help="[BLOCKED] Expected output is immutable"),
    ] = None,
    description: Annotated[
        str | None, typer.Option("--desc", "-d", help="Step description")
    ] = None,
    task_id: Annotated[str | None, typer.Option("--task", "-t")] = None,
) -> None:
    """Update step description only.

    NOTE: verify_command and expected_output are immutable after creation.
    If verification is wrong, create a fix subtask instead of modifying the plan.

    If no task_id is provided, uses the active context from 'st work'.

    Examples:
        st step update 1.1 1 -d "Clearer description" --task task-abc123
        st step update 1.1 1 -d "Clearer description"    # Uses active context
    """
    from ..context import require_task_id

    # Verification commands are immutable - reject attempts to modify
    if verify_command is not None or expected_output is not None:
        typer.echo(
            "Error: verify_command and expected_output are immutable after creation.\n"
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


@app.command("create")
def create_steps(
    subtask_id: str,
    descriptions: Annotated[list[str], typer.Argument()],
    task_id: Annotated[str | None, typer.Option("--task", "-t")] = None,
) -> None:
    """Create steps for a subtask in batch (no verification).

    Pass multiple step descriptions as arguments.
    NOTE: Steps created this way have no verify_command and cannot be passed
    until verification is added with 'st step update'.

    For steps with verification, use 'st step new' instead.
    If no task_id is provided, uses the active context from 'st work'.

    Examples:
        st step create 1.1 "Step 1" "Step 2" "Step 3" --task task-abc123
        st step create 1.1 "Step 1" "Step 2"    # Uses active context
    """
    from ..context import require_task_id

    task_id = require_task_id(task_id)
    client = STClient()

    try:
        result = client.bulk_create_steps(task_id, subtask_id, descriptions)
    except APIError as e:
        handle_api_error(e)
        return

    created = result.get("created", [])
    output_success(f"{subtask_id}|{len(created)} steps")


@app.command("add")
def add_steps(
    subtask_id: str,
    descriptions: Annotated[list[str], typer.Argument()],
    task_id: Annotated[str | None, typer.Option("--task", "-t")] = None,
) -> None:
    """Append steps to a subtask with existing steps.

    Unlike 'create' which starts at step 1, 'add' finds the highest
    existing step number and continues from there.
    If no task_id is provided, uses the active context from 'st work'.

    Examples:
        st step add 1.1 "New step 6" "New step 7" --task task-abc123
        st step add 1.1 "New step 6" "New step 7"    # Uses active context
    """
    from ..context import require_task_id

    task_id = require_task_id(task_id)
    client = STClient()

    try:
        result = client.append_steps(task_id, subtask_id, descriptions)
    except APIError as e:
        handle_api_error(e)
        return

    created = result.get("created", [])
    if created:
        start_num = created[0].get("step_number", "?")
        output_success(f"{subtask_id}|+{len(created)} from {start_num}")
    else:
        output_success(f"{subtask_id}|+0")


@app.command("list")
def list_steps(
    subtask_id: str,
    task_id: Annotated[str | None, typer.Option("--task", "-t")] = None,
) -> None:
    """List steps for a subtask.

    If no task_id is provided, uses the active context from 'st work'.

    Examples:
        st step list 1.1 --task task-abc123
        st step list 1.1    # Uses active context
    """
    from ..context import require_task_id

    task_id = require_task_id(task_id)
    client = STClient()

    try:
        steps = client.get_steps(task_id, subtask_id)
    except APIError as e:
        handle_api_error(e)
        return

    output_steps(steps, subtask_id)


@app.command("delete")
def delete_step(
    subtask_id: str,
    step_number: int,
    task_id: Annotated[str | None, typer.Option("--task", "-t")] = None,
    force: Annotated[
        bool,
        typer.Option("--force", "-f", help="Force deletion of passed steps (invalidates subtask)"),
    ] = False,
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
    from ..context import require_task_id

    task_id = require_task_id(task_id)
    client = STClient()

    try:
        result = client.delete_step(task_id, subtask_id, step_number, force=force)
    except APIError as e:
        # Check if this is a force-required error
        detail: dict[str, Any] = e.detail if isinstance(e.detail, dict) else {}
        if detail.get("requires_force"):
            typer.echo(
                f"BLOCKED: Step {subtask_id}.{step_number} has passed verification.\n"
                f"  Use --force to delete (will invalidate subtask passes status).\n"
                f"  This is a safeguard against gaming the verification system.",
                err=True,
            )
            raise typer.Exit(1) from None
        handle_api_error(e)
        return

    # Show deletion with audit info
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


@app.command("insert")
def insert_step(
    subtask_id: str,
    position: int,
    description: str,
    task_id: Annotated[str | None, typer.Option("--task", "-t")] = None,
) -> None:
    """Insert a step at a specific position, shifting existing steps down.

    Use this to add work before an incomplete step. All steps at the
    insertion position and after are renumbered (incremented by 1).
    If no task_id is provided, uses the active context from 'st work'.

    Examples:
        st step insert 1.1 3 "Complete dark mode cleanup" --task task-abc123
        st step insert 1.1 3 "Complete dark mode cleanup"    # Uses active context
    """
    from ..context import require_task_id

    task_id = require_task_id(task_id)
    client = STClient()

    try:
        result = client.insert_step(task_id, subtask_id, position, description)
    except APIError as e:
        handle_api_error(e)
        return

    step_num = result.get("step_number", position)
    output_success(f"{subtask_id}.{step_num}")


@app.command("defect")
def mark_plan_defect(
    subtask_id: str,
    step_number: int,
    fix_step: Annotated[
        int,
        typer.Option("--fix", "-f", help="Step number of the PASSED fix step (e.g., 3)"),
    ],
    task_id: Annotated[str | None, typer.Option("--task", "-t")] = None,
) -> None:
    """Mark a step as a plan defect with a linked fix step.

    Use this when a step's verification is fundamentally wrong (wrong path,
    wrong API, impossible expected_output). This allows the subtask to be
    passed without fixing the broken verification.

    REQUIRED: You must first create and pass a fix step within the same subtask
    that has the correct verification. The --fix flag links to that passed step.

    Workflow:
    1. Add fix step:    st step add <subtask> "Fix: correct verification"
    2. Pass fix step:   st step pass <subtask> <fix_step>
    3. Mark defect:     st step defect <subtask> <step> --fix <fix_step>

    If no task_id is provided, uses the active context from 'st work'.

    Examples:
        st step defect 1.1 1 --fix 3 --task task-abc123
        st step defect 2.3 1 --fix 4              # Uses active context
    """
    from ..context import require_task_id

    task_id = require_task_id(task_id)
    client = STClient()

    try:
        client.update_step_status(
            task_id, subtask_id, step_number, status="plan_defect", fix_step_number=fix_step
        )
    except APIError as e:
        handle_api_error(e)
        return

    output_success(f"{subtask_id}.{step_number}|defect→{fix_step}")
