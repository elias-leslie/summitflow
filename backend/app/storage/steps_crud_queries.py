"""Database query operations for step CRUD."""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any

from ..logging_config import get_logger
from .connection import get_connection
from .steps_crud_serialization import STEP_COLUMNS, row_to_dict

logger = get_logger(__name__)
_STEP_SHIFT_OFFSET = 1_000_000

_UPSERT_SQL = (
    "INSERT INTO task_subtask_steps (subtask_id, step_number, description, spec) "
    "VALUES (%s, %s, %s, %s) "
    "ON CONFLICT (subtask_id, step_number) DO UPDATE SET "
    "    description = EXCLUDED.description, spec = EXCLUDED.spec "
    f"RETURNING {STEP_COLUMNS}"
)
_SELECT_SQL = f"SELECT {STEP_COLUMNS} FROM task_subtask_steps"
_MAX_STEP_SQL = "SELECT COALESCE(MAX(step_number), 0) FROM task_subtask_steps WHERE subtask_id = %s"


def _parse_step_input(step: str | dict[str, Any]) -> tuple[str, dict[str, Any] | None]:
    """Parse step input into (description, spec) tuple."""
    if isinstance(step, str):
        return step, None
    return step.get("description", ""), step.get("spec")


def _spec_json(spec: dict[str, Any] | None) -> str | None:
    """Serialize spec to JSON or return None."""
    return json.dumps(spec) if spec else None


def execute_create_step(subtask_id: str, step_number: int, description: str, spec: dict[str, Any] | None) -> dict[str, Any]:
    """Execute INSERT query for a single step."""
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(_UPSERT_SQL, (subtask_id, step_number, description, _spec_json(spec)))
        row = cur.fetchone()
        conn.commit()
    logger.debug("Created step %d for subtask %s", step_number, subtask_id)
    return row_to_dict(row)


def execute_get_steps(subtask_id: str) -> list[dict[str, Any]]:
    """Execute SELECT query for all steps in a subtask."""
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(f"{_SELECT_SQL} WHERE subtask_id = %s ORDER BY step_number", (subtask_id,))
        rows = cur.fetchall()
    return [row_to_dict(row) for row in rows]


def execute_get_single_step(subtask_id: str, step_number: int) -> dict[str, Any] | None:
    """Execute SELECT query for a single step."""
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(f"{_SELECT_SQL} WHERE subtask_id = %s AND step_number = %s", (subtask_id, step_number))
        row = cur.fetchone()
    return row_to_dict(row) if row else None


def _insert_steps_in_cursor(cur: Any, subtask_id: str, steps: Sequence[str | dict[str, Any]], start: int) -> list[dict[str, Any]]:
    """Insert steps sequentially using an existing cursor, returning created rows."""
    created = []
    for idx, step in enumerate(steps, start=start):
        description, spec = _parse_step_input(step)
        cur.execute(_UPSERT_SQL, (subtask_id, idx, description, _spec_json(spec)))
        created.append(row_to_dict(cur.fetchone()))
    return created


def execute_bulk_insert(subtask_id: str, steps: Sequence[str | dict[str, Any]]) -> list[dict[str, Any]]:
    """Execute batch INSERT for multiple steps."""
    if not steps:
        return []
    with get_connection() as conn, conn.cursor() as cur:
        created = _insert_steps_in_cursor(cur, subtask_id, steps, start=1)
        conn.commit()
    logger.info("Created %d steps for subtask %s", len(created), subtask_id)
    return created


def execute_append_steps(subtask_id: str, steps: Sequence[str | dict[str, Any]]) -> list[dict[str, Any]]:
    """Execute INSERT for appending steps after finding max step number."""
    if not steps:
        return []
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(_MAX_STEP_SQL, (subtask_id,))
        max_step: int = (cur.fetchone() or (0,))[0]
        created = _insert_steps_in_cursor(cur, subtask_id, steps, start=max_step + 1)
        conn.commit()
    logger.info("Appended %d steps to subtask %s (starting at step %d)", len(created), subtask_id, max_step + 1)
    return created


def execute_delete_all_steps(subtask_id: str) -> int:
    """Execute DELETE for all steps in a subtask."""
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM task_subtask_steps WHERE subtask_id = %s", (subtask_id,))
        count: int = cur.rowcount
        conn.commit()
    logger.debug("Deleted %d steps for subtask %s", count, subtask_id)
    return count


def _shift_steps_up(cur: Any, subtask_id: str, position: int) -> int:
    """Shift all steps at or after position up by 1; returns count of shifted steps."""
    # Two-phase update: first add a large offset to move all affected rows out of range,
    # then normalize back to the target values. This avoids unique constraint violations
    # that would occur if we incremented step_number by 1 directly (colliding with the
    # next row before it is shifted).
    cur.execute(
        """
        UPDATE task_subtask_steps
        SET step_number = step_number + %s
        WHERE subtask_id = %s AND step_number >= %s
        """,
        (_STEP_SHIFT_OFFSET, subtask_id, position),
    )
    shifted = cur.rowcount
    if shifted:
        cur.execute(
            """
            UPDATE task_subtask_steps
            SET step_number = step_number - %s + 1
            WHERE subtask_id = %s AND step_number >= %s
            """,
            (_STEP_SHIFT_OFFSET, subtask_id, position + _STEP_SHIFT_OFFSET),
        )
    return shifted


def execute_insert_step(subtask_id: str, position: int, description: str, spec: dict[str, Any] | None) -> dict[str, Any]:
    """Execute INSERT with step renumbering for insertion at a position."""
    if position < 1:
        raise ValueError("Position must be >= 1")
    with get_connection() as conn, conn.cursor() as cur:
        shifted = _shift_steps_up(cur, subtask_id, position)
        cur.execute(
            f"INSERT INTO task_subtask_steps (subtask_id, step_number, description, spec) VALUES (%s, %s, %s, %s) RETURNING {STEP_COLUMNS}",
            (subtask_id, position, description, _spec_json(spec)),
        )
        row = cur.fetchone()
        conn.commit()
    logger.info("Inserted step at position %d for subtask %s (shifted %d existing steps)", position, subtask_id, shifted)
    return row_to_dict(row)
