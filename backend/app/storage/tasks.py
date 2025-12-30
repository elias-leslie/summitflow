"""Tasks storage layer - Task CRUD and execution state management.

This module provides data access for agent execution tasks.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from typing import Any

from psycopg import sql
from psycopg.rows import TupleRow

from .connection import get_connection

# Column list for all task SELECT/RETURNING queries (23 columns)
# Order must match _row_to_dict index mapping
TASK_COLUMNS = """id, project_id, capability_id, title, description, status,
    current_criterion_id, spec_content, plan_content, progress_log,
    error_message, branch_name, commits, pull_request_url,
    total_sessions, total_tokens_used, created_at, started_at, completed_at,
    priority, labels, task_type, parent_task_id"""

# Aliased version for JOINs (prefixed with t.)
TASK_COLUMNS_ALIASED = """t.id, t.project_id, t.capability_id, t.title, t.description, t.status,
    t.current_criterion_id, t.spec_content, t.plan_content, t.progress_log,
    t.error_message, t.branch_name, t.commits, t.pull_request_url,
    t.total_sessions, t.total_tokens_used, t.created_at, t.started_at, t.completed_at,
    t.priority, t.labels, t.task_type, t.parent_task_id"""


def _generate_task_id() -> str:
    """Generate a unique task ID."""
    short_uuid = str(uuid.uuid4())[:8]
    return f"task-{short_uuid}"


def create_task(
    project_id: str,
    title: str,
    capability_id: int | None = None,
    description: str | None = None,
    task_id: str | None = None,
    priority: int = 2,
    labels: list[str] | None = None,
    task_type: str = "task",
    parent_task_id: str | None = None,
) -> dict[str, Any]:
    """Create a new task.

    Args:
        project_id: Project ID
        title: Task title
        capability_id: Optional capability database ID to link to (TDD)
        description: Optional task description
        task_id: Optional custom task ID (auto-generated if not provided)
        priority: Priority 0-4 (0=critical, 4=backlog), default 2
        labels: List of labels (complexity:small, domains:backend, etc.)
        task_type: Type: 'task', 'bug', 'chore'
        parent_task_id: Parent task ID for subtasks

    Returns:
        The created task dict with all columns.
    """
    if task_id is None:
        task_id = _generate_task_id()
    if labels is None:
        labels = []

    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            f"""
            INSERT INTO tasks (id, project_id, capability_id, title, description,
                               priority, labels, task_type, parent_task_id)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING {TASK_COLUMNS}
            """,
            (
                task_id,
                project_id,
                capability_id,
                title,
                description,
                priority,
                labels,
                task_type,
                parent_task_id,
            ),
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
            f"""
            SELECT {TASK_COLUMNS}
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
        # Issue tracking fields
        "priority",
        "labels",
        "task_type",
        "parent_task_id",
        # TDD linkage
        "capability_id",
    }

    invalid = set(fields.keys()) - allowed_fields
    if invalid:
        raise ValueError(f"Invalid fields: {invalid}")

    set_clauses: list[sql.Composable] = []
    params: list[Any] = []
    for field, value in fields.items():
        if field in ("commits", "labels") and isinstance(value, list):
            set_clauses.append(sql.SQL("{} = %s").format(sql.Identifier(field)))
            params.append(value)
        elif field == "plan_content" and isinstance(value, dict):
            set_clauses.append(sql.SQL("{} = %s::jsonb").format(sql.Identifier(field)))
            params.append(json.dumps(value))
        else:
            set_clauses.append(sql.SQL("{} = %s").format(sql.Identifier(field)))
            params.append(value)

    params.append(task_id)

    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            sql.SQL(f"""
            UPDATE tasks
            SET {{set_clause}}
            WHERE id = %s
            RETURNING {TASK_COLUMNS}
            """).format(set_clause=sql.SQL(", ").join(set_clauses)),
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
    task_type_filter: str | None = None,
    priority_filter: int | None = None,
    labels_filter: list[str] | None = None,
    orphans_only: bool = False,
    limit: int = 50,
    offset: int = 0,
) -> list[dict[str, Any]]:
    """List tasks for a project.

    Args:
        project_id: Project ID
        status_filter: Optional status filter (pending, running, paused, failed, completed)
        task_type_filter: Optional type filter (task, bug, feature)
        priority_filter: Optional priority filter (0-4)
        labels_filter: Optional labels filter (task must have ALL specified labels)
        orphans_only: Only return tasks not linked to a capability
        limit: Max results (default 50)
        offset: Result offset

    Returns:
        List of task dicts.
    """
    conditions = ["t.project_id = %s"]
    params: list[Any] = [project_id]

    if status_filter:
        conditions.append("t.status = %s")
        params.append(status_filter)
    if task_type_filter:
        conditions.append("t.task_type = %s")
        params.append(task_type_filter)
    if priority_filter is not None:
        conditions.append("t.priority = %s")
        params.append(priority_filter)
    if labels_filter:
        # Task must contain all specified labels
        conditions.append("t.labels @> %s")
        params.append(labels_filter)
    if orphans_only:
        conditions.append("t.capability_id IS NULL")

    params.extend([limit, offset])

    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            sql.SQL(f"""
            SELECT {TASK_COLUMNS_ALIASED}
            FROM tasks t
            WHERE {{conditions}}
            ORDER BY t.priority ASC, t.created_at DESC
            LIMIT %s OFFSET %s
            """).format(conditions=sql.SQL(" AND ").join(sql.SQL(c) for c in conditions)),
            tuple(params),
        )
        rows = cur.fetchall()

    return [_row_to_dict(row) for row in rows]


