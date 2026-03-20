"""Internal helpers for task_spirit storage - row conversion utilities."""

from __future__ import annotations

from typing import Any

from psycopg.rows import TupleRow

from ..services.task_plan_context import hydrate_task_plan_fields

# Explicit column list for SELECT queries (avoids SELECT * fragility)
# Simplified: dropped objective, spirit_anti, decisions, constraints
SPIRIT_COLUMNS = (
    "task_id", "done_when", "context", "plan_status", "plan_approved_at",
    "plan_approved_by", "plan_history", "created_at", "updated_at", "complexity",
)
SPIRIT_SELECT = ", ".join(SPIRIT_COLUMNS)

# Expected columns for validation
EXPECTED_COLUMNS = len(SPIRIT_COLUMNS)


def _row_to_dict(row: TupleRow | tuple[Any, ...] | None) -> dict[str, Any] | None:
    """Convert a task_spirit row to a dictionary.

    Column order:
        1: task_id, 2: done_when, 3: context, 4: plan_status, 5: plan_approved_at,
        6: plan_approved_by, 7: plan_history, 8: created_at, 9: updated_at,
        10: complexity
    """
    if row is None:
        return None
    if len(row) != EXPECTED_COLUMNS:
        raise ValueError(f"Expected {EXPECTED_COLUMNS} columns for task_spirit, got {len(row)}")
    return hydrate_task_plan_fields({
        "task_id": row[0],
        "done_when": row[1] if row[1] else [],
        "context": row[2] if row[2] else {},
        "plan_status": row[3],
        "plan_approved_at": row[4].isoformat() if row[4] else None,
        "plan_approved_by": row[5],
        "plan_history": row[6] if row[6] else [],
        "created_at": row[7].isoformat() if row[7] else None,
        "updated_at": row[8].isoformat() if row[8] else None,
        "complexity": row[9],
    })
