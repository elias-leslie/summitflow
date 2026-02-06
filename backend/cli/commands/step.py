"""Step commands for the CLI."""

from __future__ import annotations

from typing import Annotated, Any

import typer

from ..client import APIError, STClient
from ..output import handle_api_error, output_success

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
            # TOON-efficient verification failure output with debug context
            exit_code = detail.get("exit_code", 1)
            output = detail.get("output", "").strip() or "(empty)"
            cwd = detail.get("cwd") or "(unknown)"
            cmd = detail.get("verify_command") or "(unknown)"
            # Truncate output to first 100 chars
            if len(output) > 100:
                output = output[:100] + "..."
            # Truncate command to 80 chars for display
            if len(cmd) > 80:
                cmd = cmd[:80] + "..."
            typer.echo(f"STEP_FAIL:{subtask_id}.{step_number}|exit={exit_code}", err=True)
            typer.echo(f"  cwd: {cwd}", err=True)
            typer.echo(f"  cmd: {cmd}", err=True)
            typer.echo(f"  got: {output}", err=True)
            typer.echo(
                f"FIX: 1) impl 2) st step defect {subtask_id} {step_number} "
                f"-v 'correct_cmd' -e 'correct_expect'",
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


@app.command("add")
def add_steps(
    subtask_id: str,
    descriptions: list[str] | None = None,
    verify_command: Annotated[
        str | None,
        typer.Option("--verify", "-v", help="Verify command (applied to all steps)"),
    ] = None,
    expected_output: Annotated[
        str | None,
        typer.Option("--expected", "-e", help="Expected output (applied to all steps)"),
    ] = None,
    json_input: Annotated[
        str | None,
        typer.Option(
            "--json",
            help='JSON array: [{"description":"...","verify_command":"...","expected_output":"..."}]',
        ),
    ] = None,
    task_id: Annotated[str | None, typer.Option("--task", "-t")] = None,
) -> None:
    """Add steps to a subtask (verification required).

    Each step must have a verify_command and expected_output.

    Two modes:
    1. Positional descriptions with shared -v/-e (all steps get same verification):
       st step add 1.1 "Step 1" "Step 2" -v "dt pytest" -e "All pass"

    2. JSON for per-step verification:
       st step add 1.1 --json '[{"description":"...","verify_command":"...","expected_output":"..."}]'

    If no task_id is provided, uses the active context from 'st work'.

    Examples:
        st step add 1.1 "Add endpoint" -v "rg 'def foo' api.py" -e "Found" -t task-abc123
        st step add 1.1 --json '[{"description":"Run tests","verify_command":"dt pytest","expected_output":"passed"}]'
    """
    import json

    from ..context import require_task_id

    task_id = require_task_id(task_id)
    client = STClient()

    steps_to_create: list[dict[str, str]] = []

    if json_input is not None:
        if descriptions:
            typer.echo("Error: provide positional descriptions OR --json, not both.", err=True)
            raise typer.Exit(1)
        try:
            parsed = json.loads(json_input)
        except json.JSONDecodeError as e:
            typer.echo(f"Error: invalid JSON: {e}", err=True)
            raise typer.Exit(1) from None
        if not isinstance(parsed, list):
            typer.echo("Error: --json must be a JSON array.", err=True)
            raise typer.Exit(1)
        for item in parsed:
            if not isinstance(item, dict):
                typer.echo("Error: each --json element must be an object.", err=True)
                raise typer.Exit(1)
            missing = [
                k for k in ("description", "verify_command", "expected_output") if k not in item
            ]
            if missing:
                typer.echo(f"Error: JSON element missing keys: {', '.join(missing)}", err=True)
                raise typer.Exit(1)
            steps_to_create.append(
                {
                    "description": item["description"],
                    "verify_command": item["verify_command"],
                    "expected_output": item["expected_output"],
                }
            )
    elif descriptions:
        if verify_command is None or expected_output is None:
            typer.echo(
                "Error: -v (verify) and -e (expected) are required.\n"
                "  Every step needs verification. Use --json for per-step verify commands.",
                err=True,
            )
            raise typer.Exit(1)
        for desc in descriptions:
            steps_to_create.append(
                {
                    "description": desc,
                    "verify_command": verify_command,
                    "expected_output": expected_output,
                }
            )
    else:
        typer.echo("Error: provide step descriptions or --json input.", err=True)
        raise typer.Exit(1)

    created_count = 0
    first_step_num = None
    for step in steps_to_create:
        try:
            result = client.create_step_with_verification(
                task_id,
                subtask_id,
                step["description"],
                step["verify_command"],
                step["expected_output"],
            )
            created_count += 1
            if first_step_num is None:
                first_step_num = result.get("step_number", "?")
        except APIError as e:
            handle_api_error(e)
            return

    output_success(f"{subtask_id}|+{created_count} from {first_step_num}")


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


@app.command("defect")
def mark_plan_defect(
    subtask_id: str,
    step_number: int,
    fix_step: Annotated[
        int | None,
        typer.Option("--fix", "-f", help="Step number of an already-PASSED fix step"),
    ] = None,
    verify_command: Annotated[
        str | None,
        typer.Option("--verify", "-v", help="Verify command for inline fix step"),
    ] = None,
    expected_output: Annotated[
        str | None,
        typer.Option("--expected", "-e", help="Expected output for inline fix step"),
    ] = None,
    task_id: Annotated[str | None, typer.Option("--task", "-t")] = None,
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
    from ..context import require_task_id

    has_inline = verify_command is not None or expected_output is not None
    has_ref = fix_step is not None

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

    task_id = require_task_id(task_id)
    client = STClient()

    if has_inline:
        assert verify_command is not None
        assert expected_output is not None

        # 1. Create fix step
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
            return
        fix_step_num = result.get("step_number")
        if fix_step_num is None:
            typer.echo("Error: failed to get fix step number from API response.", err=True)
            raise typer.Exit(1)

        # 2. Pass fix step (runs verify_command — quality gate preserved)
        try:
            client.update_step(task_id, subtask_id, fix_step_num, passes=True)
        except APIError as e:
            detail: dict[str, Any] = e.detail if isinstance(e.detail, dict) else {}
            if detail.get("verification_failed"):
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
            handle_api_error(e)
            return

        # 3. Mark original as plan_defect
        try:
            client.update_step_status(
                task_id, subtask_id, step_number, status="plan_defect", fix_step_number=fix_step_num
            )
        except APIError as e:
            handle_api_error(e)
            return

        output_success(f"{subtask_id}.{step_number}|defect→{fix_step_num}")
    else:
        assert fix_step is not None
        try:
            client.update_step_status(
                task_id, subtask_id, step_number, status="plan_defect", fix_step_number=fix_step
            )
        except APIError as e:
            handle_api_error(e)
            return

        output_success(f"{subtask_id}.{step_number}|defect→{fix_step}")


# Error stubs for removed commands - provide helpful redirects
@app.command("list", hidden=True)
def list_removed() -> None:
    """Removed: use st context --subtask instead."""
    typer.echo("Command 'step list' has been removed.\n", err=True)
    typer.echo("Use instead:", err=True)
    typer.echo("  st context <task-id> --subtask X.Y    - Shows subtask with all steps", err=True)
    raise typer.Exit(1)


@app.command("create", hidden=True)
def create_removed() -> None:
    """Removed: use st step new instead."""
    typer.echo("Command 'step create' has been removed.\n", err=True)
    typer.echo("Use instead:", err=True)
    typer.echo("  st step new <subtask> <desc> -v <verify_cmd> -e <expected>", err=True)
    raise typer.Exit(1)


@app.command("insert", hidden=True)
def insert_removed() -> None:
    """Removed: use st step add with --at instead."""
    typer.echo("Command 'step insert' has been removed.\n", err=True)
    typer.echo("Use instead:", err=True)
    typer.echo("  st step add <subtask> <desc> --at N    - Insert at position N", err=True)
    raise typer.Exit(1)
