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


def get_subtask_by_table_id(table_id: str) -> dict[str, Any] | None:
    """Get a single subtask by its full table ID.

    Args:
        table_id: Full subtask ID (e.g., "task-abc123-1.1")

    Returns:
        Subtask dict or None if not found.
    """
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


def update_subtask_passes(
    task_id: str,
    subtask_id: str,
    passes: bool,
) -> dict[str, Any] | None:
    """Update subtask passes status.

    Verification happens at the step level (via step.verify_command).
    Subtask passes ONLY when ALL its steps have passed verification.

    When passes is set to True:
    1. Checks that all steps are passed (required, no bypass)
    2. Raises SubtaskGateError if any step is incomplete
    3. Marks subtask as passed only if all steps passed

    When passes is set to False, clears passed_at.

    Args:
        task_id: Parent task ID
        subtask_id: Subtask ID (e.g., "1.1")
        passes: Whether the subtask passes

    Returns:
        Updated subtask dict or None if not found.

    Raises:
        SubtaskGateError: If any steps are incomplete (no bypass available)
    """
    table_id = _generate_subtask_id(task_id, subtask_id)

    # If marking as failed/incomplete, just update
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

    # passes=True: Gate on all steps being complete (no bypass)
    from .steps import get_steps_for_subtask

    steps = get_steps_for_subtask(table_id)

    # Gate: Subtask must have at least one step to be marked as passed
    if not steps:
        raise SubtaskGateError(
            f"Cannot pass subtask {subtask_id}: subtask has no steps. "
            "Every subtask must have at least one step with verify_command.",
            incomplete_steps=[],
        )

    # Check for incomplete steps, but allow plan_defect steps to be skipped
    # ONLY if their linked fix_step is still passing
    from .steps import STEP_STATUS_PLAN_DEFECT

    # Build a lookup for step passes status
    step_passes_lookup = {s["step_number"]: s.get("passes", False) for s in steps}

    incomplete = []
    plan_defects = []
    invalid_plan_defects = []

    for s in steps:
        if not s.get("passes"):
            if s.get("status") == STEP_STATUS_PLAN_DEFECT:
                # Validate the fix_step is still passing
                fix_step_num = s.get("fix_step_number")
                if fix_step_num and step_passes_lookup.get(fix_step_num):
                    # Fix step exists and is passing - allow plan_defect to be skipped
                    plan_defects.append(s["step_number"])
                else:
                    # Fix step missing or not passing - treat as incomplete
                    invalid_plan_defects.append((s["step_number"], fix_step_num))
                    incomplete.append(s["step_number"])
            else:
                incomplete.append(s["step_number"])

    if incomplete:
        msg = (
            f"Cannot pass subtask {subtask_id}: steps {incomplete} are not complete. "
            "Each step must pass its verify_command before the subtask can be marked complete."
        )
        if invalid_plan_defects:
            msg += (
                f" Steps {[s for s, _ in invalid_plan_defects]} are marked plan_defect "
                "but their fix steps are not passing."
            )
        if plan_defects:
            msg += f" (Plan defect steps {plan_defects} are allowed to be skipped.)"
        raise SubtaskGateError(msg, incomplete_steps=incomplete)

    if plan_defects:
        logger.info(
            "Subtask %s passing with plan_defect steps: %s",
            subtask_id,
            plan_defects,
        )

    # Gate: Must log citations before subtask can be marked as passed
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT COUNT(*) FROM subtask_citations WHERE subtask_id = %s",
            (table_id,),
        )
        row = cur.fetchone()
        citation_count = row[0] if row else 0

    if citation_count == 0:
        raise SubtaskGateError(
            f"Cannot pass subtask {subtask_id}: must log citations first. "
            "Use 'st subtask citations M:uuid+ G:uuid- --subtask X.Y' to log memory citations used.",
            incomplete_steps=[],
        )

    # All steps passed - mark subtask as passed
    passed_at = datetime.now(UTC)

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

    logger.info("Subtask %s passed for task %s", subtask_id, task_id)
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


# =============================================================================
# Subtask Summaries (handoff context isolation)
# =============================================================================


