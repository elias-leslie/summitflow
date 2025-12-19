"""Tasks storage layer - Task CRUD and execution state management.

This module provides data access for agent execution tasks.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from typing import Any

from .connection import get_connection


def _generate_task_id() -> str:
    """Generate a unique task ID."""
    short_uuid = str(uuid.uuid4())[:8]
    return f"task-{short_uuid}"


def create_task(
    project_id: str,
    title: str,
    feature_id: int | None = None,
    description: str | None = None,
    task_id: str | None = None,
) -> dict[str, Any]:
    """Create a new task.

    Args:
        project_id: Project ID
        title: Task title
        feature_id: Optional feature database ID to link to
        description: Optional task description
        task_id: Optional custom task ID (auto-generated if not provided)

    Returns:
        The created task dict with all columns.
    """
    if task_id is None:
        task_id = _generate_task_id()

    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO tasks (id, project_id, feature_id, title, description)
            VALUES (%s, %s, %s, %s, %s)
            RETURNING id, project_id, feature_id, title, description, status,
                      current_criterion_id, spec_content, plan_content, progress_log,
                      error_message, branch_name, commits, pull_request_url,
                      total_sessions, total_tokens_used, created_at, started_at, completed_at
            """,
            (task_id, project_id, feature_id, title, description),
        )
        row = cur.fetchone()
        conn.commit()

    return _row_to_dict(row)


def get_task(task_id: str) -> dict[str, Any] | None:
    """Get a task by ID.

    Returns:
        Task dict or None if not found.
    """
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, project_id, feature_id, title, description, status,
                   current_criterion_id, spec_content, plan_content, progress_log,
                   error_message, branch_name, commits, pull_request_url,
                   total_sessions, total_tokens_used, created_at, started_at, completed_at
            FROM tasks
            WHERE id = %s
            """,
            (task_id,),
        )
        row = cur.fetchone()

    if not row:
        return None
    return _row_to_dict(row)


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
    if not fields:
        raise ValueError("No fields provided to update")

    allowed_fields = {
        "title",
        "description",
        "status",
        "current_criterion_id",
        "spec_content",
        "plan_content",
        "progress_log",
        "error_message",
        "branch_name",
        "commits",
        "pull_request_url",
        "total_sessions",
        "total_tokens_used",
        "started_at",
        "completed_at",
    }

    invalid = set(fields.keys()) - allowed_fields
    if invalid:
        raise ValueError(f"Invalid fields: {invalid}")

    set_clauses = []
    params = []
    for field, value in fields.items():
        if field == "commits" and isinstance(value, list):
            set_clauses.append(f"{field} = %s")
            params.append(value)
        elif field == "plan_content" and isinstance(value, dict):
            set_clauses.append(f"{field} = %s::jsonb")
            params.append(json.dumps(value))
        else:
            set_clauses.append(f"{field} = %s")
            params.append(value)

    params.append(task_id)

    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            f"""
            UPDATE tasks
            SET {", ".join(set_clauses)}
            WHERE id = %s
            RETURNING id, project_id, feature_id, title, description, status,
                      current_criterion_id, spec_content, plan_content, progress_log,
                      error_message, branch_name, commits, pull_request_url,
                      total_sessions, total_tokens_used, created_at, started_at, completed_at
            """,
            tuple(params),
        )
        row = cur.fetchone()
        conn.commit()

    if not row:
        return None
    return _row_to_dict(row)


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


def list_tasks(
    project_id: str,
    status_filter: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[dict[str, Any]]:
    """List tasks for a project.

    Args:
        project_id: Project ID
        status_filter: Optional status filter (pending, running, paused, failed, completed)
        limit: Max results (default 50)
        offset: Result offset

    Returns:
        List of task dicts.
    """
    with get_connection() as conn, conn.cursor() as cur:
        if status_filter:
            cur.execute(
                """
                SELECT id, project_id, feature_id, title, description, status,
                       current_criterion_id, spec_content, plan_content, progress_log,
                       error_message, branch_name, commits, pull_request_url,
                       total_sessions, total_tokens_used, created_at, started_at, completed_at
                FROM tasks
                WHERE project_id = %s AND status = %s
                ORDER BY created_at DESC
                LIMIT %s OFFSET %s
                """,
                (project_id, status_filter, limit, offset),
            )
        else:
            cur.execute(
                """
                SELECT id, project_id, feature_id, title, description, status,
                       current_criterion_id, spec_content, plan_content, progress_log,
                       error_message, branch_name, commits, pull_request_url,
                       total_sessions, total_tokens_used, created_at, started_at, completed_at
                FROM tasks
                WHERE project_id = %s
                ORDER BY created_at DESC
                LIMIT %s OFFSET %s
                """,
                (project_id, limit, offset),
            )
        rows = cur.fetchall()

    return [_row_to_dict(row) for row in rows]


def get_tasks_by_feature(feature_id: int) -> list[dict[str, Any]]:
    """Get all tasks linked to a feature.

    Args:
        feature_id: Feature database ID (not feature_id string)

    Returns:
        List of task dicts.
    """
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, project_id, feature_id, title, description, status,
                   current_criterion_id, spec_content, plan_content, progress_log,
                   error_message, branch_name, commits, pull_request_url,
                   total_sessions, total_tokens_used, created_at, started_at, completed_at
            FROM tasks
            WHERE feature_id = %s
            ORDER BY created_at DESC
            """,
            (feature_id,),
        )
        rows = cur.fetchall()

    return [_row_to_dict(row) for row in rows]