def get_tasks_by_capability(capability_id: int) -> list[dict[str, Any]]:
    """Get all tasks linked to a capability.

    Args:
        capability_id: Capability database ID

    Returns:
        List of task dicts.
    """
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT {TASK_COLUMNS}
            FROM tasks
            WHERE capability_id = %s
            ORDER BY created_at DESC
            """,
            (capability_id,),
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
                f"""
                UPDATE tasks
                SET status = %s, started_at = COALESCE(started_at, NOW()), error_message = NULL
                WHERE id = %s
                RETURNING {TASK_COLUMNS}
                """,
                (status, task_id),
            )
        elif status in ("completed", "failed"):
            cur.execute(
                f"""
                UPDATE tasks
                SET status = %s, completed_at = NOW(), error_message = %s
                WHERE id = %s
                RETURNING {TASK_COLUMNS}
                """,
                (status, error_message, task_id),
            )
        else:
            cur.execute(
                f"""
                UPDATE tasks
                SET status = %s
                WHERE id = %s
                RETURNING {TASK_COLUMNS}
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
            f"""
            UPDATE tasks
            SET progress_log = COALESCE(progress_log, '') || %s
            WHERE id = %s
            RETURNING {TASK_COLUMNS}
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
            f"""
            UPDATE tasks
            SET commits = array_append(commits, %s)
            WHERE id = %s
            RETURNING {TASK_COLUMNS}
            """,
            (commit_sha, task_id),
        )
        row = cur.fetchone()
        conn.commit()

    if not row:
        return None
    return _row_to_dict(row)


def _row_to_dict(row: TupleRow | tuple[Any, ...] | None) -> dict[str, Any]:
    """Convert a database row to a task dict.

    Column order: id, project_id, capability_id, title, description, status,
                  current_criterion_id, spec_content, plan_content, progress_log,
                  error_message, branch_name, commits, pull_request_url,
                  total_sessions, total_tokens_used, created_at, started_at, completed_at,
                  priority, labels, task_type, parent_task_id
    """
    if row is None:
        raise ValueError("Row cannot be None")
    return {
        "id": row[0],
        "project_id": row[1],
        "capability_id": row[2],
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
        # Issue tracking fields
        "priority": row[19],
        "labels": row[20] or [],
        "task_type": row[21],
        "parent_task_id": row[22],
    }


def list_ready_tasks(project_id: str, limit: int = 50) -> list[dict[str, Any]]:
    """List tasks that are not blocked by dependencies.

    A task is "ready" if:
    - Status is 'pending' (not started)
    - Has no incomplete blocking dependencies

    Args:
        project_id: Project ID
        limit: Max results (default 50)

    Returns:
        List of ready task dicts, ordered by priority then creation date.
    """
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT t.id, t.project_id, t.capability_id, t.title, t.description, t.status,
                   t.current_criterion_id, t.spec_content, t.plan_content, t.progress_log,
                   t.error_message, t.branch_name, t.commits, t.pull_request_url,
                   t.total_sessions, t.total_tokens_used, t.created_at, t.started_at, t.completed_at,
                   t.priority, t.labels, t.task_type, t.parent_task_id
            FROM tasks t
            WHERE t.project_id = %s
              AND t.status = 'pending'
              AND NOT EXISTS (
                  SELECT 1 FROM task_dependencies d
                  JOIN tasks blocker ON d.depends_on_task_id = blocker.id
                  WHERE d.task_id = t.id
                    AND d.dependency_type = 'blocks'
                    AND blocker.status NOT IN ('completed')
              )
            ORDER BY t.priority ASC, t.created_at ASC
            LIMIT %s
            """,
            (project_id, limit),
        )
        rows = cur.fetchall()

    return [_row_to_dict(row) for row in rows]


def list_blocked_tasks(project_id: str, limit: int = 50) -> list[dict[str, Any]]:
    """List tasks that are blocked by incomplete dependencies.

    Args:
        project_id: Project ID
        limit: Max results (default 50)

    Returns:
        List of blocked task dicts with blocking_tasks field added.
    """
    with get_connection() as conn, conn.cursor() as cur:
        # Get blocked tasks
        cur.execute(
            """
            SELECT DISTINCT t.id, t.project_id, t.capability_id, t.title, t.description, t.status,
                   t.current_criterion_id, t.spec_content, t.plan_content, t.progress_log,
                   t.error_message, t.branch_name, t.commits, t.pull_request_url,
                   t.total_sessions, t.total_tokens_used, t.created_at, t.started_at, t.completed_at,
                   t.priority, t.labels, t.task_type, t.parent_task_id
            FROM tasks t
            WHERE t.project_id = %s
              AND t.status = 'pending'
              AND EXISTS (
                  SELECT 1 FROM task_dependencies d
                  JOIN tasks blocker ON d.depends_on_task_id = blocker.id
                  WHERE d.task_id = t.id
                    AND d.dependency_type = 'blocks'
                    AND blocker.status NOT IN ('completed')
              )
            ORDER BY t.priority ASC, t.created_at ASC
            LIMIT %s
            """,
            (project_id, limit),
        )
        rows = cur.fetchall()

    return [_row_to_dict(row) for row in rows]
