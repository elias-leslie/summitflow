"""Tasks storage - Core CRUD operations.

This module provides basic data access for task records.
"""

from __future__ import annotations

from typing import Any

from ..connection import generate_prefixed_id, get_connection
from .columns import TASK_COLUMNS, TASK_COLUMNS_WITH_SPIRIT
from .mapping import row_to_dict, row_to_dict_with_spirit
from .update import update_task_fields


def _generate_task_id() -> str:
    """Generate a unique task ID."""
    return generate_prefixed_id("task")


def create_task(
    project_id: str,
    title: str,
    capability_id: int | None = None,
    description: str | None = None,
    task_id: str | None = None,
    priority: int = 2,
    task_type: str = "task",
    parent_task_id: str | None = None,
    tier: int | None = None,
    current_phase: str = "plan",
    raw_request: str | None = None,
    enrichment_status: str = "none",
    complexity: str | None = None,
    autonomous: bool = False,
    labels: list[str] | None = None,
) -> dict[str, Any]:
    """Create a new task.

    Args:
        project_id: Project ID
        title: Task title
        capability_id: Optional capability database ID to link to (TDD)
        description: Optional task description
        task_id: Optional custom task ID (auto-generated if not provided)
        priority: Priority 0-4 (0=critical, 4=backlog), default 2
        task_type: Type: 'task', 'bug', 'chore'
        parent_task_id: Parent task ID for subtasks
        tier: Execution tier 1-4 for autonomous execution (defaults to 2)
        current_phase: Task phase: plan, implement, test, verify, complete
        raw_request: Original user input before AI enrichment
        enrichment_status: Enrichment state: none, draft, enriching, review, discussing, accepted, failed
        complexity: Task complexity tier (SIMPLE, STANDARD, COMPLEX)
        autonomous: Enable autonomous execution (Flash/Opus pipeline)
        labels: Optional list of labels (e.g. ["crowdsourced", "domains:backend"])

    Note:
        - objective, spirit_anti, decisions, constraints, done_when are stored
          in task_spirit table. Use storage.task_spirit functions.
        - Verification happens at step level via verify_command. See storage.steps.

    Returns:
        The created task dict with all columns.
    """
    if task_id is None:
        task_id = _generate_task_id()
    # Auto-enable autonomous for mechanical task types (opt-in by default)
    if not autonomous and task_type in ("refactor", "debt", "regression"):
        autonomous = True

    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            f"""
            INSERT INTO tasks (id, project_id, capability_id, title, description,
                               priority, task_type, parent_task_id, tier,
                               current_phase, raw_request, enrichment_status,
                               complexity, autonomous, labels)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING {TASK_COLUMNS}
            """,
            (
                task_id,
                project_id,
                capability_id,
                title,
                description,
                priority,
                task_type,
                parent_task_id,
                tier,
                current_phase,
                raw_request,
                enrichment_status,
                complexity,
                autonomous,
                labels or [],
            ),
        )
        row = cur.fetchone()
        conn.commit()

    return row_to_dict(row)


def get_task(task_id: str) -> dict[str, Any] | None:
    """Get a task by ID with spirit fields.

    Returns:
        Task dict with spirit fields (objective, spirit_anti, decisions,
        constraints, done_when, plan_status) or None if not found.
    """
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT {TASK_COLUMNS_WITH_SPIRIT}
            FROM tasks t
            LEFT JOIN task_spirit ts ON t.id = ts.task_id
            WHERE t.id = %s
            """,
            (task_id,),
        )
        row = cur.fetchone()

    if not row:
        return None
    return row_to_dict_with_spirit(row)


def update_task(task_id: str, **fields: Any) -> dict[str, Any] | None:
    """Update task fields.

    Args:
        task_id: Task ID
        **fields: Fields to update (e.g., title='New title', description='...')

    Returns:
        Updated task dict or None if not found.

    Raises:
        ValueError: If no fields provided or invalid field name.
    """
    return update_task_fields(task_id, **fields)


def delete_task(task_id: str) -> bool:
    """Delete a task.

    Returns:
        True if deleted, False if not found.
    """
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            "DELETE FROM tasks WHERE id = %s RETURNING id",
            (task_id,),
        )
        result = cur.fetchone()
        conn.commit()

    return result is not None


# Re-export for backwards compatibility
from .columns import (  # noqa: E402
    EXPECTED_TASK_COLUMNS,
    EXPECTED_TASK_COLUMNS_WITH_SPIRIT,
    TASK_COLUMNS_ALIASED,
)
from .sessions import add_agent_hub_session, get_agent_hub_sessions  # noqa: E402

# Private functions re-exported for package use
_row_to_dict = row_to_dict
_row_to_dict_with_spirit = row_to_dict_with_spirit

__all__ = [
    "EXPECTED_TASK_COLUMNS",
    "EXPECTED_TASK_COLUMNS_WITH_SPIRIT",
    "TASK_COLUMNS",
    "TASK_COLUMNS_ALIASED",
    "TASK_COLUMNS_WITH_SPIRIT",
    "_row_to_dict",
    "_row_to_dict_with_spirit",
    "add_agent_hub_session",
    "create_task",
    "delete_task",
    "get_agent_hub_sessions",
    "get_task",
    "update_task",
]
