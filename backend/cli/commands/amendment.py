"""Amendment commands for the CLI.

Commands for managing criterion amendment requests:
- list: List amendments with filters
- approve: Approve a pending amendment
- reject: Reject a pending amendment
"""

from __future__ import annotations

from typing import Annotated

import typer

from ..output import output_error

app = typer.Typer(help="Amendment management commands")


@app.command("list")
def list_amendments(
    task_id: Annotated[str | None, typer.Option("--task", "-t", help="Filter by task ID")] = None,
    status: Annotated[
        str | None,
        typer.Option("--status", "-s", help="Filter by status: pending, approved, rejected"),
    ] = None,
) -> None:
    """List criterion amendments.

    Examples:
        st amendment list                            # All amendments
        st amendment list --task task-abc123         # Filter by task
        st amendment list --status pending           # Filter by status
        st amendment list -t task-abc123 -s pending  # Both filters
    """
    from app.storage.amendments import list_amendments as storage_list
    from app.storage.connection import get_connection

    with get_connection() as conn:
        amendments = storage_list(conn, task_id=task_id, status=status)

    if not amendments:
        print("AMENDMENTS[0]:none")
        return

    # Header
    print(f"AMENDMENTS[{len(amendments)}]")

    # Output each amendment
    for a in amendments:
        amend_id = a["amendment_id"]
        crit_id = a["criterion_id"]
        a_task = a["task_id"]
        a_status = a["status"]
        reason = (a.get("reason") or "")[:50]

        print(f"  {amend_id}|{a_task}|{crit_id}|{a_status}|{reason}")


@app.command("approve")
def approve_amendment(
    amendment_id: Annotated[str, typer.Argument(help="Amendment ID to approve (e.g., amend-0001)")],
    reason: Annotated[
        str | None,
        typer.Option("--reason", "-r", help="Optional reason for approval"),
    ] = None,
    approved_by: Annotated[
        str,
        typer.Option("--by", help="Who is approving (default: human)"),
    ] = "human",
) -> None:
    """Approve a pending amendment.

    On approval, the criterion's verify_command is updated with the new command.

    Examples:
        st amendment approve amend-0001
        st amendment approve amend-0001 --reason "Test fix looks correct"
        st amendment approve amend-0001 --by supervisor
    """
    from app.storage.amendments import approve_amendment as storage_approve
    from app.storage.connection import get_connection

    with get_connection() as conn:
        result = storage_approve(conn, amendment_id, approved_by, reason)

    if "error" in result:
        output_error(result["error"])
        raise typer.Exit(1)

    print(
        f"APPROVED:{result['amendment_id']}|criterion={result['criterion_id']}|"
        f"approved_by={result['approved_by']}"
    )


@app.command("reject")
def reject_amendment(
    amendment_id: Annotated[str, typer.Argument(help="Amendment ID to reject (e.g., amend-0001)")],
    reason: Annotated[
        str,
        typer.Option("--reason", "-r", help="Required reason for rejection"),
    ],
    rejected_by: Annotated[
        str,
        typer.Option("--by", help="Who is rejecting (default: human)"),
    ] = "human",
) -> None:
    """Reject a pending amendment.

    The criterion's verify_command remains unchanged.

    Examples:
        st amendment reject amend-0001 --reason "Original command is correct"
        st amendment reject amend-0001 -r "Fix the implementation instead"
    """
    from app.storage.amendments import reject_amendment as storage_reject
    from app.storage.connection import get_connection

    with get_connection() as conn:
        result = storage_reject(conn, amendment_id, rejected_by, reason)

    if "error" in result:
        output_error(result["error"])
        raise typer.Exit(1)

    print(f"REJECTED:{result['amendment_id']}|criterion={result['criterion_id']}|reason={reason}")


@app.command("show")
def show_amendment(
    amendment_id: Annotated[str, typer.Argument(help="Amendment ID to show (e.g., amend-0001)")],
) -> None:
    """Show details of a specific amendment.

    Examples:
        st amendment show amend-0001
    """
    from app.storage.amendments import get_amendment
    from app.storage.connection import get_connection

    with get_connection() as conn:
        amendment = get_amendment(conn, amendment_id)

    if not amendment:
        output_error(f"Amendment {amendment_id} not found")
        raise typer.Exit(1)

    # Output in structured format
    print(f"AMENDMENT:{amendment['amendment_id']}")
    print(f"  task_id: {amendment['task_id']}")
    print(f"  criterion_id: {amendment['criterion_id']}")
    print(f"  status: {amendment['status']}")
    print(f"  reason: {amendment['reason']}")
    print(f"  old_verify_command: {amendment['old_verify_command']}")
    print(f"  new_verify_command: {amendment['new_verify_command']}")
    print(f"  preflight_status: {amendment['preflight_status']}")
    if amendment.get("approved_by"):
        print(f"  approved_by: {amendment['approved_by']}")
    if amendment.get("approval_reason"):
        print(f"  approval_reason: {amendment['approval_reason']}")
    print(f"  created_at: {amendment['created_at']}")
    if amendment.get("resolved_at"):
        print(f"  resolved_at: {amendment['resolved_at']}")
