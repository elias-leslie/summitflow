"""Subtask helpers - utility functions for subtask operations.

This module provides helper functions for ID generation, row conversion,
and column definitions used across subtask CRUD operations.
"""

from __future__ import annotations

from typing import Any

from psycopg.rows import TupleRow

# Column list for all subtask SELECT/RETURNING queries (11 columns)
SUBTASK_COLUMNS = """id, task_id, subtask_id, phase, description,
    passes, passed_at, display_order, created_at, citations_acknowledged_at,
    subtask_type"""

# Expected column count for row validation
EXPECTED_SUBTASK_COLUMNS = 11


def generate_subtask_id(task_id: str, subtask_id: str) -> str:
    """Generate a unique subtask table ID.

    Format: {task_id}-{subtask_id} e.g., "task-abc123-1.1"
    """
    return f"{task_id}-{subtask_id}"


def row_to_dict(row: TupleRow | tuple[Any, ...] | None) -> dict[str, Any]:
    """Convert a database row to a subtask dict.

    Column order (10 columns):
        id, task_id, subtask_id, phase, description,
        passes, passed_at, display_order, created_at, citations_acknowledged_at

    Note: steps field is always [] - steps are in task_subtask_steps table
    """
    if row is None:
        raise ValueError("Row cannot be None")
    if len(row) != EXPECTED_SUBTASK_COLUMNS:
        raise ValueError(f"Expected {EXPECTED_SUBTASK_COLUMNS} columns, got {len(row)}")
    return {
        "id": row[0],
        "task_id": row[1],
        "subtask_id": row[2],
        "phase": row[3],
        "description": row[4],
        # Note: "steps" field is populated separately when include_steps=True
        "passes": row[5],
        "passed_at": row[6].isoformat() if row[6] else None,
        "display_order": row[7],
        "created_at": row[8].isoformat() if row[8] else None,
        "citations_acknowledged_at": row[9].isoformat() if row[9] else None,
        "subtask_type": row[10],
    }
