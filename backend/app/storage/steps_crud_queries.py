"""Database query operations for step CRUD."""

from __future__ import annotations

import json
import logging
from collections.abc import Sequence
from typing import Any

from .connection import get_connection
from .steps_crud_serialization import STEP_COLUMNS, row_to_dict

logger = logging.getLogger(__name__)


def execute_create_step(
    subtask_id: str,
    step_number: int,
    description: str,
    spec: dict[str, Any] | None,
) -> dict[str, Any]:
    """Execute INSERT query for a single step."""
    spec_json = json.dumps(spec) if spec else None

    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            f"""
            INSERT INTO task_subtask_steps (subtask_id, step_number, description, spec)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (subtask_id, step_number) DO UPDATE SET
                description = EXCLUDED.description,
                spec = EXCLUDED.spec
            RETURNING {STEP_COLUMNS}
            """,
            (subtask_id, step_number, description, spec_json),
        )
        row = cur.fetchone()
        conn.commit()

    logger.debug("Created step %d for subtask %s", step_number, subtask_id)
    return row_to_dict(row)


def execute_get_steps(subtask_id: str) -> list[dict[str, Any]]:
    """Execute SELECT query for all steps in a subtask."""
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

    return [row_to_dict(row) for row in rows]


def execute_get_single_step(subtask_id: str, step_number: int) -> dict[str, Any] | None:
    """Execute SELECT query for a single step."""
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

    return row_to_dict(row)


def execute_bulk_insert(
    subtask_id: str,
    steps: Sequence[str | dict[str, Any]],
) -> list[dict[str, Any]]:
    """Execute batch INSERT for multiple steps."""
    if not steps:
        return []

    created = []
    with get_connection() as conn, conn.cursor() as cur:
        for idx, step in enumerate(steps, start=1):
            description, spec = _parse_step_input(step)
            spec_json = json.dumps(spec) if spec else None

            cur.execute(
                f"""
                INSERT INTO task_subtask_steps (subtask_id, step_number, description, spec)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (subtask_id, step_number) DO UPDATE SET
                    description = EXCLUDED.description,
                    spec = EXCLUDED.spec
                RETURNING {STEP_COLUMNS}
                """,
                (subtask_id, idx, description, spec_json),
            )
            row = cur.fetchone()
            created.append(row_to_dict(row))

        conn.commit()

    logger.info("Created %d steps for subtask %s", len(created), subtask_id)
    return created


def execute_append_steps(
    subtask_id: str,
    steps: Sequence[str | dict[str, Any]],
) -> list[dict[str, Any]]:
    """Execute INSERT for appending steps after finding max step number."""
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
            description, spec = _parse_step_input(step)
            spec_json = json.dumps(spec) if spec else None

            cur.execute(
                f"""
                INSERT INTO task_subtask_steps (subtask_id, step_number, description, spec)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (subtask_id, step_number) DO UPDATE SET
                    description = EXCLUDED.description,
                    spec = EXCLUDED.spec
                RETURNING {STEP_COLUMNS}
                """,
                (subtask_id, idx, description, spec_json),
            )
            row = cur.fetchone()
            created.append(row_to_dict(row))

        conn.commit()

    logger.info(
        "Appended %d steps to subtask %s (starting at step %d)",
        len(created),
        subtask_id,
        max_step + 1,
    )
    return created


def execute_delete_all_steps(subtask_id: str) -> int:
    """Execute DELETE for all steps in a subtask."""
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            "DELETE FROM task_subtask_steps WHERE subtask_id = %s",
            (subtask_id,),
        )
        count: int = cur.rowcount
        conn.commit()

    logger.debug("Deleted %d steps for subtask %s", count, subtask_id)
    return count


def execute_insert_step(
    subtask_id: str,
    position: int,
    description: str,
    spec: dict[str, Any] | None,
) -> dict[str, Any]:
    """Execute INSERT with step renumbering for insertion at a position."""
    if position < 1:
        raise ValueError("Position must be >= 1")

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
            INSERT INTO task_subtask_steps (subtask_id, step_number, description, spec)
            VALUES (%s, %s, %s, %s)
            RETURNING {STEP_COLUMNS}
            """,
            (subtask_id, position, description, spec_json),
        )
        row = cur.fetchone()
        conn.commit()

    logger.info(
        "Inserted step at position %d for subtask %s (shifted %d existing steps)",
        position,
        subtask_id,
        shifted,
    )
    return row_to_dict(row)


def _parse_step_input(
    step: str | dict[str, Any],
) -> tuple[str, dict[str, Any] | None]:
    """Parse step input into components."""
    if isinstance(step, str):
        return step, None

    description = step.get("description", "")
    spec = step.get("spec")
    return description, spec
