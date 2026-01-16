"""Subtasks storage layer - CRUD operations for task implementation subtasks.

This module provides data access for the task_subtasks table, which stores
normalized subtask data for structured task execution tracking.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from psycopg.rows import TupleRow

from .connection import get_connection
from .steps import bulk_create_steps

logger = logging.getLogger(__name__)

# Column list for all subtask SELECT/RETURNING queries (10 columns)
# Note: steps column was dropped in migration 045 - steps are in task_subtask_steps table
# Note: details column added in migration 061 - stores rich implementation specs
SUBTASK_COLUMNS = """id, task_id, subtask_id, phase, description,
    details, passes, passed_at, display_order, created_at"""

# Expected column count for row validation
EXPECTED_SUBTASK_COLUMNS = 10


def _generate_subtask_id(task_id: str, subtask_id: str) -> str:
    """Generate a unique subtask table ID.

    Format: {task_id}-{subtask_id} e.g., "task-abc123-1.1"
    """
    return f"{task_id}-{subtask_id}"


def _row_to_dict(row: TupleRow | tuple[Any, ...] | None) -> dict[str, Any]:
    """Convert a database row to a subtask dict.

    Column order (10 columns):
        id, task_id, subtask_id, phase, description,
        details, passes, passed_at, display_order, created_at

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
        "details": row[5],  # Rich implementation spec from plan.json
        # Note: "steps" field is populated separately when include_steps=True
        "passes": row[6],
        "passed_at": row[7].isoformat() if row[7] else None,
        "display_order": row[8],
        "created_at": row[9].isoformat() if row[9] else None,
    }


def create_subtask(
    task_id: str,
    subtask_id: str,
    description: str,
    display_order: int,
    phase: str | None = None,
    steps: list[str | dict[str, Any]] | None = None,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Create a new subtask.

    Also creates step rows in task_subtask_steps table when steps are provided.
    The JSONB steps column is not used (deprecated).

    Args:
        task_id: Parent task ID (must exist in tasks table)
        subtask_id: Hierarchical ID like "1.1", "2.3"
        description: Subtask description
        display_order: Order for display (0-indexed)
        phase: Optional phase: research, database, backend, frontend, testing
        steps: Optional list of steps - strings or {description, spec} dicts
        details: Optional rich implementation spec from plan.json (deprecated)

    Returns:
        The created subtask dict.

    Raises:
        Exception: If task_id doesn't exist (FK constraint violation)
    """
    import json

    if steps is None:
        steps = []

    table_id = _generate_subtask_id(task_id, subtask_id)
    details_json = json.dumps(details) if details else None

    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            f"""
            INSERT INTO task_subtasks (id, task_id, subtask_id, phase, description,
                                       details, display_order)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            RETURNING {SUBTASK_COLUMNS}
            """,
            (
                table_id,
                task_id,
                subtask_id,
                phase,
                description,
                details_json,
                display_order,
            ),
        )
        row = cur.fetchone()
        conn.commit()

    result = _row_to_dict(row)

    # Create steps in normalized table
    if steps:
        try:
            created_steps = bulk_create_steps(table_id, steps)
            result["steps"] = created_steps
        except Exception as e:
            logger.error("Failed to create steps for subtask %s: %s", table_id, e)
            # Continue - subtask created, steps failed (partial success)

    logger.debug("Created subtask %s for task %s", subtask_id, task_id)
    return result


def get_subtask(task_id: str, subtask_id: str) -> dict[str, Any] | None:
    """Get a single subtask by task_id and subtask_id.

    Returns:
        Subtask dict or None if not found.
    """
    table_id = _generate_subtask_id(task_id, subtask_id)

    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT {SUBTASK_COLUMNS}
            FROM task_subtasks
            WHERE id = %s
            """,
            (table_id,),
        )
        row = cur.fetchone()

    if not row:
        return None
    return _row_to_dict(row)


