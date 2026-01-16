"""Task Spirit storage - Agent guidance and plan approval workflow.

Handles the task_spirit table which stores:
- objective, spirit_anti (agent guidance)
- decisions, constraints, done_when (JSONB arrays)
- context (JSONB blob for plan.json round-trip)
- plan_status, plan_approved_at/by, plan_history (workflow)
- complexity (SIMPLE|STANDARD|COMPLEX)
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from typing import Any

from psycopg.rows import TupleRow

from .connection import get_connection

logger = logging.getLogger(__name__)

# Expected columns for validation
EXPECTED_COLUMNS = 14  # task_id, objective, spirit_anti, decisions, constraints, done_when, context, plan_status, plan_approved_at, plan_approved_by, plan_history, created_at, updated_at, complexity


def _row_to_dict(row: TupleRow | tuple[Any, ...] | None) -> dict[str, Any] | None:
    """Convert a task_spirit row to a dictionary.

    Column order (from DB ordinal_position):
        1: task_id, 2: objective, 3: spirit_anti, 4: decisions, 5: constraints,
        6: done_when, 7: context, 8: plan_status, 9: plan_approved_at,
        10: plan_approved_by, 11: plan_history, 12: created_at, 13: updated_at,
        14: complexity
    """
    if row is None:
        return None
    if len(row) != EXPECTED_COLUMNS:
        raise ValueError(f"Expected {EXPECTED_COLUMNS} columns for task_spirit, got {len(row)}")
    return {
        "task_id": row[0],
        "objective": row[1],
        "spirit_anti": row[2],
        "decisions": row[3] if row[3] else [],
        "constraints": row[4] if row[4] else [],
        "done_when": row[5] if row[5] else [],
        "context": row[6] if row[6] else {},
        "plan_status": row[7],
        "plan_approved_at": row[8].isoformat() if row[8] else None,
        "plan_approved_by": row[9],
        "plan_history": row[10] if row[10] else [],
        "created_at": row[11].isoformat() if row[11] else None,
        "updated_at": row[12].isoformat() if row[12] else None,
        "complexity": row[13],
    }


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
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO task_spirit (
                task_id, objective, spirit_anti, decisions, constraints,
                done_when, context, complexity
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING *
            """,
            (
                task_id,
                objective,
                spirit_anti,
                json.dumps(decisions or []),
                json.dumps(constraints or []),
                json.dumps(done_when or []),
                json.dumps(context or {}),
                complexity,
            ),
        )
        row = cur.fetchone()
        conn.commit()
        logger.info(f"Created task_spirit for task {task_id}")
        result = _row_to_dict(row)
        if result is None:
            raise ValueError(f"Failed to create task_spirit for {task_id}")
        return result


def get_task_spirit(task_id: str) -> dict[str, Any] | None:
    """Get task_spirit record by task ID."""
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute("SELECT * FROM task_spirit WHERE task_id = %s", (task_id,))
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
        "objective",
        "spirit_anti",
        "decisions",
        "constraints",
        "done_when",
        "context",
        "complexity",
        "plan_status",
    }
    updates = {k: v for k, v in fields.items() if k in allowed_fields}
    if not updates:
        return get_task_spirit(task_id)

    # Convert JSONB fields
    for jsonb_field in ["decisions", "constraints", "done_when", "context"]:
        if jsonb_field in updates:
            updates[jsonb_field] = json.dumps(updates[jsonb_field])

    set_clause = ", ".join(f"{k} = %s" for k in updates)
    values = [*list(updates.values()), task_id]

    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            f"UPDATE task_spirit SET {set_clause} WHERE task_id = %s RETURNING *",
            values,
        )
        row = cur.fetchone()
        conn.commit()
        if row:
            logger.info(f"Updated task_spirit for task {task_id}: {list(updates.keys())}")
        return _row_to_dict(row)


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
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO task_spirit (
                task_id, objective, spirit_anti, decisions, constraints,
                done_when, context, complexity
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (task_id) DO UPDATE SET
                objective = EXCLUDED.objective,
                spirit_anti = EXCLUDED.spirit_anti,
                decisions = EXCLUDED.decisions,
                constraints = EXCLUDED.constraints,
                done_when = EXCLUDED.done_when,
                context = EXCLUDED.context,
                complexity = EXCLUDED.complexity,
                updated_at = NOW()
            RETURNING *
            """,
            (
                task_id,
                objective,
                spirit_anti,
                json.dumps(decisions or []),
                json.dumps(constraints or []),
                json.dumps(done_when or []),
                json.dumps(context or {}),
                complexity,
            ),
        )
        row = cur.fetchone()
        conn.commit()
        logger.info(f"Upserted task_spirit for task {task_id}")
        result = _row_to_dict(row)
        if result is None:
            raise ValueError(f"Failed to upsert task_spirit for {task_id}")
        return result


def approve_plan(
    task_id: str,
    approved_by: str = "user",
    notes: str | None = None,
) -> dict[str, Any] | None:
    """Approve a task's plan, allowing execution to start.

    Args:
        task_id: The task ID
        approved_by: Who/what approved the plan
        notes: Optional approval notes

    Returns:
        Updated record or None if not found
    """
    now = datetime.now(UTC)
    history_entry = {
        "status": "approved",
        "timestamp": now.isoformat(),
        "actor": approved_by,
        "notes": notes,
    }

    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            UPDATE task_spirit SET
                plan_status = 'approved',
                plan_approved_at = %s,
                plan_approved_by = %s,
                plan_history = plan_history || %s::jsonb
            WHERE task_id = %s
            RETURNING *
            """,
            (now, approved_by, json.dumps([history_entry]), task_id),
        )
        row = cur.fetchone()
        conn.commit()
        if row:
            logger.info(f"Approved plan for task {task_id} by {approved_by}")
        return _row_to_dict(row)


def reject_plan(
    task_id: str,
    rejected_by: str = "user",
    reason: str | None = None,
) -> dict[str, Any] | None:
    """Reject a task's plan, requiring revision.

    Args:
        task_id: The task ID
        rejected_by: Who/what rejected the plan
        reason: Reason for rejection

    Returns:
        Updated record or None if not found
    """
    now = datetime.now(UTC)
    history_entry = {
        "status": "rejected",
        "timestamp": now.isoformat(),
        "actor": rejected_by,
        "reason": reason,
    }

    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            UPDATE task_spirit SET
                plan_status = 'rejected',
                plan_history = plan_history || %s::jsonb
            WHERE task_id = %s
            RETURNING *
            """,
            (json.dumps([history_entry]), task_id),
        )
        row = cur.fetchone()
        conn.commit()
        if row:
            logger.info(f"Rejected plan for task {task_id} by {rejected_by}: {reason}")
        return _row_to_dict(row)


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
            logger.info(f"Deleted task_spirit for task {task_id}")
        return deleted
