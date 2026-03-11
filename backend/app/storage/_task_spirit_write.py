"""Internal write operations for task_spirit storage - create, upsert, delete."""

from __future__ import annotations

import json
from typing import Any

from ..logging_config import get_logger
from ._task_spirit_helpers import SPIRIT_SELECT, _row_to_dict
from .connection import get_connection

logger = get_logger(__name__)

_INSERT_FIELDS = "(task_id, objective, spirit_anti, decisions, constraints, done_when, context, complexity)"
_INSERT_PLACEHOLDERS = "(%s, %s, %s, %s, %s, %s, %s, %s)"


def _build_insert_params(
    task_id: str,
    objective: str,
    spirit_anti: str | None,
    decisions: list[dict[str, Any]] | None,
    constraints: list[str] | None,
    done_when: list[str] | None,
    context: dict[str, Any] | None,
    complexity: str | None,
) -> tuple[Any, ...]:
    return (
        task_id,
        objective,
        spirit_anti,
        json.dumps(decisions or []),
        json.dumps(constraints or []),
        json.dumps(done_when or []),
        json.dumps(context or {}),
        complexity,
    )


def create_task_spirit(
    task_id: str,
    objective: str,
    spirit_anti: str | None = None,
    decisions: list[dict[str, Any]] | None = None,
    constraints: list[str] | None = None,
    done_when: list[str] | None = None,
    context: dict[str, Any] | None = None,
    complexity: str | None = None,
) -> dict[str, Any]:
    """Create a task_spirit record for a task.

    Args:
        task_id: The task ID (FK to tasks)
        objective: What the task aims to achieve
        spirit_anti: What to avoid during implementation
        decisions: List of architectural/design decisions
        constraints: List of implementation constraints
        done_when: List of completion criteria
        context: JSONB blob for plan.json context preservation
        complexity: SIMPLE|STANDARD|COMPLEX

    Returns:
        Created task_spirit record as dict
    """
    params = _build_insert_params(
        task_id, objective, spirit_anti, decisions, constraints, done_when, context, complexity
    )
    sql = f"INSERT INTO task_spirit {_INSERT_FIELDS} VALUES {_INSERT_PLACEHOLDERS} RETURNING {SPIRIT_SELECT}"
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(sql, params)
        row = cur.fetchone()
        conn.commit()
    logger.info("Created task_spirit for task %s", task_id)
    result = _row_to_dict(row)
    if result is None:
        raise ValueError(f"Failed to create task_spirit for {task_id}")
    return result


def upsert_task_spirit(
    task_id: str,
    objective: str,
    spirit_anti: str | None = None,
    decisions: list[dict[str, Any]] | None = None,
    constraints: list[str] | None = None,
    done_when: list[str] | None = None,
    context: dict[str, Any] | None = None,
    complexity: str | None = None,
) -> dict[str, Any]:
    """Create or update task_spirit record.

    Used during plan.json import to handle both new tasks and updates.
    """
    params = _build_insert_params(
        task_id, objective, spirit_anti, decisions, constraints, done_when, context, complexity
    )
    sql = f"""
        INSERT INTO task_spirit {_INSERT_FIELDS} VALUES {_INSERT_PLACEHOLDERS}
        ON CONFLICT (task_id) DO UPDATE SET
            objective = EXCLUDED.objective,
            spirit_anti = EXCLUDED.spirit_anti,
            decisions = EXCLUDED.decisions,
            constraints = EXCLUDED.constraints,
            done_when = EXCLUDED.done_when,
            context = EXCLUDED.context,
            complexity = EXCLUDED.complexity,
            updated_at = NOW()
        RETURNING {SPIRIT_SELECT}
    """
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(sql, params)
        row = cur.fetchone()
        conn.commit()
    logger.info("Upserted task_spirit for task %s", task_id)
    result = _row_to_dict(row)
    if result is None:
        raise ValueError(f"Failed to upsert task_spirit for {task_id}")
    return result


def delete_task_spirit(task_id: str) -> bool:
    """Delete task_spirit record.

    Usually handled by CASCADE on tasks deletion.
    """
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute("DELETE FROM task_spirit WHERE task_id = %s", (task_id,))
        deleted = cur.rowcount > 0
        conn.commit()
    if deleted:
        logger.info("Deleted task_spirit for task %s", task_id)
    return deleted