def get_subtasks_for_task(
    task_id: str,
    include_steps: bool = False,
) -> list[dict[str, Any]]:
    """Get all subtasks for a task, ordered by display_order.

    Args:
        task_id: Parent task ID
        include_steps: If True, include steps from task_subtask_steps table

    Returns:
        List of subtask dicts, ordered by display_order.
    """
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT {SUBTASK_COLUMNS}
            FROM task_subtasks
            WHERE task_id = %s
            ORDER BY display_order
            """,
            (task_id,),
        )
        rows = cur.fetchall()

    subtasks = [_row_to_dict(row) for row in rows]

    if include_steps:
        from .steps import get_step_summary, get_steps_for_subtask

        for subtask in subtasks:
            subtask_table_id = subtask["id"]  # Already in table ID format
            subtask["steps_from_table"] = get_steps_for_subtask(subtask_table_id)
            subtask["step_summary"] = get_step_summary(subtask_table_id)

    return subtasks


class SubtaskGateError(Exception):
    """Raised when subtask completion gate is violated."""

    def __init__(self, message: str, incomplete_steps: list[int] | None = None):
        super().__init__(message)
        self.incomplete_steps = incomplete_steps or []


class SubtaskVerificationError(Exception):
    """Raised when subtask completion is blocked by failed verification.

    Attributes:
        criterion_id: The criterion that failed verification
        output: The verification command output
        attempts: Current attempt count
        escalation_level: Current escalation level (WORKER, SUPERVISOR, HUMAN)
    """

    def __init__(
        self,
        message: str,
        criterion_id: str,
        output: str,
        attempts: int,
        escalation_level: str,
    ):
        super().__init__(message)
        self.criterion_id = criterion_id
        self.output = output
        self.attempts = attempts
        self.escalation_level = escalation_level


def _run_linked_verifications_for_subtask(subtask_table_id: str, task_id: str) -> dict[str, Any]:
    """Run verifications for all criteria linked to a subtask.

    Args:
        subtask_table_id: The subtask table ID (e.g., "task-abc123-1.1")
        task_id: The parent task ID (e.g., "task-abc123")

    Returns:
        Dict with:
            - passed: bool - True if all verifications passed
            - results: list of verification results
            - failed: first failed criterion (if any)
    """
    from .criterion_subtask_map import get_criteria_for_subtask
    from .verification import get_task_criterion, run_verification

    # Get linked criteria
    criteria = get_criteria_for_subtask(subtask_table_id)
    if not criteria:
        # No linked criteria - subtask passes without verification
        return {"passed": True, "results": [], "failed": None}

    results = []
    with get_connection() as conn:
        for crit in criteria:
            criterion_id = crit.get("criterion_id")  # This is the ac-XXX code
            if not criterion_id:
                logger.warning(f"Criterion mapping missing criterion_id: {crit}")
                continue

            # Get full criterion details
            full_criterion = get_task_criterion(conn, task_id, criterion_id)
            if not full_criterion:
                logger.warning(f"Criterion {criterion_id} not found for task {task_id}")
                continue

            # Skip if no verify_command
            if not full_criterion.get("verify_command"):
                logger.debug(f"Criterion {criterion_id} has no verify_command, skipping")
                results.append(
                    {
                        "criterion_id": criterion_id,
                        "status": "skipped",
                        "reason": "no verify_command",
                    }
                )
                continue

            # Skip if already verified
            if full_criterion.get("verified"):
                logger.debug(f"Criterion {criterion_id} already verified, skipping")
                results.append(
                    {
                        "criterion_id": criterion_id,
                        "status": "already_verified",
                    }
                )
                continue

            # Run verification
            result = run_verification(conn, task_id, criterion_id)
            results.append(result)

            # Check for failure
            if result.get("status") == "failed":
                return {
                    "passed": False,
                    "results": results,
                    "failed": result,
                }

            # Check for escalation to human
            if result.get("error") and "HUMAN" in str(result.get("error", "")):
                return {
                    "passed": False,
                    "results": results,
                    "failed": result,
                }

    return {"passed": True, "results": results, "failed": None}


def update_subtask_passes(
    task_id: str,
    subtask_id: str,
    passes: bool,
    force: bool = False,  # Deprecated: kept for API compatibility, ignored
) -> dict[str, Any] | None:
    """Update subtask passes status with automatic verification.

    When passes is set to True:
    1. Looks up linked criteria via criterion_subtask_map
    2. For each criterion with verify_command, runs verification
    3. Only marks subtask passes=true if all verifications pass
    4. Auto-closes all steps on success
    5. Raises SubtaskVerificationError on failure with attempt count and output

    When passes is set to False, clears passed_at without verification.

    Args:
        task_id: Parent task ID
        subtask_id: Subtask ID (e.g., "1.1")
        passes: Whether the subtask passes
        force: DEPRECATED - kept for API compatibility, ignored

    Returns:
        Updated subtask dict or None if not found.

    Raises:
        SubtaskVerificationError: If verification fails (when passes=True)
    """
    _ = force  # Deprecated parameter, ignored
    table_id = _generate_subtask_id(task_id, subtask_id)

    # If marking as failed/incomplete, no verification needed
    if not passes:
        passed_at = None
        with get_connection() as conn, conn.cursor() as cur:
            cur.execute(
                f"""
                UPDATE task_subtasks
                SET passes = %s, passed_at = %s
                WHERE id = %s
                RETURNING {SUBTASK_COLUMNS}
                """,
                (passes, passed_at, table_id),
            )
            row = cur.fetchone()
            conn.commit()

        if not row:
            logger.warning("Subtask %s not found for task %s", subtask_id, task_id)
            return None

        logger.debug("Updated subtask %s passes=False for task %s", subtask_id, task_id)
        return _row_to_dict(row)

    # passes=True: Run verification for linked criteria
    verification_result = _run_linked_verifications_for_subtask(table_id, task_id)

    if not verification_result["passed"]:
        failed = verification_result["failed"]
        criterion_id = failed.get("criterion_id", "unknown")
        output = failed.get("output", "No output")
        attempts = failed.get("attempts", 0)
        escalation_level = failed.get("escalation_level", "WORKER")

        # Build error message based on escalation level
        from .verification import MAX_WORKER_ATTEMPTS

        if escalation_level == "HUMAN":
            message = (
                f"Criterion {criterion_id} requires human review. "
                f"Verification failed after exhausting supervisor attempts. "
                f"Use 'st criterion override' to manually approve."
            )
        elif escalation_level == "SUPERVISOR":
            message = (
                f"Criterion {criterion_id} verification failed. "
                f"Escalated to SUPERVISOR level after 3 worker attempts. "
                f"Attempt {attempts}/2 at current level.\n"
                f"Output: {output[:500]}"
            )
        else:
            # WORKER level
            remaining = MAX_WORKER_ATTEMPTS - attempts
            message = (
                f"Criterion {criterion_id} verification failed. "
                f"Attempt {attempts}/{MAX_WORKER_ATTEMPTS}. "
                f"{remaining} attempt(s) remaining before escalation.\n"
                f"Output: {output[:500]}"
            )

        raise SubtaskVerificationError(
            message=message,
            criterion_id=criterion_id,
            output=output,
            attempts=attempts,
            escalation_level=escalation_level,
        )

    # All verifications passed - mark subtask as passed
    passed_at = datetime.now(UTC)

    with get_connection() as conn, conn.cursor() as cur:
        # Auto-close all incomplete steps for this subtask (cleanup)
        cur.execute(
            """
            UPDATE task_subtask_steps
            SET passes = TRUE, passed_at = %s
            WHERE subtask_id = %s AND passes = FALSE
            """,
            (passed_at, table_id),
        )
        steps_closed = cur.rowcount
        if steps_closed > 0:
            logger.info(f"Auto-closed {steps_closed} incomplete steps for subtask {subtask_id}")

        cur.execute(
            f"""
            UPDATE task_subtasks
            SET passes = %s, passed_at = %s
            WHERE id = %s
            RETURNING {SUBTASK_COLUMNS}
            """,
            (passes, passed_at, table_id),
        )
        row = cur.fetchone()
        conn.commit()

    if not row:
        logger.warning("Subtask %s not found for task %s", subtask_id, task_id)
        return None

    logger.info(
        "Subtask %s verified and passed for task %s (verified %d criteria)",
        subtask_id,
        task_id,
        len(verification_result["results"]),
    )
    return _row_to_dict(row)


def delete_subtasks_for_task(task_id: str) -> int:
    """Delete all subtasks for a task.

    Args:
        task_id: Parent task ID

    Returns:
        Number of subtasks deleted.
    """
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            "DELETE FROM task_subtasks WHERE task_id = %s",
            (task_id,),
        )
        count: int = cur.rowcount
        conn.commit()

    logger.debug("Deleted %d subtasks for task %s", count, task_id)
    return count


def delete_subtask(task_id: str, subtask_id: str) -> bool:
    """Delete a single subtask and its steps.

    Cascading delete: Steps are deleted first (FK constraint), then the subtask.

    Args:
        task_id: Parent task ID
        subtask_id: Subtask ID to delete (e.g., "99.1")

    Returns:
        True if subtask was deleted, False if not found.
    """
    from .steps import delete_steps_for_subtask

    table_id = _generate_subtask_id(task_id, subtask_id)

    # First delete associated steps (FK cascade not configured)
    steps_deleted = delete_steps_for_subtask(table_id)

    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            "DELETE FROM task_subtasks WHERE id = %s",
            (table_id,),
        )
        deleted: bool = cur.rowcount > 0
        conn.commit()

    if deleted:
        logger.info(
            "Deleted subtask %s from task %s (%d steps removed)",
            subtask_id,
            task_id,
            steps_deleted,
        )
    else:
        logger.warning("Subtask %s not found in task %s", subtask_id, task_id)

    return deleted


def bulk_create_subtasks(
    task_id: str,
    subtasks: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Create multiple subtasks for a task in a single transaction.

    Also creates step rows in task_subtask_steps table when steps are provided.
    The JSONB steps column is not used (deprecated).

    Args:
        task_id: Parent task ID
        subtasks: List of subtask dicts with keys:
            - subtask_id: str (required) - e.g., "1.1"
            - description: str (required)
            - phase: str (optional)
            - steps: list[str | dict] (optional) - strings or {description, spec} objects
            - display_order: int (optional, auto-assigned if missing)
            - details: dict (optional) - deprecated, use step-level specs

    Returns:
        List of created subtask dicts.

    Raises:
        Exception: If task_id doesn't exist or on DB error.
    """
    import json

    if not subtasks:
        return []

    created = []
    steps_to_create: list[tuple[str, list[str | dict[str, Any]]]] = []

    with get_connection() as conn, conn.cursor() as cur:
        for idx, subtask in enumerate(subtasks):
            subtask_id = subtask["subtask_id"]
            table_id = _generate_subtask_id(task_id, subtask_id)
            display_order = subtask.get("display_order", idx)
            steps = subtask.get("steps", [])
            details = subtask.get("details")
            details_json = json.dumps(details) if details else None

            cur.execute(
                f"""
                INSERT INTO task_subtasks (id, task_id, subtask_id, phase, description,
                                           details, display_order)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                RETURNING {SUBTASK_COLUMNS}
                """,
                (
                    table_id,
                    task_id,
                    subtask_id,
                    subtask.get("phase"),
                    subtask["description"],
                    details_json,
                    display_order,
                ),
            )
            row = cur.fetchone()
            created.append(_row_to_dict(row))

            # Queue steps for creation after subtask commit
            if steps:
                steps_to_create.append((table_id, steps))

        conn.commit()

    # Create steps in normalized table (outside subtask transaction for safety)
    # Track which subtasks got steps so we can update the response
    subtasks_with_steps: dict[str, list[dict[str, Any]]] = {}
    for subtask_table_id, step_items in steps_to_create:
        try:
            created_steps = bulk_create_steps(subtask_table_id, step_items)
            subtasks_with_steps[subtask_table_id] = created_steps
        except Exception as e:
            logger.error("Failed to create steps for subtask %s: %s", subtask_table_id, e)
            # Continue - subtask created, steps failed (partial success)

    # Update returned subtasks with their created steps
    for subtask in created:
        subtask_table_id = subtask["id"]
        if subtask_table_id in subtasks_with_steps:
            subtask["steps_from_table"] = subtasks_with_steps[subtask_table_id]

    logger.info("Created %d subtasks for task %s", len(created), task_id)
    return created


