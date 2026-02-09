"""Step summary operations - completion tracking and progress."""

from __future__ import annotations

from typing import Any

from .connection import get_connection


def get_step_summary(subtask_id: str) -> dict[str, Any]:
    """Get summary of step completion for a subtask.

    Returns:
        Dict with keys:
            - total: Total number of steps
            - completed: Number of resolved steps (passed OR plan_defect with passing fix)
            - progress_percent: Completion percentage (0-100)
    """
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT
                COUNT(*) as total,
                COUNT(*) FILTER (WHERE
                    s.passes = TRUE
                    OR (s.status = 'plan_defect' AND fix.passes = TRUE)
                ) as completed
            FROM task_subtask_steps s
            LEFT JOIN task_subtask_steps fix
                ON fix.subtask_id = s.subtask_id
                AND fix.step_number = s.fix_step_number
            WHERE s.subtask_id = %s
            """,
            (subtask_id,),
        )
        row = cur.fetchone()

    total = row[0] if row else 0
    completed = row[1] if row else 0
    progress_percent = round((completed / total * 100) if total > 0 else 0, 1)

    return {
        "total": total,
        "completed": completed,
        "progress_percent": progress_percent,
    }
