"""Storage module for verification enforcement.

Implements TDD-style verification using task_acceptance_criteria table.
This module provides the new verification-based criterion operations.
"""

import logging
import subprocess
from datetime import UTC, datetime
from typing import Any

import psycopg
from psycopg import sql

logger = logging.getLogger(__name__)

# Escalation limits (3-2-1 pattern)
MAX_WORKER_ATTEMPTS = 3
MAX_SUPERVISOR_ATTEMPTS = 2
MAX_HUMAN_ATTEMPTS = 1

# Timeout for verify_command execution (30 seconds)
VERIFY_COMMAND_TIMEOUT = 30


# =============================================================================
# Criterion ID Generation (for task_acceptance_criteria)
# =============================================================================


def get_next_task_criterion_id(conn: psycopg.Connection, task_id: str) -> str:
    """Generate the next criterion_id for a task.

    Format: ac-NNN (e.g., ac-001, ac-012, ac-123)
    Scoped to task, not project.
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT criterion_id FROM task_acceptance_criteria
            WHERE task_id = %s AND criterion_id ~ '^ac-[0-9]+$'
            ORDER BY CAST(SUBSTRING(criterion_id FROM 4) AS INTEGER) DESC
            LIMIT 1
            """,
            (task_id,),
        )
        row = cur.fetchone()

        if row is None:
            return "ac-001"

        current = row[0]
        try:
            num = int(current.split("-")[1])
            return f"ac-{num + 1:03d}"
        except (IndexError, ValueError):
            logger.warning(f"Invalid criterion_id format: {current}, starting from ac-001")
            return "ac-001"


# =============================================================================
# CRUD Operations for task_acceptance_criteria
# =============================================================================


def create_task_criterion(
    conn: psycopg.Connection,
    task_id: str,
    criterion: str,
    category: str = "correctness",
    verify_by: str = "test",
    verify_command: str | None = None,
    expected_output: str | None = None,
    criterion_id: str | None = None,
) -> dict[str, Any]:
    """Create a new acceptance criterion in task_acceptance_criteria.

    Args:
        conn: Database connection
        task_id: Task ID this criterion belongs to
        criterion: The criterion text (what to verify)
        category: Category (correctness, performance, security, quality)
        verify_by: How to verify (test, agent, human, opus)
        verify_command: Bash command to verify the criterion
        expected_output: Expected output from verify_command
        criterion_id: Optional explicit criterion_id (auto-generated if not provided)
    """
    if criterion_id is None:
        criterion_id = get_next_task_criterion_id(conn, task_id)

    # Get next display_order
    with conn.cursor() as cur:
        cur.execute(
            "SELECT COALESCE(MAX(display_order), 0) + 1 FROM task_acceptance_criteria WHERE task_id = %s",
            (task_id,),
        )
        row = cur.fetchone()
        display_order = row[0] if row else 1

        cur.execute(
            """
            INSERT INTO task_acceptance_criteria
                (task_id, criterion_id, criterion, category, verify_by, verify_command,
                 expected_output, display_order, preflight_status, is_locked,
                 verification_status, verification_attempts, escalation_level)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'pending', FALSE, 'pending', 0, 'WORKER')
            RETURNING id, task_id, criterion_id, criterion, category, verify_by,
                      verify_command, expected_output, verified, verified_at,
                      preflight_status, is_locked, verification_status,
                      verification_attempts, escalation_level, created_at
            """,
            (
                task_id,
                criterion_id,
                criterion,
                category,
                verify_by,
                verify_command,
                expected_output,
                display_order,
            ),
        )
        row = cur.fetchone()
        conn.commit()

    assert row is not None, "INSERT with RETURNING should always return a row"
    return _row_to_criterion_dict(row)


def get_task_criterion(
    conn: psycopg.Connection, task_id: str, criterion_id: str
) -> dict[str, Any] | None:
    """Get a criterion by task_id + criterion_id."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, task_id, criterion_id, criterion, category, verify_by,
                   verify_command, expected_output, verified, verified_at,
                   preflight_status, is_locked, verification_status,
                   verification_attempts, escalation_level, created_at
            FROM task_acceptance_criteria
            WHERE task_id = %s AND criterion_id = %s
            """,
            (task_id, criterion_id),
        )
        row = cur.fetchone()

    return _row_to_criterion_dict(row) if row else None


