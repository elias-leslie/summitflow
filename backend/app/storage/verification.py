"""Storage module for task acceptance criteria.

Provides CRUD operations for task_acceptance_criteria table.
Verification is now handled at application level during st close.
"""

import logging
import subprocess
from datetime import UTC, datetime
from typing import Any

import psycopg
from psycopg import sql

logger = logging.getLogger(__name__)

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
                 expected_output, display_order)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id, task_id, criterion_id, criterion, category, verify_by,
                      verify_command, expected_output, verified, verified_at,
                      verified_by_actual, created_at
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
                   verified_by_actual, created_at
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
                   verified_by_actual, created_at
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
                   verified_by_actual, created_at
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
    """Update a criterion's fields in task_acceptance_criteria."""
    allowed_fields = {
        "criterion",
        "category",
        "verify_command",
        "verify_by",
        "expected_output",
        "verified",
        "verified_at",
        "verified_by_actual",
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
                  verified_by_actual, created_at
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
        "verified_by_actual": row[10],
        "created_at": row[11],
    }


# =============================================================================
# Syntax Validation
# =============================================================================


def validate_bash_syntax(command: str) -> tuple[bool, str | None]:
    """Check if a command has valid bash syntax without executing it.

    Uses `bash -n` to parse the command without running it.

    Args:
        command: The bash command string to validate

    Returns:
        Tuple of (is_valid, error_message).
        - (True, None) if syntax is valid
        - (False, stderr) if syntax is invalid
    """
    try:
        result = subprocess.run(
            ["bash", "-n", "-c", command],
            capture_output=True,
            text=True,
            timeout=5,  # Syntax check should be fast
        )
        if result.returncode != 0:
            return False, result.stderr.strip()
        return True, None
    except subprocess.TimeoutExpired:
        return False, "Syntax check timed out"
    except Exception as e:
        # If bash isn't available, skip syntax check
        logger.warning(f"Could not run bash syntax check: {e}")
        return True, None


# =============================================================================
# Verification Execution (for st close)
# =============================================================================


def run_verify_command(
    verify_command: str,
    timeout: int = VERIFY_COMMAND_TIMEOUT,
) -> tuple[str, int, str]:
    """Execute a verify_command and return classification.

    Returns:
        Tuple of (status, exit_code, output) where status is one of:
        - 'passed': Exit code 0
        - 'failed': Exit code != 0
        - 'crashed': Exit code 126-127 or exception
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
            return ("crashed", exit_code, output)

    except subprocess.TimeoutExpired:
        return ("crashed", -1, f"Command timed out after {timeout}s")
    except Exception as e:
        return ("crashed", -1, str(e))


def get_criteria_with_verify_commands(
    conn: psycopg.Connection, task_id: str
) -> list[dict[str, Any]]:
    """Get criteria that have verify_commands (for verification runs)."""
    criteria = get_criteria_for_task_v2(conn, task_id)
    return [c for c in criteria if c.get("verify_command")]
