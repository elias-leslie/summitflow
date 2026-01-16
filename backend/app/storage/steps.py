"""Steps storage layer - CRUD operations for subtask steps.

This module provides data access for the task_subtask_steps table, which stores
normalized step data for granular completion tracking within subtasks.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

from psycopg.rows import TupleRow

from .connection import get_connection

logger = logging.getLogger(__name__)

# Column list for all step SELECT/RETURNING queries (8 columns)
STEP_COLUMNS = """id, subtask_id, step_number, description, spec, passes, passed_at, created_at"""

# Expected column count for row validation
EXPECTED_STEP_COLUMNS = 8


def _row_to_dict(row: TupleRow | tuple[Any, ...] | None) -> dict[str, Any]:
    """Convert a database row to a step dict.

    Column order (8 columns):
        id, subtask_id, step_number, description, spec, passes, passed_at, created_at
    """
    if row is None:
        raise ValueError("Row cannot be None")
    if len(row) != EXPECTED_STEP_COLUMNS:
        raise ValueError(f"Expected {EXPECTED_STEP_COLUMNS} columns, got {len(row)}")
    return {
        "id": row[0],
        "subtask_id": row[1],
        "step_number": row[2],
        "description": row[3],
        "spec": row[4],
        "passes": row[5],
        "passed_at": row[6].isoformat() if row[6] else None,
        "created_at": row[7].isoformat() if row[7] else None,
    }


def create_step(
    subtask_id: str,
    step_number: int,
    description: str,
    spec: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Create a new step for a subtask.

    Args:
        subtask_id: Parent subtask ID (e.g., "task-abc123-1.1")
        step_number: 1-indexed step number within subtask
        description: Step description text
        spec: Optional JSONB spec for implementation details

    Returns:
        The created step dict.

    Raises:
        Exception: If subtask_id doesn't exist (FK constraint violation)
    """

    spec_json = json.dumps(spec) if spec else None

    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            f"""
            INSERT INTO task_subtask_steps (subtask_id, step_number, description, spec)
            VALUES (%s, %s, %s, %s)
            RETURNING {STEP_COLUMNS}
            """,
            (subtask_id, step_number, description, spec_json),
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


class StepGateError(Exception):
    """Raised when step completion gate is violated."""

    def __init__(self, message: str, missing_steps: list[int] | None = None):
        super().__init__(message)
        self.missing_steps = missing_steps or []


def update_step_passes(
    subtask_id: str,
    step_number: int,
    passes: bool,
    force: bool = False,  # Deprecated: kept for API compatibility, ignored
) -> dict[str, Any] | None:
    """Update step passes status.

    When passes is set to True, also sets passed_at timestamp.
    When passes is set to False, clears passed_at.

    Note: Sequential step completion is logged but not enforced as a gate.
    Verification is now handled by criterion verification.

    Args:
        subtask_id: Parent subtask ID
        step_number: Step number to update
        passes: Whether the step passes
        force: DEPRECATED - kept for API compatibility, ignored

    Returns:
        Updated step dict or None if not found.
    """
    _ = force  # Deprecated parameter, ignored
    passed_at = datetime.now(UTC) if passes else None

    with get_connection() as conn, conn.cursor() as cur:
        # Log incomplete previous steps for context (no longer enforced as gate)
        if passes and step_number > 1:
            cur.execute(
                """
                SELECT step_number FROM task_subtask_steps
                WHERE subtask_id = %s AND step_number < %s AND passes = FALSE
                ORDER BY step_number
                """,
                (subtask_id, step_number),
            )
            incomplete = [row[0] for row in cur.fetchall()]
            if incomplete:
                logger.info(
                    f"Marking step {step_number} as passed with incomplete previous steps: {incomplete}. "
                    "Verification is handled by criterion verification."
                )

        cur.execute(
            f"""
            UPDATE task_subtask_steps
            SET passes = %s, passed_at = %s
            WHERE subtask_id = %s AND step_number = %s
            RETURNING {STEP_COLUMNS}
            """,
            (passes, passed_at, subtask_id, step_number),
        )
        row = cur.fetchone()
        conn.commit()

    if not row:
        logger.warning("Step %d not found for subtask %s", step_number, subtask_id)
        return None

    logger.debug("Updated step %d passes=%s for subtask %s", step_number, passes, subtask_id)
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
               or dicts with {description: str, spec: dict | None}

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
            else:
                description = step.get("description", "")
                spec = step.get("spec")

            spec_json = json.dumps(spec) if spec else None
            cur.execute(
                f"""
                INSERT INTO task_subtask_steps (subtask_id, step_number, description, spec)
                VALUES (%s, %s, %s, %s)
                RETURNING {STEP_COLUMNS}
                """,
                (subtask_id, idx, description, spec_json),
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
               or dicts with {description: str, spec: dict | None}

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
            else:
                description = step.get("description", "")
                spec = step.get("spec")

            spec_json = json.dumps(spec) if spec else None
            cur.execute(
                f"""
                INSERT INTO task_subtask_steps (subtask_id, step_number, description, spec)
                VALUES (%s, %s, %s, %s)
                RETURNING {STEP_COLUMNS}
                """,
                (subtask_id, idx, description, spec_json),
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


def delete_step(subtask_id: str, step_number: int) -> bool:
    """Delete a single step from a subtask.

    Args:
        subtask_id: Parent subtask ID (e.g., "task-abc123-1.1")
        step_number: Step number to delete

    Returns:
        True if step was deleted, False if not found.
    """
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            "DELETE FROM task_subtask_steps WHERE subtask_id = %s AND step_number = %s",
            (subtask_id, step_number),
        )
        deleted: bool = cur.rowcount > 0
        conn.commit()

    if deleted:
        logger.info("Deleted step %d from subtask %s", step_number, subtask_id)
    else:
        logger.warning("Step %d not found in subtask %s", step_number, subtask_id)

    return deleted


def get_step_summary(subtask_id: str) -> dict[str, Any]:
    """Get summary of step completion for a subtask.

    Returns:
        Dict with keys:
            - total: Total number of steps
            - completed: Number of steps with passes=True
            - progress_percent: Completion percentage (0-100)
    """
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT
                COUNT(*) as total,
                COUNT(*) FILTER (WHERE passes = TRUE) as completed
            FROM task_subtask_steps
            WHERE subtask_id = %s
            """,
            (subtask_id,),
        )
        row = cur.fetchone()

    total = row[0] if row else 0
    completed = row[1] if row else 0
    progress_percent = round((completed / total * 100) if total > 0 else 0, 1)

    return {
        "total": total,
        "completed": completed,
        "progress_percent": progress_percent,
    }
