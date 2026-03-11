"""Task Spirit storage - Agent guidance and plan approval workflow.

Handles the task_spirit table which stores:
- objective, spirit_anti (agent guidance)
- decisions, constraints, done_when (JSONB arrays)
- context (JSONB blob for plan.json round-trip)
- plan_status, plan_approved_at/by, plan_history (workflow)
- complexity (SIMPLE|STANDARD|COMPLEX)

Public API is re-exported from internal modules for maintainability.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from ._task_spirit_helpers import EXPECTED_COLUMNS, SPIRIT_SELECT, _row_to_dict
from ._task_spirit_workflow import approve_plan, reject_plan, set_plan_status
from ._task_spirit_write import create_task_spirit, delete_task_spirit, upsert_task_spirit
from .connection import get_connection

__all__ = [
    "EXPECTED_COLUMNS",
    "SPIRIT_SELECT",
    "_row_to_dict",
    "approve_plan",
    "create_task_spirit",
    "delete_task_spirit",
    "get_task_spirit",
    "reject_plan",
    "set_plan_status",
    "update_task_spirit",
    "upsert_task_spirit",
]

logger = logging.getLogger(__name__)


def get_task_spirit(task_id: str) -> dict[str, Any] | None:
    """Get task_spirit record by task ID."""
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(f"SELECT {SPIRIT_SELECT} FROM task_spirit WHERE task_id = %s", (task_id,))
        return _row_to_dict(cur.fetchone())


def update_task_spirit(task_id: str, **fields: Any) -> dict[str, Any] | None:
    """Update task_spirit record.

    Args:
        task_id: The task ID
        **fields: Fields to update (objective, spirit_anti, decisions, constraints,
                  done_when, context, complexity, plan_status)

    Returns:
        Updated record or None if not found
    """
    allowed_fields = {
        "objective", "spirit_anti", "decisions", "constraints",
        "done_when", "context", "complexity", "plan_status",
    }
    updates = {k: v for k, v in fields.items() if k in allowed_fields}
    if not updates:
        return get_task_spirit(task_id)

    for jsonb_field in ["decisions", "constraints", "done_when", "context"]:
        if jsonb_field in updates:
            updates[jsonb_field] = json.dumps(updates[jsonb_field])

    set_clause = ", ".join(f"{k} = %s" for k in updates)
    values = [*list(updates.values()), task_id]

    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            f"UPDATE task_spirit SET {set_clause} WHERE task_id = %s RETURNING {SPIRIT_SELECT}",
            values,
        )
        row = cur.fetchone()
        conn.commit()
    if row:
        logger.info("Updated task_spirit for task %s: %s", task_id, list(updates.keys()))
    return _row_to_dict(row)
