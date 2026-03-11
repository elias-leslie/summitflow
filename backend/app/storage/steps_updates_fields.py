"""Step field updates (description)."""

from __future__ import annotations

from typing import Any

from ..logging_config import get_logger
from .connection import get_connection
from .steps_crud import get_step
from .steps_crud_serialization import STEP_COLUMNS, row_to_dict

logger = get_logger(__name__)


def update_step_fields(
    subtask_id: str,
    step_number: int,
    description: str | None = None,
) -> dict[str, Any] | None:
    """Update step description.

    Only the description field can be updated.

    Args:
        subtask_id: Parent subtask ID
        step_number: Step number to update
        description: Step description

    Returns:
        Updated step dict or None if not found.
    """
    # Build dynamic UPDATE based on provided fields
    updates: list[str] = []
    values: list[Any] = []

    if description is not None:
        updates.append("description = %s")
        values.append(description)

    if not updates:
        # Nothing to update - just return existing step
        return get_step(subtask_id, step_number)

    values.extend([subtask_id, step_number])

    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            f"""
            UPDATE task_subtask_steps
            SET {", ".join(updates)}
            WHERE subtask_id = %s AND step_number = %s
            RETURNING {STEP_COLUMNS}
            """,
            tuple(values),
        )
        row = cur.fetchone()
        conn.commit()

    if not row:
        logger.warning("Step %d not found for subtask %s", step_number, subtask_id)
        return None

    logger.info("Updated step %d fields for subtask %s", step_number, subtask_id)
    return row_to_dict(row)
