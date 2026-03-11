"""Subtask bulk operations.

This module provides bulk creation operations for subtasks.
"""

from __future__ import annotations

from typing import Any

from ..logging_config import get_logger
from .connection import get_connection
from .steps import bulk_create_steps
from .subtasks_helpers import SUBTASK_COLUMNS, generate_subtask_id, row_to_dict

logger = get_logger(__name__)

_INSERT_SQL = f"""
    INSERT INTO task_subtasks (id, task_id, subtask_id, phase, description,
                               display_order, subtask_type)
    VALUES (%s, %s, %s, %s, %s, %s, %s)
    ON CONFLICT (task_id, subtask_id) DO UPDATE SET
        phase = EXCLUDED.phase,
        description = EXCLUDED.description,
        display_order = EXCLUDED.display_order,
        subtask_type = EXCLUDED.subtask_type
    RETURNING {SUBTASK_COLUMNS}
"""


def _insert_one_subtask(cur: Any, task_id: str, subtask: dict[str, Any], idx: int) -> tuple[dict[str, Any], str, list[Any]]:
    """Execute the INSERT for a single subtask row and return (row_dict, table_id, steps)."""
    subtask_id = subtask["subtask_id"]
    table_id = generate_subtask_id(task_id, subtask_id)
    display_order = subtask.get("display_order", idx)
    steps = subtask.get("steps", [])

    cur.execute(
        _INSERT_SQL,
        (
            table_id,
            task_id,
            subtask_id,
            subtask.get("phase"),
            subtask["description"],
            display_order,
            subtask.get("subtask_type"),
        ),
    )
    row = cur.fetchone()
    return row_to_dict(row), table_id, steps


def _insert_subtasks_in_transaction(
    task_id: str,
    subtasks: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[tuple[str, list[str | dict[str, Any]]]]]:
    """Insert subtask rows inside a single DB transaction.

    Returns:
        A tuple of (created_subtask_dicts, steps_to_create) where
        steps_to_create is a list of (subtask_table_id, step_items) pairs
        for subtasks that have steps defined.
    """
    created: list[dict[str, Any]] = []
    steps_to_create: list[tuple[str, list[str | dict[str, Any]]]] = []

    with get_connection() as conn, conn.cursor() as cur:
        for idx, subtask in enumerate(subtasks):
            row_dict, table_id, steps = _insert_one_subtask(cur, task_id, subtask, idx)
            created.append(row_dict)
            if steps:
                steps_to_create.append((table_id, steps))
        conn.commit()

    return created, steps_to_create


def _create_steps_for_subtasks(
    steps_to_create: list[tuple[str, list[str | dict[str, Any]]]],
) -> dict[str, list[dict[str, Any]]]:
    """Create step rows for each subtask outside the subtask transaction.

    Args:
        steps_to_create: List of (subtask_table_id, step_items) pairs.

    Returns:
        Mapping of subtask_table_id -> list of created step dicts.
    """
    subtasks_with_steps: dict[str, list[dict[str, Any]]] = {}
    for subtask_table_id, step_items in steps_to_create:
        try:
            created_steps = bulk_create_steps(subtask_table_id, step_items)
            subtasks_with_steps[subtask_table_id] = created_steps
        except ValueError:
            raise  # Validation errors must propagate
        except Exception as e:
            logger.error("Failed to create steps for subtask %s: %s", subtask_table_id, e)
            # Continue - subtask created, steps failed (partial success)
    return subtasks_with_steps


def _attach_steps_to_subtasks(
    created: list[dict[str, Any]],
    subtasks_with_steps: dict[str, list[dict[str, Any]]],
) -> None:
    """Mutate each subtask dict to include its created steps list."""
    for subtask in created:
        subtask_table_id = subtask["id"]
        if subtask_table_id in subtasks_with_steps:
            subtask["steps_from_table"] = subtasks_with_steps[subtask_table_id]


def bulk_create_subtasks(
    task_id: str,
    subtasks: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Create multiple subtasks for a task in a single transaction.

    Also creates step rows in task_subtask_steps table when steps are provided.
    The JSONB steps column is not used (deprecated).

    Args:
        task_id: Parent task ID
        subtasks: List of subtask dicts with keys:
            - subtask_id: str (required) - e.g., "1.1"
            - description: str (required)
            - phase: str (optional)
            - steps: list[str | dict] (optional) - strings or {description, spec} objects
            - display_order: int (optional, auto-assigned if missing)

    Returns:
        List of created subtask dicts.

    Raises:
        Exception: If task_id doesn't exist or on DB error.
    """
    if not subtasks:
        return []

    created, steps_to_create = _insert_subtasks_in_transaction(task_id, subtasks)
    subtasks_with_steps = _create_steps_for_subtasks(steps_to_create)
    _attach_steps_to_subtasks(created, subtasks_with_steps)

    logger.info("Created %d subtasks for task %s", len(created), task_id)
    return created
