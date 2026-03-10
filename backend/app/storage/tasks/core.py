"""Tasks storage - Core CRUD operations.

This module provides basic data access for task records.
"""

from __future__ import annotations

from typing import Any

from ..connection import generate_prefixed_id, get_connection
from .columns import TASK_COLUMNS, TASK_COLUMNS_WITH_SPIRIT
from .execution_mode import normalize_execution_fields
from .mapping import row_to_dict, row_to_dict_with_spirit
from .update import update_task_fields


def _generate_task_id() -> str:
    """Generate a unique task ID."""
    return generate_prefixed_id("task")


def canonicalize_task_id(task_id: str) -> str:
    """Normalize user/agent input to the canonical stored task id format."""
    raw = task_id.strip()
    if raw.startswith("task-"):
        return raw
    return f"task-{raw}"


def _fetch_task_row(task_id: str) -> Any | None:
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
        return cur.fetchone()


def _insert_task(params: tuple[Any, ...]) -> dict[str, Any]:
    """Execute INSERT for a task row and return the created dict."""
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            f"""
            INSERT INTO tasks (id, project_id, capability_id, title, description,
                               priority, task_type, parent_task_id, tier,
                               current_phase, raw_request, enrichment_status,
                               complexity, execution_mode, autonomous, labels, ai_review)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING {TASK_COLUMNS}
            """,
            params,
        )
        row = cur.fetchone()
        conn.commit()
    return row_to_dict(row)


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
    execution_mode: str | None = None,
    autonomous: bool = False,
    labels: list[str] | None = None,
    ai_review: bool = True,
) -> dict[str, Any]:
    """Create a new task and return its dict.

    Spirit fields (objective, constraints, done_when, etc.) live in task_spirit;
    use storage.task_spirit functions. Verification is at step level (storage.steps).
    """
    task_id = _generate_task_id() if task_id is None else canonicalize_task_id(task_id)
    execution_fields = normalize_execution_fields(
        task_type=task_type,
        execution_mode=execution_mode,
        autonomous=autonomous,
    )
    params = (
        task_id, project_id, capability_id, title, description,
        priority, task_type, parent_task_id, tier,
        current_phase, raw_request, enrichment_status,
        complexity, execution_fields["execution_mode"], execution_fields["autonomous"],
        labels or [], ai_review,
    )
    return _insert_task(params)


def get_task(task_id: str) -> dict[str, Any] | None:
    """Get a task by ID with spirit fields, or None if not found."""
    canonical_task_id = canonicalize_task_id(task_id)
    row = _fetch_task_row(task_id) if canonical_task_id != task_id else None
    if row is None:
        row = _fetch_task_row(canonical_task_id)
    if not row:
        return None
    return row_to_dict_with_spirit(row)


def update_task(task_id: str, **fields: Any) -> dict[str, Any] | None:
    """Update task fields. Returns updated dict or None if not found.

    Raises:
        ValueError: If no fields provided or invalid field name.
    """
    resolved_task_id = canonicalize_task_id(task_id)
    if "execution_mode" in fields or "autonomous" in fields or "task_type" in fields:
        existing = get_task(resolved_task_id)
        if existing is None:
            return None
        execution_fields = normalize_execution_fields(
            task_type=str(fields.get("task_type", existing.get("task_type", "task"))),
            execution_mode=fields.get("execution_mode", existing.get("execution_mode")),
            autonomous=fields.get("autonomous", existing.get("autonomous")),
        )
        fields["execution_mode"] = execution_fields["execution_mode"]
        fields["autonomous"] = execution_fields["autonomous"]
    return update_task_fields(resolved_task_id, **fields)


def delete_task(task_id: str) -> bool:
    """Delete a task. Returns True if deleted, False if not found."""
    resolved_task_id = canonicalize_task_id(task_id)
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            "DELETE FROM tasks WHERE id = %s RETURNING id",
            (resolved_task_id,),
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
    "canonicalize_task_id",
    "create_task",
    "delete_task",
    "get_agent_hub_sessions",
    "get_task",
    "update_task",
]
