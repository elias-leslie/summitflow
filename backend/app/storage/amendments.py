"""Storage module for criterion amendments.

Implements the amendment protocol for modifying locked criteria.
Amendments require preflight validation and supervisor/human approval.
"""

import logging
from datetime import UTC, datetime
from typing import Any

import psycopg

from .verification import run_preflight

logger = logging.getLogger(__name__)


def get_next_amendment_id(conn: psycopg.Connection) -> str:
    """Generate the next amendment_id.

    Format: amend-XXXX (e.g., amend-0001)
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT amendment_id FROM criterion_amendments
            WHERE amendment_id ~ '^amend-[0-9]+$'
            ORDER BY CAST(SUBSTRING(amendment_id FROM 7) AS INTEGER) DESC
            LIMIT 1
            """
        )
        row = cur.fetchone()

        if row is None:
            return "amend-0001"

        current = row[0]
        try:
            num = int(current.split("-")[1])
            return f"amend-{num + 1:04d}"
        except (IndexError, ValueError):
            return "amend-0001"


def create_amendment(
    conn: psycopg.Connection,
    task_id: str,
    criterion_id: str,
    new_verify_command: str,
    reason: str,
    evidence: str | None = None,
) -> dict[str, Any]:
    """Create an amendment request for a locked criterion.

    The new verify_command must fail preflight (TDD-style) to be valid.
    If it passes, the amendment is rejected immediately.

    Args:
        conn: Database connection
        task_id: Task ID
        criterion_id: Criterion ID to amend
        new_verify_command: Proposed new verify_command
        reason: Why the amendment is needed
        evidence: Optional path to artifact (screenshot, log)

    Returns:
        Amendment dict with status (pending or rejected)
    """
    # Get current criterion
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT verify_command, is_locked
            FROM task_acceptance_criteria
            WHERE task_id = %s AND criterion_id = %s
            """,
            (task_id, criterion_id),
        )
        row = cur.fetchone()

    if not row:
        return {"error": f"Criterion {criterion_id} not found for task {task_id}"}

    old_verify_command, is_locked = row

    if not is_locked:
        return {"error": f"Criterion {criterion_id} is not locked. Direct edit allowed."}

    # Run preflight on new command - it must FAIL
    preflight_status, _, preflight_output = run_preflight(new_verify_command)

    if preflight_status == "invalid_pass":
        # New command passes - reject amendment (would bypass verification)
        return {
            "error": "Amendment rejected: new verify_command passes immediately",
            "status": "rejected",
            "reason": "New command must fail preflight (TDD-style). A passing command would bypass verification.",
            "preflight_status": preflight_status,
            "preflight_output": preflight_output,
        }

    if preflight_status == "invalid_crash":
        return {
            "error": "Amendment rejected: new verify_command has syntax errors",
            "status": "rejected",
            "reason": "Command crashed during preflight - check syntax",
            "preflight_status": preflight_status,
            "preflight_output": preflight_output,
        }

    # Preflight passed (valid_fail) - create amendment record
    amendment_id = get_next_amendment_id(conn)

    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO criterion_amendments
                (amendment_id, task_id, criterion_id, old_verify_command,
                 new_verify_command, reason, evidence, status,
                 preflight_status, preflight_output)
            VALUES (%s, %s, %s, %s, %s, %s, %s, 'pending', %s, %s)
            RETURNING id, amendment_id, task_id, criterion_id, status, created_at
            """,
            (
                amendment_id,
                task_id,
                criterion_id,
                old_verify_command,
                new_verify_command,
                reason,
                evidence,
                preflight_status,
                preflight_output[:10000] if preflight_output else None,
            ),
        )
        row = cur.fetchone()
        conn.commit()

    assert row is not None, "INSERT with RETURNING should always return a row"
    return {
        "id": row[0],
        "amendment_id": row[1],
        "task_id": row[2],
        "criterion_id": row[3],
        "status": row[4],
        "created_at": row[5],
        "preflight_status": preflight_status,
    }