def get_subtask_summary(task_id: str) -> dict[str, Any]:
    """Get summary of subtask completion for a task.

    Returns:
        Dict with keys:
            - total: Total number of subtasks
            - completed: Number of subtasks with passes=True
            - next_subtask_id: ID of next incomplete subtask, or None
            - progress_percent: Completion percentage (0-100)
    """
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT
                COUNT(*) as total,
                COUNT(*) FILTER (WHERE passes = TRUE) as completed,
                MIN(subtask_id) FILTER (WHERE passes = FALSE) as next_subtask_id
            FROM task_subtasks
            WHERE task_id = %s
            """,
            (task_id,),
        )
        row = cur.fetchone()

    total = row[0] if row else 0
    completed = row[1] if row else 0
    next_subtask_id = row[2] if row else None
    progress_percent = round((completed / total * 100) if total > 0 else 0, 1)

    return {
        "total": total,
        "completed": completed,
        "next_subtask_id": next_subtask_id,
        "progress_percent": progress_percent,
    }


# =============================================================================
# Dependency handling (delegates to subtask_dependencies module)
# =============================================================================


def add_subtask_dependency(
    task_id: str,
    subtask_id: str,
    depends_on_subtask_id: str,
) -> dict[str, Any] | None:
    """Add a dependency between two subtasks.

    Args:
        task_id: The parent task ID
        subtask_id: The subtask that has the dependency (e.g., "2.1")
        depends_on_subtask_id: The subtask that must complete first (e.g., "1.1")

    Returns:
        Created dependency record or None if already exists
    """
    from .subtask_dependencies import add_dependency

    # Convert short IDs to table IDs
    table_id = _generate_subtask_id(task_id, subtask_id)
    depends_on_table_id = _generate_subtask_id(task_id, depends_on_subtask_id)
    return add_dependency(table_id, depends_on_table_id)


def get_subtask_dependencies(task_id: str, subtask_id: str) -> list[str]:
    """Get all subtasks that this subtask depends on.

    Args:
        task_id: The parent task ID
        subtask_id: The subtask to check

    Returns:
        List of subtask IDs (short form like "1.1") that must complete first
    """
    from .subtask_dependencies import get_dependencies

    table_id = _generate_subtask_id(task_id, subtask_id)
    dep_table_ids = get_dependencies(table_id)
    # Extract short subtask IDs from table IDs
    return [tid.split("-")[-1] for tid in dep_table_ids]


def is_subtask_blocked(task_id: str, subtask_id: str) -> bool:
    """Check if a subtask is blocked by incomplete dependencies.

    Args:
        task_id: The parent task ID
        subtask_id: The subtask to check

    Returns:
        True if any dependency is incomplete
    """
    from .subtask_dependencies import is_blocked

    table_id = _generate_subtask_id(task_id, subtask_id)
    return is_blocked(table_id)


def get_blocking_subtasks(task_id: str, subtask_id: str) -> list[dict[str, Any]]:
    """Get incomplete subtasks blocking this subtask.

    Args:
        task_id: The parent task ID
        subtask_id: The subtask to check

    Returns:
        List of blocking subtask info
    """
    from .subtask_dependencies import get_blocking_dependencies

    table_id = _generate_subtask_id(task_id, subtask_id)
    return get_blocking_dependencies(table_id)


def bulk_add_subtask_dependencies(
    task_id: str,
    dependencies: list[tuple[str, str]],
) -> list[dict[str, Any]]:
    """Add multiple dependencies at once.

    Args:
        task_id: The parent task ID
        dependencies: List of (subtask_id, depends_on_subtask_id) tuples
                     using short IDs like "1.1", "2.1"

    Returns:
        List of created dependency records
    """
    from .subtask_dependencies import bulk_add_dependencies

    # Convert short IDs to table IDs
    table_id_deps = [
        (_generate_subtask_id(task_id, s), _generate_subtask_id(task_id, d))
        for s, d in dependencies
    ]
    return bulk_add_dependencies(table_id_deps)
