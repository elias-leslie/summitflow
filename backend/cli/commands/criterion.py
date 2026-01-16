"""Criterion commands for the CLI."""

from __future__ import annotations

from typing import Annotated

import typer

from ..client import APIError, STClient
from ..output import handle_api_error, output_error, output_json

app = typer.Typer(help="Criterion management commands")


@app.command("list")
def list_criteria(
    task_id: Annotated[str, typer.Option("--task", "-t", help="Task ID")],
) -> None:
    """List criteria for a task.

    Examples:
        st criterion list --task task-abc123
        st criterion list -t task-abc123
    """
    client = STClient()

    try:
        criteria = client.list_task_criteria(task_id)
    except APIError as e:
        handle_api_error(e)
        return

    output_json(criteria)


@app.command("create")
def create_criterion(
    criterion: Annotated[str, typer.Argument(help="Criterion text (min 10 chars)")],
    task_id: Annotated[str | None, typer.Option("--task", "-t", help="Task ID to link")] = None,
    category: Annotated[
        str, typer.Option("--category", help="correctness, performance, security, quality")
    ] = "correctness",
    verify_command: Annotated[
        str | None, typer.Option("--verify-command", "-v", help="Bash command to verify")
    ] = None,
    verify_by: Annotated[
        str, typer.Option("--verify-by", help="Verification method: test, agent, human, opus")
    ] = "test",
    expected_output: Annotated[
        str | None, typer.Option("--expected-output", "-e", help="Expected output for verification")
    ] = None,
) -> None:
    """Create a criterion and link to a task.

    Examples:
        st criterion create "All pytest tests pass" --task task-abc123 --verify-by test
        st criterion create "UI renders correctly" -t task-abc123 --verify-by agent -v "ba check http://localhost:3001 --no-errors"
    """
    if not task_id:
        output_error("--task is required")
        raise typer.Exit(1)

    client = STClient()

    criterion_data = {
        "criterion": criterion,
        "category": category,
        "verify_by": verify_by,
    }
    if verify_command:
        criterion_data["verify_command"] = verify_command
    if expected_output:
        criterion_data["expected_output"] = expected_output

    try:
        result = client.batch_create_task_criteria(task_id, [criterion_data])
    except APIError as e:
        handle_api_error(e)
        return

    # Return the created criterion (first item from batch)
    if result.get("created"):
        output_json(result["created"][0])
    else:
        output_error(f"Failed to create criterion: {result.get('errors', 'Unknown error')}")
        raise typer.Exit(1)


@app.command("update")
def update_criterion(
    criterion_id: str,
    criterion: Annotated[str | None, typer.Option("--criterion", help="New criterion text")] = None,
    category: Annotated[str | None, typer.Option("--category", help="New category")] = None,
    measurement: Annotated[
        str | None, typer.Option("--measurement", "-m", help="New measurement type")
    ] = None,
    threshold: Annotated[
        str | None, typer.Option("--threshold", "-t", help="New threshold value")
    ] = None,
    verify_command: Annotated[
        str | None, typer.Option("--verify-command", "-v", help="Bash command to verify")
    ] = None,
    verify_by: Annotated[
        str | None,
        typer.Option("--verify-by", help="Verification method: test, agent, human, opus"),
    ] = None,
    expected_output: Annotated[
        str | None, typer.Option("--expected-output", "-e", help="Expected output for verification")
    ] = None,
) -> None:
    """Update a criterion.

    Examples:
        st criterion update ac-001 --criterion "Updated criterion text"
        st criterion update ac-001 --category performance --threshold "<100ms"
        st criterion update ac-001 --verify-command "ba check http://localhost:3001 --no-errors"
        st criterion update ac-001 --verify-by agent --expected-output "Screenshot shows 5 columns"
    """
    client = STClient()

    # Build update dict
    updates: dict = {}
    if criterion is not None:
        updates["criterion"] = criterion
    if category is not None:
        updates["category"] = category
    if measurement is not None:
        updates["measurement"] = measurement
    if threshold is not None:
        updates["threshold"] = threshold
    if verify_command is not None:
        updates["verify_command"] = verify_command
    if verify_by is not None:
        updates["verify_by"] = verify_by
    if expected_output is not None:
        updates["expected_output"] = expected_output

    if not updates:
        output_error("No updates specified")
        raise typer.Exit(1)

    try:
        result = client.update_criterion(criterion_id, **updates)
    except APIError as e:
        handle_api_error(e)
        return

    output_json(result)


@app.command("verify")
def verify_criterion(
    task_id: str,
    criterion_id: str,
    verified_by: Annotated[str, typer.Option("--by")] = "test",
) -> None:
    """Verify a criterion for a task.

    Examples:
        st criterion verify task-abc123 ac-001
        st criterion verify task-abc123 ac-001 --by manual
    """
    client = STClient()

    try:
        result = client.verify_criterion(
            task_id=task_id,
            criterion_id=criterion_id,
            verified=True,
            verified_by=verified_by,
        )
    except APIError as e:
        handle_api_error(e)
        return

    output_json(result)


