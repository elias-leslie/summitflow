"""Basic CRUD operations for steps."""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Sequence
from typing import Any

from psycopg.rows import TupleRow

from .connection import get_connection

logger = logging.getLogger(__name__)

_ABSOLUTE_CD_PATTERN = re.compile(r"\bcd\s+/[^\s;|&]+")
_ABSOLUTE_PATH_PREFIX = re.compile(r"(?:^|\s)/(?:home|root|tmp|var|opt|usr)/\S+")


def _sanitize_verify_command(cmd: str | None) -> str | None:
    """Nullify verify_commands containing absolute paths that break worktree isolation."""
    if not cmd:
        return cmd
    if _ABSOLUTE_CD_PATTERN.search(cmd) or _ABSOLUTE_PATH_PREFIX.search(cmd):
        logger.warning("Rejected verify_command with absolute path: %s", cmd[:80])
        return None
    return cmd

# Column list for all step SELECT/RETURNING queries (12 columns)
STEP_COLUMNS = """id, subtask_id, step_number, description, spec, passes, passed_at, created_at, verify_command, expected_output, status, fix_step_number"""

# Expected column count for row validation
EXPECTED_STEP_COLUMNS = 12


def _row_to_dict(row: TupleRow | tuple[Any, ...] | None) -> dict[str, Any]:
    """Convert a database row to a step dict.

    Column order (12 columns):
        id, subtask_id, step_number, description, spec, passes, passed_at, created_at,
        verify_command, expected_output, status, fix_step_number
    """
    if row is None:
        raise ValueError("Row cannot be None")
    if len(row) != EXPECTED_STEP_COLUMNS:
        raise ValueError(f"Expected {EXPECTED_STEP_COLUMNS} columns, got {len(row)}")

    # Import here to avoid circular dependency
    from .steps_constants import STEP_STATUS_PENDING

    return {
        "id": row[0],
        "subtask_id": row[1],
        "step_number": row[2],
        "description": row[3],
        "spec": row[4],
        "passes": row[5],
        "passed_at": row[6].isoformat() if row[6] else None,
        "created_at": row[7].isoformat() if row[7] else None,
        "verify_command": row[8],
        "expected_output": row[9],
        "status": row[10] or STEP_STATUS_PENDING,
        "fix_step_number": row[11],
    }


def create_step(
    subtask_id: str,
    step_number: int,
    description: str,
    spec: dict[str, Any] | None = None,
    verify_command: str | None = None,
    expected_output: str | None = None,
) -> dict[str, Any]:
    """Create a new step for a subtask.

    Args:
        subtask_id: Parent subtask ID (e.g., "task-abc123-1.1")
        step_number: 1-indexed step number within subtask
        description: Step description text
        spec: Optional JSONB spec for implementation details
        verify_command: Bash command to verify step completion
        expected_output: Expected output pattern for verification

    Returns:
        The created step dict.

    Raises:
        Exception: If subtask_id doesn't exist (FK constraint violation)
    """

    verify_command = _sanitize_verify_command(verify_command)
    spec_json = json.dumps(spec) if spec else None

    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            f"""
            INSERT INTO task_subtask_steps (subtask_id, step_number, description, spec, verify_command, expected_output)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (subtask_id, step_number) DO UPDATE SET
                description = EXCLUDED.description,
                spec = EXCLUDED.spec,
                verify_command = EXCLUDED.verify_command,
                expected_output = EXCLUDED.expected_output
            RETURNING {STEP_COLUMNS}
            """,
            (subtask_id, step_number, description, spec_json, verify_command, expected_output),
        )
        row = cur.fetchone()
        conn.commit()

    logger.debug("Created step %d for subtask %s", step_number, subtask_id)
    return _row_to_dict(row)


def get_steps_for_subtask(subtask_id: str) -> list[dict[str, Any]]:
    """Get all steps for a subtask, ordered by step_number.

    Args:
        subtask_id: Parent subtask ID

    Returns:
        List of step dicts, ordered by step_number.
    """
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT {STEP_COLUMNS}
            FROM task_subtask_steps
            WHERE subtask_id = %s
            ORDER BY step_number
            """,
            (subtask_id,),
        )
        rows = cur.fetchall()

    return [_row_to_dict(row) for row in rows]


def get_step(subtask_id: str, step_number: int) -> dict[str, Any] | None:
    """Get a single step by subtask_id and step_number.

    Args:
        subtask_id: Parent subtask ID
        step_number: Step number (1-indexed)

    Returns:
        Step dict or None if not found.
    """
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT {STEP_COLUMNS}
            FROM task_subtask_steps
            WHERE subtask_id = %s AND step_number = %s
            """,
            (subtask_id, step_number),
        )
        row = cur.fetchone()

    if not row:
        return None

    return _row_to_dict(row)


def bulk_create_steps(
    subtask_id: str,
    steps: Sequence[str | dict[str, Any]],
) -> list[dict[str, Any]]:
    """Create multiple steps for a subtask in a single transaction.

    Steps are automatically numbered starting from 1.

    Args:
        subtask_id: Parent subtask ID
        steps: List of step items - either strings (description only)
               or dicts with {description, spec, verify_command, expected_output}

    Returns:
        List of created step dicts.

    Raises:
        Exception: If subtask_id doesn't exist or on DB error.
    """
    if not steps:
        return []

    created = []
    with get_connection() as conn, conn.cursor() as cur:
        for idx, step in enumerate(steps, start=1):
            if isinstance(step, str):
                description = step
                spec = None
                verify_command = None
                expected_output = None
            else:
                description = step.get("description", "")
                spec = step.get("spec")
                verify_command = _sanitize_verify_command(step.get("verify_command"))
                expected_output = step.get("expected_output")

            spec_json = json.dumps(spec) if spec else None
            cur.execute(
                f"""
                INSERT INTO task_subtask_steps (subtask_id, step_number, description, spec, verify_command, expected_output)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (subtask_id, step_number) DO UPDATE SET
                    description = EXCLUDED.description,
                    spec = EXCLUDED.spec,
                    verify_command = EXCLUDED.verify_command,
                    expected_output = EXCLUDED.expected_output
                RETURNING {STEP_COLUMNS}
                """,
                (subtask_id, idx, description, spec_json, verify_command, expected_output),
            )
            row = cur.fetchone()
            created.append(_row_to_dict(row))

        conn.commit()

    logger.info("Created %d steps for subtask %s", len(created), subtask_id)
    return created


