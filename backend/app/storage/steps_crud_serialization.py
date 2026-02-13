"""Serialization utilities for step database rows."""

from __future__ import annotations

from typing import Any

from psycopg.rows import TupleRow

# Column list for all step SELECT/RETURNING queries (11 columns)
STEP_COLUMNS = """id, subtask_id, step_number, description, spec, passes, passed_at, created_at, verify_command, status, fix_step_number"""

# Expected column count for row validation
EXPECTED_STEP_COLUMNS = 11


def row_to_dict(row: TupleRow | tuple[Any, ...] | None) -> dict[str, Any]:
    """Convert a database row to a step dict.

    Column order (11 columns):
        id, subtask_id, step_number, description, spec, passes, passed_at, created_at,
        verify_command, status, fix_step_number
    """
    if row is None:
        raise ValueError("Row cannot be None")
    if len(row) != EXPECTED_STEP_COLUMNS:
        raise ValueError(f"Expected {EXPECTED_STEP_COLUMNS} columns, got {len(row)}")

    # Import here to avoid circular dependency
    from .steps_constants import STEP_STATUS_PENDING

    return {
        "id": row[0],
        "subtask_id": row[1],
        "step_number": row[2],
        "description": row[3],
        "spec": row[4],
        "passes": row[5],
        "passed_at": row[6].isoformat() if row[6] else None,
        "created_at": row[7].isoformat() if row[7] else None,
        "verify_command": row[8],
        "status": row[9] or STEP_STATUS_PENDING,
        "fix_step_number": row[10],
    }