def insert_subtask_summary(
    subtask_id: str,
    summary: str,
    files_modified: list[str] | None = None,
    decisions_made: list[str] | None = None,
) -> dict[str, Any]:
    """Insert or update a handoff summary for a subtask.

    Used to capture context at subtask completion for handoff to next subtask.
    Implements UPSERT - updates existing summary if one exists.

    Args:
        subtask_id: Full subtask table ID (e.g., "task-abc123-1.1")
        summary: Structured summary of work done, key decisions, gotchas
        files_modified: List of file paths modified during this subtask
        decisions_made: List of key decisions made during execution

    Returns:
        The created/updated summary record.
    """
    import json

    files_json = json.dumps(files_modified or [])
    decisions_json = json.dumps(decisions_made or [])

    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO subtask_summaries (subtask_id, summary, files_modified, decisions_made)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (subtask_id) DO UPDATE SET
                summary = EXCLUDED.summary,
                files_modified = EXCLUDED.files_modified,
                decisions_made = EXCLUDED.decisions_made,
                created_at = NOW()
            RETURNING id, subtask_id, summary, files_modified, decisions_made, created_at
            """,
            (subtask_id, summary, files_json, decisions_json),
        )
        row = cur.fetchone()
        conn.commit()

    if not row:
        raise ValueError(f"Insert failed for subtask_id={subtask_id}")

    return {
        "id": row[0],
        "subtask_id": row[1],
        "summary": row[2],
        "files_modified": row[3] or [],
        "decisions_made": row[4] or [],
        "created_at": row[5].isoformat() if row[5] else None,
    }


def get_previous_summary(subtask_id: str) -> dict[str, Any] | None:
    """Get the summary for a specific subtask.

    Args:
        subtask_id: Full subtask table ID (e.g., "task-abc123-1.1")

    Returns:
        Summary record or None if not found.
    """
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, subtask_id, summary, files_modified, decisions_made, created_at
            FROM subtask_summaries
            WHERE subtask_id = %s
            """,
            (subtask_id,),
        )
        row = cur.fetchone()

    if not row:
        return None

    return {
        "id": row[0],
        "subtask_id": row[1],
        "summary": row[2],
        "files_modified": row[3] or [],
        "decisions_made": row[4] or [],
        "created_at": row[5].isoformat() if row[5] else None,
    }


def get_handoff_context(task_id: str, current_subtask_id: str) -> dict[str, Any]:
    """Build handoff context for a subtask from all previous completed subtasks.

    Returns summaries from all completed subtasks before the current one,
    providing fresh context without accumulated conversation history.

    Args:
        task_id: Parent task ID
        current_subtask_id: The subtask about to be executed (e.g., "1.2")

    Returns:
        Dict with:
            - previous_summaries: List of summary records from completed subtasks
            - total_files_modified: Aggregated list of all modified files
            - key_decisions: Aggregated list of all decisions made
    """
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT ss.id, ss.subtask_id, ss.summary, ss.files_modified,
                   ss.decisions_made, ss.created_at, ts.subtask_id as short_id
            FROM subtask_summaries ss
            JOIN task_subtasks ts ON ts.id = ss.subtask_id
            WHERE ts.task_id = %s
              AND ts.passes = TRUE
              AND ts.subtask_id < %s
            ORDER BY ts.display_order
            """,
            (task_id, current_subtask_id),
        )
        rows = cur.fetchall()

    summaries = []
    all_files: list[str] = []
    all_decisions: list[str] = []

    for row in rows:
        files = row[3] or []
        decisions = row[4] or []
        summaries.append(
            {
                "id": row[0],
                "subtask_id": row[1],
                "short_id": row[6],
                "summary": row[2],
                "files_modified": files,
                "decisions_made": decisions,
                "created_at": row[5].isoformat() if row[5] else None,
            }
        )
        all_files.extend(files)
        all_decisions.extend(decisions)

    return {
        "previous_summaries": summaries,
        "total_files_modified": list(set(all_files)),
        "key_decisions": all_decisions,
    }


def parse_citation(citation: str) -> tuple[str, str]:
    """Parse a citation in suffix notation to (episode_uuid_prefix, rating).

    Args:
        citation: Citation string like "M:abc12345+" or "G:def67890-" or "M:xyz99999"
                  Also handles bracket format: "[M:abc12345]"

    Returns:
        Tuple of (uuid_prefix, rating) where rating is 'helpful', 'harmful', or 'used'
    """
    clean = citation.strip("[]")
    prefix = clean[2:10]
    suffix = clean[10:] if len(clean) > 10 else ""
    if suffix == "+":
        rating = "helpful"
    elif suffix == "-":
        rating = "harmful"
    else:
        rating = "used"
    return prefix, rating


def log_citations(task_id: str, subtask_id: str, citations: list[str]) -> int:
    """Log episode citations for a subtask with ratings.

    Parses suffix notation and stores in subtask_citations table.

    Args:
        task_id: Task ID
        subtask_id: Subtask ID (e.g., "1.1")
        citations: List of citations in suffix notation

    Returns:
        Number of citations logged
    """
    if not citations:
        return 0

    table_id = _generate_subtask_id(task_id, subtask_id)

    parsed = [parse_citation(c) for c in citations]

    with get_connection() as conn, conn.cursor() as cur:
        for uuid_prefix, rating in parsed:
            cur.execute(
                """
                INSERT INTO subtask_citations (subtask_id, episode_uuid, rating)
                VALUES (%s, %s, %s)
                """,
                (table_id, uuid_prefix, rating),
            )
        conn.commit()

    logger.info("Logged %d citations for subtask %s", len(parsed), subtask_id)
    return len(parsed)