def get_task_criterion_by_id(conn: psycopg.Connection, db_id: int) -> dict[str, Any] | None:
    """Get a criterion by internal database ID."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, task_id, criterion_id, criterion, category, verify_by,
                   verify_command, expected_output, verified, verified_at,
                   preflight_status, is_locked, verification_status,
                   verification_attempts, escalation_level, created_at
            FROM task_acceptance_criteria
            WHERE id = %s
            """,
            (db_id,),
        )
        row = cur.fetchone()

    return _row_to_criterion_dict(row) if row else None


def get_criteria_for_task_v2(conn: psycopg.Connection, task_id: str) -> list[dict[str, Any]]:
    """Get all criteria for a task from task_acceptance_criteria.

    Ordered by display_order for consistent presentation.
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, task_id, criterion_id, criterion, category, verify_by,
                   verify_command, expected_output, verified, verified_at,
                   preflight_status, is_locked, verification_status,
                   verification_attempts, escalation_level, created_at
            FROM task_acceptance_criteria
            WHERE task_id = %s
            ORDER BY display_order, criterion_id
            """,
            (task_id,),
        )
        rows = cur.fetchall()

    return [_row_to_criterion_dict(row) for row in rows]


def update_task_criterion(
    conn: psycopg.Connection,
    task_id: str,
    criterion_id: str,
    updates: dict[str, Any],
) -> dict[str, Any] | None:
    """Update a criterion's fields in task_acceptance_criteria.

    Note: verify_command cannot be updated if is_locked=True (enforced by trigger).
    """
    allowed_fields = {
        "criterion",
        "category",
        "verify_command",
        "verify_by",
        "expected_output",
        "verified",
        "verified_at",
        "verified_by_actual",
        "preflight_status",
        "preflight_output",
        "preflight_at",
        "verification_status",
        "verification_output",
        "verification_at",
        "verification_attempts",
        "escalation_level",
    }
    filtered = {k: v for k, v in updates.items() if k in allowed_fields}

    if not filtered:
        return get_task_criterion(conn, task_id, criterion_id)

    # Add updated_at
    filtered["updated_at"] = datetime.now(UTC)

    set_clauses = sql.SQL(", ").join(
        sql.SQL("{} = %s").format(sql.Identifier(field)) for field in filtered
    )
    values = list(filtered.values())
    values.extend([task_id, criterion_id])

    query = sql.SQL("""
        UPDATE task_acceptance_criteria
        SET {}
        WHERE task_id = %s AND criterion_id = %s
        RETURNING id, task_id, criterion_id, criterion, category, verify_by,
                  verify_command, expected_output, verified, verified_at,
                  preflight_status, is_locked, verification_status,
                  verification_attempts, escalation_level, created_at
    """).format(set_clauses)

    with conn.cursor() as cur:
        cur.execute(query, values)
        row = cur.fetchone()
        conn.commit()

    return _row_to_criterion_dict(row) if row else None


def _row_to_criterion_dict(row: tuple[Any, ...]) -> dict[str, Any]:
    """Convert a database row to a criterion dict."""
    return {
        "id": row[0],
        "task_id": row[1],
        "criterion_id": row[2],
        "criterion": row[3],
        "category": row[4],
        "verify_by": row[5],
        "verify_command": row[6],
        "expected_output": row[7],
        "verified": row[8],
        "verified_at": row[9],
        "preflight_status": row[10],
        "is_locked": row[11],
        "verification_status": row[12],
        "verification_attempts": row[13],
        "escalation_level": row[14],
        "created_at": row[15],
    }


# =============================================================================
# Verification Execution
# =============================================================================


def run_verify_command(
    verify_command: str,
    timeout: int = VERIFY_COMMAND_TIMEOUT,
) -> tuple[str, int, str]:
    """Execute a verify_command and return classification.

    Returns:
        Tuple of (status, exit_code, output) where status is one of:
        - 'valid_fail': Exit code 1-125, command failed as expected (TDD red)
        - 'invalid_pass': Exit code 0, command passed unexpectedly (bad for preflight)
        - 'invalid_crash': Exit code 126-127 or exception, command has errors
        - 'passed': Exit code 0 during verification (good)
        - 'failed': Exit code != 0 during verification (needs work)
    """
    try:
        result = subprocess.run(
            verify_command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd="/home/kasadis/summitflow",
        )

        exit_code = result.returncode
        output = result.stdout + result.stderr

        # Classify based on exit code
        if exit_code == 0:
            return ("passed", 0, output)
        elif 1 <= exit_code <= 125:
            return ("failed", exit_code, output)
        else:  # 126-127 = command not found or not executable
            return ("invalid_crash", exit_code, output)

    except subprocess.TimeoutExpired:
        return ("invalid_crash", -1, f"Command timed out after {timeout}s")
    except Exception as e:
        return ("invalid_crash", -1, str(e))


