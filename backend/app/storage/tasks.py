"""Tasks storage layer - Task CRUD and execution state management.

This module provides data access for agent execution tasks.
"""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from typing import Any

from psycopg import sql
from psycopg.rows import TupleRow

from .connection import generate_prefixed_id, get_connection

# Column list for all task SELECT/RETURNING queries (33 columns)
# Order must match _row_to_dict index mapping
TASK_COLUMNS = """id, project_id, capability_id, title, description, status,
    current_criterion_id, spec_content, plan_content, progress_log,
    error_message, branch_name, commits, pull_request_url,
    total_sessions, total_tokens_used, created_at, started_at, completed_at,
    priority, labels, task_type, parent_task_id,
    claimed_by, claimed_at, lock_expires_at, tier, pre_merge_sha, review_result,
    objective, acceptance_criteria, current_phase, verification_result"""

# Aliased version for JOINs (prefixed with t.)
TASK_COLUMNS_ALIASED = """t.id, t.project_id, t.capability_id, t.title, t.description, t.status,
    t.current_criterion_id, t.spec_content, t.plan_content, t.progress_log,
    t.error_message, t.branch_name, t.commits, t.pull_request_url,
    t.total_sessions, t.total_tokens_used, t.created_at, t.started_at, t.completed_at,
    t.priority, t.labels, t.task_type, t.parent_task_id,
    t.claimed_by, t.claimed_at, t.lock_expires_at, t.tier, t.pre_merge_sha, t.review_result,
    t.objective, t.acceptance_criteria, t.current_phase, t.verification_result"""


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
    labels: list[str] | None = None,
    task_type: str = "task",
    parent_task_id: str | None = None,
    tier: int | None = None,
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
        tier: Execution tier 1-4 for autonomous execution (defaults to 2)

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
                               priority, labels, task_type, parent_task_id, tier)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
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
                tier,
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
        "project_id",  # Allow moving task between projects
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
        # Autonomous execution fields
        "claimed_by",
        "claimed_at",
        "lock_expires_at",
        "tier",
        "pre_merge_sha",
        "review_result",
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
        elif field in ("plan_content", "review_result") and isinstance(value, dict):
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
    "pending": {"running", "paused", "cancelled"},
    "running": {"paused", "failed", "completed", "pending_review", "cancelled"},
    "paused": {"running", "pending", "failed", "cancelled"},
    "failed": {"pending", "running", "cancelled"},  # Allow retry or cancel
    "completed": set(),  # Terminal - no transitions allowed
    "pending_review": {"completed", "failed", "running", "cancelled"},  # Opus review gate
    "cancelled": set(),  # Terminal - task was invalid/obsolete
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
        status: New status (pending, running, paused, failed, completed, pending_review, cancelled)
        error_message: Optional error message (for failed status)
        validate_transition: Whether to validate status transition (default True)

    Returns:
        Updated task dict or None if not found.

    Raises:
        ValueError: If invalid status or invalid transition.
    """
    valid_statuses = {
        "pending",
        "running",
        "paused",
        "failed",
        "completed",
        "pending_review",
        "cancelled",
    }
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
        # Single UPDATE with CASE expressions for conditional field updates
        cur.execute(
            f"""
            UPDATE tasks
            SET status = %s,
                started_at = CASE WHEN %s = 'running' THEN COALESCE(started_at, NOW()) ELSE started_at END,
                completed_at = CASE WHEN %s IN ('completed', 'failed', 'cancelled') THEN NOW() ELSE completed_at END,
                error_message = CASE
                    WHEN %s = 'running' THEN NULL
                    WHEN %s IN ('completed', 'failed') THEN %s
                    ELSE error_message
                END
            WHERE id = %s
            RETURNING {TASK_COLUMNS}
            """,
            (status, status, status, status, status, error_message, task_id),
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


EXPECTED_TASK_COLUMNS = 33


def _row_to_dict(row: TupleRow | tuple[Any, ...] | None) -> dict[str, Any]:
    """Convert a database row to a task dict.

    Column order: id, project_id, capability_id, title, description, status,
                  current_criterion_id, spec_content, plan_content, progress_log,
                  error_message, branch_name, commits, pull_request_url,
                  total_sessions, total_tokens_used, created_at, started_at, completed_at,
                  priority, labels, task_type, parent_task_id,
                  claimed_by, claimed_at, lock_expires_at, tier, pre_merge_sha, review_result,
                  objective, acceptance_criteria, current_phase, verification_result
    """
    if row is None:
        raise ValueError("Row cannot be None")
    if len(row) != EXPECTED_TASK_COLUMNS:
        raise ValueError(f"Expected {EXPECTED_TASK_COLUMNS} columns, got {len(row)}")
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
        # Autonomous execution fields
        "claimed_by": row[23],
        "claimed_at": row[24],
        "lock_expires_at": row[25],
        "tier": row[26],
        "pre_merge_sha": row[27],
        "review_result": row[28],
        # AI agent reliability fields
        "objective": row[29],
        "acceptance_criteria": row[30] or [],
        "current_phase": row[31],
        "verification_result": row[32],
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
            f"""
            SELECT {TASK_COLUMNS_ALIASED}
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
            f"""
            SELECT DISTINCT {TASK_COLUMNS_ALIASED}
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


def claim_task(
    task_id: str,
    worker_id: str,
    lock_duration_minutes: int = 30,
) -> dict[str, Any] | None:
    """Atomically claim a task for execution.

    Uses SELECT FOR UPDATE to prevent race conditions when multiple workers
    try to claim the same task.

    Args:
        task_id: Task ID to claim
        worker_id: Identifier for the worker claiming the task
        lock_duration_minutes: How long the claim is valid (default 30 min)

    Returns:
        Claimed task dict if successful, None if:
        - Task not found
        - Task status not claimable (not pending/paused/failed)
        - Task already claimed by another worker with valid lock
    """
    with get_connection() as conn, conn.cursor() as cur:
        # SELECT FOR UPDATE locks the row until transaction commits
        cur.execute(
            f"""
            SELECT {TASK_COLUMNS}
            FROM tasks
            WHERE id = %s
            FOR UPDATE
            """,
            (task_id,),
        )
        row = cur.fetchone()

        if not row:
            return None

        task = _row_to_dict(row)

        # Check if task is in a claimable status
        claimable_statuses = {"pending", "paused", "failed"}
        if task["status"] not in claimable_statuses:
            return None

        # Check if already claimed with valid lock
        if task["claimed_by"] and task["lock_expires_at"]:
            # Check if lock is still valid
            cur.execute("SELECT NOW()")
            now = cur.fetchone()[0]
            if task["lock_expires_at"] > now:
                # Another worker has a valid claim
                return None

        # Claim the task
        cur.execute(
            f"""
            UPDATE tasks
            SET claimed_by = %s,
                claimed_at = NOW(),
                lock_expires_at = NOW() + INTERVAL '%s minutes',
                status = 'running',
                started_at = COALESCE(started_at, NOW())
            WHERE id = %s
            RETURNING {TASK_COLUMNS}
            """,
            (worker_id, lock_duration_minutes, task_id),
        )
        row = cur.fetchone()
        conn.commit()

    if not row:
        return None
    return _row_to_dict(row)


def release_task(task_id: str) -> dict[str, Any] | None:
    """Release a claimed task back to pending status.

    Clears the claim fields and resets status to pending.

    Args:
        task_id: Task ID to release

    Returns:
        Updated task dict or None if not found.
    """
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            f"""
            UPDATE tasks
            SET claimed_by = NULL,
                claimed_at = NULL,
                lock_expires_at = NULL,
                status = 'pending'
            WHERE id = %s
            RETURNING {TASK_COLUMNS}
            """,
            (task_id,),
        )
        row = cur.fetchone()
        conn.commit()

    if not row:
        return None
    return _row_to_dict(row)


def reset_expired_claims() -> int:
    """Reset all tasks with expired claim locks.

    Finds tasks where:
    - status is 'running'
    - lock_expires_at has passed
    - claimed_by is set

    Resets them to 'pending' with cleared claim fields.

    Returns:
        Count of tasks reset.
    """
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            UPDATE tasks
            SET claimed_by = NULL,
                claimed_at = NULL,
                lock_expires_at = NULL,
                status = 'pending'
            WHERE status = 'running'
              AND lock_expires_at IS NOT NULL
              AND lock_expires_at < NOW()
              AND claimed_by IS NOT NULL
            """
        )
        count = cur.rowcount
        conn.commit()

    return count


