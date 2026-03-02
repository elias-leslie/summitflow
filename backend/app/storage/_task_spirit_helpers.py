"""Internal helpers for task_spirit storage - row conversion utilities."""

from __future__ import annotations

from typing import Any

from psycopg.rows import TupleRow

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