def run_preflight(
    verify_command: str,
    timeout: int = VERIFY_COMMAND_TIMEOUT,
) -> tuple[str, int, str]:
    """Run preflight validation on a verify_command.

    For TDD-style validation, the command MUST FAIL (exit != 0) before work begins.

    Returns:
        Tuple of (status, exit_code, output) where status is one of:
        - 'valid_fail': Exit code 1-125, good for TDD (test correctly fails)
        - 'invalid_pass': Exit code 0, bad for TDD (test already passes)
        - 'invalid_crash': Exit code 126-127 or exception, command has syntax errors
    """
    try:
        result = subprocess.run(
            verify_command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd="/home/kasadis/summitflow",
        )

        exit_code = result.returncode
        output = result.stdout + result.stderr

        if exit_code == 0:
            return ("invalid_pass", 0, output)
        elif 1 <= exit_code <= 125:
            return ("valid_fail", exit_code, output)
        else:  # 126-127
            return ("invalid_crash", exit_code, output)

    except subprocess.TimeoutExpired:
        return ("invalid_crash", -1, f"Command timed out after {timeout}s")
    except Exception as e:
        return ("invalid_crash", -1, str(e))


def run_preflight_for_criterion(
    conn: psycopg.Connection,
    task_id: str,
    criterion_id: str,
) -> dict[str, Any]:
    """Run preflight validation for a criterion and update database.

    Args:
        conn: Database connection
        task_id: Task ID
        criterion_id: Criterion ID (e.g., 'ac-001')

    Returns:
        Dict with preflight result including status and output.
    """
    criterion = get_task_criterion(conn, task_id, criterion_id)
    if not criterion:
        return {"error": f"Criterion {criterion_id} not found for task {task_id}"}

    verify_command = criterion.get("verify_command")
    if not verify_command:
        # No verify_command means manual verification - skip preflight
        return {"status": "skipped", "reason": "No verify_command defined"}

    # Run preflight
    status, exit_code, output = run_preflight(verify_command)

    # Update criterion with preflight result
    now = datetime.now(UTC)
    update_task_criterion(
        conn,
        task_id,
        criterion_id,
        {
            "preflight_status": status,
            "preflight_output": output[:10000],  # Truncate if needed
            "preflight_at": now,
        },
    )

    return {
        "status": status,
        "criterion_id": criterion_id,
        "exit_code": exit_code,
        "output": output,
        "valid": status == "valid_fail",
    }


# =============================================================================
# System-Mediated Verification
# =============================================================================


def run_verification(
    conn: psycopg.Connection,
    task_id: str,
    criterion_id: str,
) -> dict[str, Any]:
    """Run verification for a criterion and update its status.

    This is the core verification function called by st step/subtask pass.
    Agent cannot mark criterion verified directly - only this function can.

    Returns:
        Dict with verification result including status, output, and escalation info.
    """
    criterion = get_task_criterion(conn, task_id, criterion_id)
    if not criterion:
        return {"error": f"Criterion {criterion_id} not found for task {task_id}"}

    # Check if locked (required before verification)
    if not criterion["is_locked"]:
        return {"error": f"Criterion {criterion_id} is not locked. Task must be running."}

    verify_command = criterion.get("verify_command")
    if not verify_command:
        return {"error": f"Criterion {criterion_id} has no verify_command"}

    # Check escalation level
    escalation = criterion["escalation_level"]
    attempts = criterion["verification_attempts"]

    if escalation == "HUMAN":
        return {
            "error": f"Criterion {criterion_id} requires human override. Use st criterion override.",
            "escalation_level": "HUMAN",
        }

    # Run the verification
    status, exit_code, output = run_verify_command(verify_command)

    # Update criterion with result
    now = datetime.now(UTC)
    new_attempts = attempts + 1

    if status == "passed":
        # Verification passed - update and return success
        update_task_criterion(
            conn,
            task_id,
            criterion_id,
            {
                "verification_status": "passed",
                "verification_output": output[:10000],  # Truncate if needed
                "verification_at": now,
                "verification_attempts": new_attempts,
                "verified": True,
                "verified_at": now,
            },
        )
        return {
            "status": "passed",
            "criterion_id": criterion_id,
            "output": output,
            "attempts": new_attempts,
        }
    else:
        # Verification failed - increment attempts and check escalation
        updates = {
            "verification_status": "failed",
            "verification_output": output[:10000],
            "verification_at": now,
            "verification_attempts": new_attempts,
        }

        # Check if we need to escalate
        new_escalation = check_and_escalate(escalation, new_attempts)
        if new_escalation != escalation:
            updates["escalation_level"] = new_escalation
            updates["verification_attempts"] = 0  # Reset for new escalation level

        update_task_criterion(conn, task_id, criterion_id, updates)

        return {
            "status": "failed",
            "criterion_id": criterion_id,
            "output": output,
            "exit_code": exit_code,
            "attempts": new_attempts,
            "escalation_level": new_escalation,
            "escalated": new_escalation != escalation,
        }