def approve_amendment(
    conn: psycopg.Connection,
    amendment_id: str,
    approved_by: str,
    approval_reason: str | None = None,
) -> dict[str, Any]:
    """Approve an amendment and update the criterion's verify_command.

    Args:
        conn: Database connection
        amendment_id: Amendment ID to approve
        approved_by: Who approved ('supervisor' or user ID)
        approval_reason: Optional reason for approval

    Returns:
        Updated amendment dict
    """
    with conn.cursor() as cur:
        # Get amendment details
        cur.execute(
            """
            SELECT id, task_id, criterion_id, new_verify_command, status
            FROM criterion_amendments
            WHERE amendment_id = %s
            """,
            (amendment_id,),
        )
        row = cur.fetchone()

    if not row:
        return {"error": f"Amendment {amendment_id} not found"}

    _db_id, task_id, criterion_id, new_verify_command, status = row

    if status != "pending":
        return {"error": f"Amendment {amendment_id} is not pending (status: {status})"}

    now = datetime.now(UTC)

    # Update amendment status and criterion verify_command
    with conn.cursor() as cur:
        # Set session variable to bypass lock check (transaction-scoped via SET LOCAL)
        cur.execute("SET LOCAL app.amendment_approval = 'true'")

        cur.execute(
            """
            UPDATE criterion_amendments
            SET status = 'approved', approved_by = %s, approval_reason = %s,
                resolved_at = %s, updated_at = %s
            WHERE amendment_id = %s
            """,
            (approved_by, approval_reason, now, now, amendment_id),
        )

        # Update criterion verify_command (lock bypassed via session variable)
        cur.execute(
            """
            UPDATE task_acceptance_criteria
            SET verify_command = %s, updated_at = %s,
                preflight_status = 'pending', preflight_output = NULL, preflight_at = NULL
            WHERE task_id = %s AND criterion_id = %s
            """,
            (new_verify_command, now, task_id, criterion_id),
        )
        conn.commit()
        # Session variable automatically cleared when transaction ends

    return {
        "amendment_id": amendment_id,
        "status": "approved",
        "approved_by": approved_by,
        "criterion_id": criterion_id,
        "new_verify_command": new_verify_command,
    }


def reject_amendment(
    conn: psycopg.Connection,
    amendment_id: str,
    rejected_by: str,
    rejection_reason: str,
) -> dict[str, Any]:
    """Reject an amendment.

    Args:
        conn: Database connection
        amendment_id: Amendment ID to reject
        rejected_by: Who rejected
        rejection_reason: Why it was rejected

    Returns:
        Updated amendment dict
    """
    now = datetime.now(UTC)

    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE criterion_amendments
            SET status = 'rejected', approved_by = %s, approval_reason = %s,
                resolved_at = %s, updated_at = %s
            WHERE amendment_id = %s AND status = 'pending'
            RETURNING amendment_id, status, criterion_id
            """,
            (rejected_by, rejection_reason, now, now, amendment_id),
        )
        row = cur.fetchone()
        conn.commit()

    if not row:
        return {"error": f"Amendment {amendment_id} not found or not pending"}

    return {
        "amendment_id": row[0],
        "status": row[1],
        "criterion_id": row[2],
        "rejected_by": rejected_by,
        "reason": rejection_reason,
    }


def get_amendment(conn: psycopg.Connection, amendment_id: str) -> dict[str, Any] | None:
    """Get an amendment by ID."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, amendment_id, task_id, criterion_id, old_verify_command,
                   new_verify_command, reason, evidence, status, approved_by,
                   approval_reason, preflight_status, preflight_output,
                   created_at, resolved_at
            FROM criterion_amendments
            WHERE amendment_id = %s
            """,
            (amendment_id,),
        )
        row = cur.fetchone()

    if not row:
        return None

    return {
        "id": row[0],
        "amendment_id": row[1],
        "task_id": row[2],
        "criterion_id": row[3],
        "old_verify_command": row[4],
        "new_verify_command": row[5],
        "reason": row[6],
        "evidence": row[7],
        "status": row[8],
        "approved_by": row[9],
        "approval_reason": row[10],
        "preflight_status": row[11],
        "preflight_output": row[12],
        "created_at": row[13],
        "resolved_at": row[14],
    }


def list_amendments(
    conn: psycopg.Connection,
    task_id: str | None = None,
    status: str | None = None,
) -> list[dict[str, Any]]:
    """List amendments with optional filters."""
    query = """
        SELECT id, amendment_id, task_id, criterion_id, status,
               reason, approved_by, created_at, resolved_at
        FROM criterion_amendments
        WHERE 1=1
    """
    params: list[Any] = []

    if task_id:
        query += " AND task_id = %s"
        params.append(task_id)

    if status:
        query += " AND status = %s"
        params.append(status)

    query += " ORDER BY created_at DESC"

    with conn.cursor() as cur:
        cur.execute(query, params)
        rows = cur.fetchall()

    return [
        {
            "id": row[0],
            "amendment_id": row[1],
            "task_id": row[2],
            "criterion_id": row[3],
            "status": row[4],
            "reason": row[5],
            "approved_by": row[6],
            "created_at": row[7],
            "resolved_at": row[8],
        }
        for row in rows
    ]