# Valid task status transitions
VALID_TRANSITIONS: dict[str, set[str]] = {
    "pending": {"running", "paused"},
    "running": {"paused", "failed", "completed"},
    "paused": {"running", "pending", "failed"},
    "failed": {"pending", "running"},  # Allow retry
    "completed": set(),  # Terminal - no transitions allowed
}


def validate_status_transition(current: str, target: str) -> bool:
    """Check if a status transition is valid.

    Args:
        current: Current task status
        target: Target task status

    Returns:
        True if transition is valid
    """
    return target in VALID_TRANSITIONS.get(current, set())


def update_task_status(
    task_id: str,
    status: str,
    error_message: str | None = None,
    validate_transition: bool = True,
) -> dict[str, Any] | None:
    """Update task status with timestamp handling and transition validation.

    Args:
        task_id: Task ID
        status: New status (pending, running, paused, failed, completed)
        error_message: Optional error message (for failed status)
        validate_transition: Whether to validate status transition (default True)

    Returns:
        Updated task dict or None if not found.

    Raises:
        ValueError: If invalid status or invalid transition.
    """
    valid_statuses = {"pending", "running", "paused", "failed", "completed"}
    if status not in valid_statuses:
        raise ValueError(f"Invalid status '{status}'. Must be one of: {valid_statuses}")

    # Get current status if validating transitions
    if validate_transition:
        current_task = get_task(task_id)
        if current_task:
            current_status = current_task["status"]
            if current_status != status and not validate_status_transition(current_status, status):
                raise ValueError(
                    f"Invalid transition from '{current_status}' to '{status}'. "
                    f"Valid transitions: {VALID_TRANSITIONS.get(current_status, set())}"
                )

    with get_connection() as conn, conn.cursor() as cur:
        # Build update based on status
        if status == "running":
            cur.execute(
                """
                UPDATE tasks
                SET status = %s, started_at = COALESCE(started_at, NOW()), error_message = NULL
                WHERE id = %s
                RETURNING id, project_id, feature_id, title, description, status,
                          current_criterion_id, spec_content, plan_content, progress_log,
                          error_message, branch_name, commits, pull_request_url,
                          total_sessions, total_tokens_used, created_at, started_at, completed_at
                """,
                (status, task_id),
            )
        elif status in ("completed", "failed"):
            cur.execute(
                """
                UPDATE tasks
                SET status = %s, completed_at = NOW(), error_message = %s
                WHERE id = %s
                RETURNING id, project_id, feature_id, title, description, status,
                          current_criterion_id, spec_content, plan_content, progress_log,
                          error_message, branch_name, commits, pull_request_url,
                          total_sessions, total_tokens_used, created_at, started_at, completed_at
                """,
                (status, error_message, task_id),
            )
        else:
            cur.execute(
                """
                UPDATE tasks
                SET status = %s
                WHERE id = %s
                RETURNING id, project_id, feature_id, title, description, status,
                          current_criterion_id, spec_content, plan_content, progress_log,
                          error_message, branch_name, commits, pull_request_url,
                          total_sessions, total_tokens_used, created_at, started_at, completed_at
                """,
                (status, task_id),
            )

        row = cur.fetchone()
        conn.commit()

    if not row:
        return None
    return _row_to_dict(row)


def append_progress_log(task_id: str, entry: str) -> dict[str, Any] | None:
    """Append an entry to the task's progress log.

    Args:
        task_id: Task ID
        entry: Log entry to append (timestamp is auto-added)

    Returns:
        Updated task dict or None if not found.
    """
    timestamp = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S")
    log_entry = f"[{timestamp}] {entry}\n"

    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            UPDATE tasks
            SET progress_log = COALESCE(progress_log, '') || %s
            WHERE id = %s
            RETURNING id, project_id, feature_id, title, description, status,
                      current_criterion_id, spec_content, plan_content, progress_log,
                      error_message, branch_name, commits, pull_request_url,
                      total_sessions, total_tokens_used, created_at, started_at, completed_at
            """,
            (log_entry, task_id),
        )
        row = cur.fetchone()
        conn.commit()

    if not row:
        return None
    return _row_to_dict(row)


def add_commit(task_id: str, commit_sha: str) -> dict[str, Any] | None:
    """Add a commit SHA to the task's commits array.

    Args:
        task_id: Task ID
        commit_sha: Git commit SHA to add

    Returns:
        Updated task dict or None if not found.
    """
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            UPDATE tasks
            SET commits = array_append(commits, %s)
            WHERE id = %s
            RETURNING id, project_id, feature_id, title, description, status,
                      current_criterion_id, spec_content, plan_content, progress_log,
                      error_message, branch_name, commits, pull_request_url,
                      total_sessions, total_tokens_used, created_at, started_at, completed_at
            """,
            (commit_sha, task_id),
        )
        row = cur.fetchone()
        conn.commit()

    if not row:
        return None
    return _row_to_dict(row)


def _row_to_dict(row: tuple) -> dict[str, Any]:
    """Convert a database row to a task dict."""
    return {
        "id": row[0],
        "project_id": row[1],
        "feature_id": row[2],
        "title": row[3],
        "description": row[4],
        "status": row[5],
        "current_criterion_id": row[6],
        "spec_content": row[7],
        "plan_content": row[8],
        "progress_log": row[9],
        "error_message": row[10],
        "branch_name": row[11],
        "commits": row[12] or [],
        "pull_request_url": row[13],
        "total_sessions": row[14],
        "total_tokens_used": row[15],
        "created_at": row[16],
        "started_at": row[17],
        "completed_at": row[18],
    }