def check_and_escalate(current_level: str, attempts: int) -> str:
    """Determine if escalation is needed based on attempts.

    3-2-1 pattern:
    - WORKER: 3 attempts max, then escalate to SUPERVISOR
    - SUPERVISOR: 2 attempts max, then escalate to HUMAN
    - HUMAN: 1 attempt (human must override)
    """
    if current_level == "WORKER" and attempts >= MAX_WORKER_ATTEMPTS:
        return "SUPERVISOR"
    elif current_level == "SUPERVISOR" and attempts >= MAX_SUPERVISOR_ATTEMPTS:
        return "HUMAN"
    return current_level


# =============================================================================
# Task Status Computation
# =============================================================================


def compute_task_status_from_criteria(conn: psycopg.Connection, task_id: str) -> str | None:
    """Compute what task status should be based on criteria escalation levels.

    Returns:
        - 'human_reviewing' if any criterion is at HUMAN level
        - 'ai_reviewing' if any criterion is at SUPERVISOR level
        - None if all criteria are at WORKER level (keep current status)
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT escalation_level, COUNT(*)
            FROM task_acceptance_criteria
            WHERE task_id = %s
            GROUP BY escalation_level
            """,
            (task_id,),
        )
        rows = cur.fetchall()

    levels = {row[0]: row[1] for row in rows}

    if levels.get("HUMAN", 0) > 0:
        return "human_reviewing"
    elif levels.get("SUPERVISOR", 0) > 0:
        return "ai_reviewing"
    return None


def get_criteria_with_verify_commands(
    conn: psycopg.Connection, task_id: str
) -> list[dict[str, Any]]:
    """Get criteria that have verify_commands (for verification runs)."""
    criteria = get_criteria_for_task_v2(conn, task_id)
    return [c for c in criteria if c.get("verify_command")]


# =============================================================================
# Human Override Functions
# =============================================================================


def human_override_criterion(
    conn: psycopg.Connection,
    task_id: str,
    criterion_id: str,
    action: str,
    reason: str,
) -> dict[str, Any]:
    """Human override for a criterion at HUMAN escalation level.

    Args:
        conn: Database connection
        task_id: Task ID
        criterion_id: Criterion ID
        action: 'pass' to force-pass, 'reset' to reset to WORKER level
        reason: Required reason for the override

    Returns:
        Dict with result of the override action.
    """
    criterion = get_task_criterion(conn, task_id, criterion_id)
    if not criterion:
        return {"error": f"Criterion {criterion_id} not found for task {task_id}"}

    if criterion["escalation_level"] != "HUMAN":
        return {
            "error": f"Criterion {criterion_id} is at {criterion['escalation_level']} level, not HUMAN. "
            "Human override only allowed at HUMAN level."
        }

    now = datetime.now(UTC)

    if action == "pass":
        # Force-pass the criterion
        update_task_criterion(
            conn,
            task_id,
            criterion_id,
            {
                "verification_status": "passed",
                "verification_output": f"Human override: {reason}",
                "verification_at": now,
                "verified": True,
                "verified_at": now,
                "verified_by_actual": "human",
            },
        )
        return {
            "status": "passed",
            "criterion_id": criterion_id,
            "action": "force-pass",
            "reason": reason,
        }

    elif action == "reset":
        # Reset to WORKER level for another attempt
        update_task_criterion(
            conn,
            task_id,
            criterion_id,
            {
                "escalation_level": "WORKER",
                "verification_attempts": 0,
                "verification_status": "pending",
                "verification_output": f"Human reset: {reason}",
            },
        )
        return {
            "status": "reset",
            "criterion_id": criterion_id,
            "action": "reset-to-worker",
            "reason": reason,
        }

    else:
        return {"error": f"Invalid action '{action}'. Use 'pass' or 'reset'."}