@app.command("preflight")
def preflight_criteria(
    task_id: Annotated[str, typer.Argument(help="Task ID")],
    criterion_id: Annotated[
        str | None, typer.Argument(help="Optional specific criterion ID")
    ] = None,
) -> None:
    """Run TDD-style preflight validation on verify_commands.

    Preflight checks that verify_commands FAIL before work begins (TDD-style).
    Valid results: valid_fail (good), invalid_pass (bad), invalid_crash (bad)

    Examples:
        st criterion preflight task-abc123           # All criteria
        st criterion preflight task-abc123 ac-001    # Single criterion
    """
    from app.storage.connection import get_connection
    from app.storage.verification import (
        get_criteria_for_task_v2,
        run_preflight_for_criterion,
    )

    with get_connection() as conn:
        if criterion_id:
            # Single criterion
            result = run_preflight_for_criterion(conn, task_id, criterion_id)
            if "error" in result:
                output_error(result["error"])
                raise typer.Exit(1)
            # Detailed output for single criterion
            status = result["status"]
            output = result.get("output", "")[:500]  # Truncate for display
            print(f"PREFLIGHT:{criterion_id}:{status}")
            if output:
                print(f"OUTPUT:{output}")
        else:
            # All criteria
            criteria = get_criteria_for_task_v2(conn, task_id)
            if not criteria:
                output_error(f"No criteria found for task {task_id}")
                raise typer.Exit(1)

            valid = 0
            invalid_pass = 0
            invalid_crash = 0
            pending = 0

            for c in criteria:
                if not c.get("verify_command"):
                    pending += 1
                    continue

                result = run_preflight_for_criterion(conn, task_id, c["criterion_id"])
                status = result.get("status", "error")

                if status == "valid_fail":
                    valid += 1
                elif status == "invalid_pass":
                    invalid_pass += 1
                elif status == "invalid_crash":
                    invalid_crash += 1
                else:
                    pending += 1

            total = len(criteria)
            print(
                f"PREFLIGHT[{total}]:valid={valid}|invalid_pass={invalid_pass}|invalid_crash={invalid_crash}|pending={pending}"
            )

            # Exit with error if any invalid
            if invalid_pass > 0 or invalid_crash > 0:
                raise typer.Exit(1)


@app.command("amend")
def amend_criterion(
    task_id: Annotated[str, typer.Argument(help="Task ID")],
    criterion_id: Annotated[str, typer.Argument(help="Criterion ID to amend")],
    new_command: Annotated[str, typer.Option("--new-command", "-c", help="New verify_command")],
    reason: Annotated[str, typer.Option("--reason", "-r", help="Reason for amendment")],
    evidence: Annotated[
        str | None, typer.Option("--evidence", "-e", help="Path to evidence artifact")
    ] = None,
) -> None:
    """Request an amendment to a locked criterion's verify_command.

    The new command must fail preflight (TDD-style) to be valid.
    Amendment requires supervisor/human approval.

    Examples:
        st criterion amend task-abc123 ac-001 --new-command "grep -q 'foo' file.py" --reason "Original command path wrong"
    """
    from app.storage.amendments import create_amendment
    from app.storage.connection import get_connection

    with get_connection() as conn:
        result = create_amendment(
            conn,
            task_id,
            criterion_id,
            new_command,
            reason,
            evidence,
        )

    if "error" in result:
        output_error(result["error"])
        if result.get("status") == "rejected":
            print(f"AMENDMENT:rejected|reason={result.get('reason', 'unknown')}")
        raise typer.Exit(1)

    print(f"AMENDMENT:pending|id={result['amendment_id']}|criterion={result['criterion_id']}")


@app.command("override")
def override_criterion(
    task_id: Annotated[str, typer.Argument(help="Task ID")],
    criterion_id: Annotated[str, typer.Argument(help="Criterion ID to override")],
    action: Annotated[str, typer.Option("--action", "-a", help="pass or reset")],
    reason: Annotated[str, typer.Option("--reason", "-r", help="Reason for override")],
) -> None:
    """Human override for a criterion at HUMAN escalation level.

    Actions:
        pass: Force-pass the criterion (marks as verified by human)
        reset: Reset to WORKER level for another attempt

    Examples:
        st criterion override task-abc123 ac-001 --action pass --reason "Verified manually"
        st criterion override task-abc123 ac-001 --action reset --reason "Fixed the test"
    """
    from app.storage.connection import get_connection
    from app.storage.verification import human_override_criterion

    with get_connection() as conn:
        result = human_override_criterion(conn, task_id, criterion_id, action, reason)

    if "error" in result:
        output_error(result["error"])
        raise typer.Exit(1)

    print(
        f"OVERRIDE:{result['status']}|criterion={result['criterion_id']}|action={result['action']}"
    )