def task_exists_for_file(project_id: str, file_path: str) -> bool:
    """Check if a task already exists that targets a specific file.

    Used for deduplication when auto-generating tasks from Explorer scans.

    Args:
        project_id: Project to check
        file_path: File path to look for in task descriptions/plan_content

    Returns:
        True if a pending/running task exists for this file
    """
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT EXISTS (
                SELECT 1 FROM tasks
                WHERE project_id = %s
                AND status IN ('pending', 'running', 'paused')
                AND (
                    -- Check description contains file path
                    description LIKE %s
                    -- Or check plan_content affected_files contains path
                    OR plan_content::text LIKE %s
                )
            )
            """,
            (project_id, f"%{file_path}%", f"%{file_path}%"),
        )
        result = cur.fetchone()
        return bool(result[0]) if result else False


def _normalize_error_pattern(error_title: str) -> tuple[str, set[str]]:
    """Extract normalized pattern and keywords from error title.

    Handles variations like:
    - "PostgreSQL connection failed due to missing role"
    - "PostgreSQL connection failed due to missing user role"
    - "Database connection failed due to missing role"

    Returns:
        Tuple of (normalized_pattern, keyword_set)
    """
    title_lower = error_title.lower().strip()

    # Common substitutions to normalize variations
    substitutions = [
        # Database variations
        (r"postgresql|postgres|pg", "database"),
        (r"database connection|db connection", "database connection"),
        # Role variations
        (r"missing (user |database |db )?role", "missing role"),
        (r"role ('\w+'|`\w+`|\w+) (does not exist|not found)", "missing role"),
        # Connection variations
        (r"connection (failed|error|refused|timeout)", "connection failed"),
        (r"authentication (failed|error)", "authentication failed"),
        # UUID/JSON variations
        (r"uuid (is not json serializable|serialization)", "uuid serialization"),
        (r"json serializ(ation|able)", "json serialization"),
        # Import variations
        (r"(module|import).*not found", "import error"),
        (r"no module named", "import error"),
    ]

    normalized = title_lower
    for pattern, replacement in substitutions:
        normalized = re.sub(pattern, replacement, normalized)

    # Extract significant keywords (3+ chars, not stop words)
    stop_words = {"the", "and", "for", "due", "with", "from", "error", "fix"}
    keywords = {word for word in re.findall(r"\b\w{3,}\b", normalized) if word not in stop_words}

    return normalized, keywords


def _calculate_keyword_overlap(keywords1: set[str], keywords2: set[str]) -> float:
    """Calculate Jaccard similarity between two keyword sets."""
    if not keywords1 or not keywords2:
        return 0.0
    intersection = len(keywords1 & keywords2)
    union = len(keywords1 | keywords2)
    return intersection / union if union > 0 else 0.0


def bug_task_exists_for_error(project_id: str, error_title: str) -> bool:
    """Check if a bug task already exists for a specific error.

    Uses semantic deduplication with pattern normalization and keyword overlap
    to catch variations like "missing user role" vs "missing database role".

    Args:
        project_id: Project to check
        error_title: Error title to look for in task titles

    Returns:
        True if a pending/running bug task exists for this error
    """
    normalized_pattern, error_keywords = _normalize_error_pattern(error_title)

    with get_connection() as conn, conn.cursor() as cur:
        # First, try exact/substring match with normalized pattern
        cur.execute(
            """
            SELECT EXISTS (
                SELECT 1 FROM tasks
                WHERE project_id = %s
                AND status IN ('pending', 'running', 'paused', 'pending_review')
                AND task_type = 'bug'
                AND (
                    LOWER(title) LIKE %s
                    OR LOWER(description) LIKE %s
                )
            )
            """,
            (project_id, f"%{normalized_pattern[:50]}%", f"%{normalized_pattern[:50]}%"),
        )
        result = cur.fetchone()
        if result and result[0]:
            return True

        # Second pass: Check for keyword overlap with existing bug tasks
        # This catches semantic duplicates that substring matching misses
        cur.execute(
            """
            SELECT title, description FROM tasks
            WHERE project_id = %s
            AND status IN ('pending', 'running', 'paused', 'pending_review')
            AND task_type = 'bug'
            """,
            (project_id,),
        )

        for row in cur.fetchall():
            existing_title = row[0] or ""
            existing_desc = row[1] or ""
            combined = f"{existing_title} {existing_desc}"

            _, existing_keywords = _normalize_error_pattern(combined)
            overlap = _calculate_keyword_overlap(error_keywords, existing_keywords)

            # If 70%+ keyword overlap, consider it a duplicate
            if overlap >= 0.7:
                return True

        return False