def append_steps(
    subtask_id: str,
    steps: Sequence[str | dict[str, Any]],
) -> list[dict[str, Any]]:
    """Append steps to a subtask, continuing from the highest existing step number.

    Unlike bulk_create_steps which starts at 1, this finds the max step_number
    and continues from there.

    Args:
        subtask_id: Parent subtask ID
        steps: List of step items - either strings (description only)
               or dicts with {description, spec, verify_command, expected_output}

    Returns:
        List of created step dicts.

    Raises:
        Exception: If subtask_id doesn't exist or on DB error.
    """
    if not steps:
        return []

    with get_connection() as conn, conn.cursor() as cur:
        # Find the current max step number
        cur.execute(
            "SELECT COALESCE(MAX(step_number), 0) FROM task_subtask_steps WHERE subtask_id = %s",
            (subtask_id,),
        )
        row = cur.fetchone()
        max_step: int = row[0] if row else 0

        created = []
        for idx, step in enumerate(steps, start=max_step + 1):
            if isinstance(step, str):
                description = step
                spec = None
                verify_command = None
                expected_output = None
            else:
                description = step.get("description", "")
                spec = step.get("spec")
                verify_command = _sanitize_verify_command(step.get("verify_command"))
                expected_output = step.get("expected_output")

            spec_json = json.dumps(spec) if spec else None
            cur.execute(
                f"""
                INSERT INTO task_subtask_steps (subtask_id, step_number, description, spec, verify_command, expected_output)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (subtask_id, step_number) DO UPDATE SET
                    description = EXCLUDED.description,
                    spec = EXCLUDED.spec,
                    verify_command = EXCLUDED.verify_command,
                    expected_output = EXCLUDED.expected_output
                RETURNING {STEP_COLUMNS}
                """,
                (subtask_id, idx, description, spec_json, verify_command, expected_output),
            )
            row = cur.fetchone()
            created.append(_row_to_dict(row))

        conn.commit()

    logger.info(
        "Appended %d steps to subtask %s (starting at step %d)",
        len(created),
        subtask_id,
        max_step + 1,
    )
    return created


def delete_steps_for_subtask(subtask_id: str) -> int:
    """Delete all steps for a subtask.

    Args:
        subtask_id: Parent subtask ID

    Returns:
        Number of steps deleted.
    """
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            "DELETE FROM task_subtask_steps WHERE subtask_id = %s",
            (subtask_id,),
        )
        count: int = cur.rowcount
        conn.commit()

    logger.debug("Deleted %d steps for subtask %s", count, subtask_id)
    return count


def insert_step(
    subtask_id: str,
    position: int,
    description: str,
    spec: dict[str, Any] | None = None,
    verify_command: str | None = None,
    expected_output: str | None = None,
) -> dict[str, Any]:
    """Insert a step at a specific position, shifting existing steps down.

    This allows inserting a step before an existing step. All steps at or after
    the insertion position are renumbered (incremented by 1).

    Args:
        subtask_id: Parent subtask ID (e.g., "task-abc123-1.1")
        position: Position to insert at (1-indexed). Existing steps at this
                  position and after are shifted down.
        description: Step description text
        spec: Optional JSONB spec for implementation details
        verify_command: Bash command to verify step completion
        expected_output: Expected output pattern for verification

    Returns:
        The created step dict.

    Raises:
        ValueError: If position < 1
        Exception: If subtask_id doesn't exist (FK constraint violation)
    """
    if position < 1:
        raise ValueError("Position must be >= 1")

    verify_command = _sanitize_verify_command(verify_command)
    spec_json = json.dumps(spec) if spec else None

    with get_connection() as conn, conn.cursor() as cur:
        # Get steps to shift (in reverse order to avoid unique constraint violations)
        cur.execute(
            """
            SELECT step_number FROM task_subtask_steps
            WHERE subtask_id = %s AND step_number >= %s
            ORDER BY step_number DESC
            """,
            (subtask_id, position),
        )
        steps_to_shift = [row[0] for row in cur.fetchall()]

        # Shift each step individually in reverse order
        for step_num in steps_to_shift:
            cur.execute(
                """
                UPDATE task_subtask_steps
                SET step_number = %s
                WHERE subtask_id = %s AND step_number = %s
                """,
                (step_num + 1, subtask_id, step_num),
            )
        shifted = len(steps_to_shift)

        # Insert the new step at the position
        cur.execute(
            f"""
            INSERT INTO task_subtask_steps (subtask_id, step_number, description, spec, verify_command, expected_output)
            VALUES (%s, %s, %s, %s, %s, %s)
            RETURNING {STEP_COLUMNS}
            """,
            (subtask_id, position, description, spec_json, verify_command, expected_output),
        )
        row = cur.fetchone()
        conn.commit()

    logger.info(
        "Inserted step at position %d for subtask %s (shifted %d existing steps)",
        position,
        subtask_id,
        shifted,
    )
    return _row_to_dict(row)
