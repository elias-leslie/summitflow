"""Storage module for unified acceptance criteria.

Implements the TDD architecture with junction tables linking criteria
to capabilities, tasks, and tests.
"""

import logging
from datetime import UTC, datetime
from typing import Any

import psycopg
from psycopg import sql

from .connection import get_connection

logger = logging.getLogger(__name__)


# =============================================================================
# Criterion ID Generation
# =============================================================================


def get_next_criterion_id(conn: psycopg.Connection, project_id: str) -> str:
    """Generate the next criterion_id for a project.

    Format: ac-NNN (e.g., ac-001, ac-012, ac-123)
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT criterion_id FROM acceptance_criteria
            WHERE project_id = %s AND criterion_id ~ '^ac-[0-9]+$'
            ORDER BY CAST(SUBSTRING(criterion_id FROM 4) AS INTEGER) DESC
            LIMIT 1
            """,
            (project_id,),
        )
        row = cur.fetchone()

        if row is None:
            return "ac-001"

        # Parse current max and increment
        current = row[0]  # e.g., "ac-042"
        try:
            num = int(current.split("-")[1])
            return f"ac-{num + 1:03d}"
        except (IndexError, ValueError):
            logger.warning(f"Invalid criterion_id format: {current}, starting from ac-001")
            return "ac-001"


# =============================================================================
# CRUD Operations for acceptance_criteria
# =============================================================================


def create_criterion(
    conn: psycopg.Connection,
    project_id: str,
    criterion: str,
    category: str = "correctness",
    measurement: str = "test",
    threshold: str | None = None,
    created_by_task_id: str | None = None,
    verify_command: str | None = None,
    verify_by: str = "test",
    expected_output: str | None = None,
) -> dict[str, Any]:
    """Create a new acceptance criterion with auto-generated criterion_id.

    Args:
        conn: Database connection
        project_id: Project ID
        criterion: The criterion text (what to verify)
        category: Category (correctness, performance, security, quality)
        measurement: Legacy field for measurement type
        threshold: Legacy field for threshold value
        created_by_task_id: Task ID that created this criterion
        verify_command: Bash command to verify the criterion
        verify_by: How to verify (test, opus, human, agent)
        expected_output: Expected output from verify_command
    """
    criterion_id = get_next_criterion_id(conn, project_id)

    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO acceptance_criteria
                (project_id, criterion_id, criterion, category, measurement, threshold,
                 created_by_task_id, verify_command, verify_by, expected_output)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id, project_id, criterion_id, criterion, category, measurement, threshold,
                      created_at, created_by_task_id, verify_command, verify_by, expected_output
            """,
            (
                project_id,
                criterion_id,
                criterion,
                category,
                measurement,
                threshold,
                created_by_task_id,
                verify_command,
                verify_by,
                expected_output,
            ),
        )
        row = cur.fetchone()
        conn.commit()

    assert row is not None, "INSERT with RETURNING should always return a row"
    return {
        "id": row[0],
        "project_id": row[1],
        "criterion_id": row[2],
        "criterion": row[3],
        "category": row[4],
        "measurement": row[5],
        "threshold": row[6],
        "created_at": row[7],
        "created_by_task_id": row[8],
        "verify_command": row[9],
        "verify_by": row[10],
        "expected_output": row[11],
    }


def get_criterion(
    conn: psycopg.Connection, project_id: str, criterion_id: str
) -> dict[str, Any] | None:
    """Get a criterion by project + criterion_id string."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, project_id, criterion_id, criterion, category, measurement, threshold,
                   created_at, created_by_task_id, verify_command, verify_by, expected_output
            FROM acceptance_criteria
            WHERE project_id = %s AND criterion_id = %s
            """,
            (project_id, criterion_id),
        )
        row = cur.fetchone()

    if row is None:
        return None

    return {
        "id": row[0],
        "project_id": row[1],
        "criterion_id": row[2],
        "criterion": row[3],
        "category": row[4],
        "measurement": row[5],
        "threshold": row[6],
        "created_at": row[7],
        "created_by_task_id": row[8],
        "verify_command": row[9],
        "verify_by": row[10],
        "expected_output": row[11],
    }


def get_criterion_by_id(conn: psycopg.Connection, db_id: int) -> dict[str, Any] | None:
    """Get a criterion by internal database ID."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, project_id, criterion_id, criterion, category, measurement, threshold,
                   created_at, created_by_task_id, verify_command, verify_by, expected_output
            FROM acceptance_criteria
            WHERE id = %s
            """,
            (db_id,),
        )
        row = cur.fetchone()

    if row is None:
        return None

    return {
        "id": row[0],
        "project_id": row[1],
        "criterion_id": row[2],
        "criterion": row[3],
        "category": row[4],
        "measurement": row[5],
        "threshold": row[6],
        "created_at": row[7],
        "created_by_task_id": row[8],
        "verify_command": row[9],
        "verify_by": row[10],
        "expected_output": row[11],
    }


def delete_criterion(conn: psycopg.Connection, db_id: int) -> bool:
    """Hard delete a criterion by database ID."""
    with conn.cursor() as cur:
        cur.execute("DELETE FROM acceptance_criteria WHERE id = %s", (db_id,))
        deleted = cur.rowcount > 0
        conn.commit()
    return deleted


def update_criterion(
    conn: psycopg.Connection,
    project_id: str,
    criterion_id: str,
    updates: dict[str, Any],
) -> dict[str, Any] | None:
    """Update a criterion's fields.

    Args:
        conn: Database connection
        project_id: Project ID
        criterion_id: The string criterion_id (e.g., 'ac-001')
        updates: Dict of fields to update (criterion, category, measurement, threshold,
                 verify_command, verify_by, expected_output)

    Returns:
        Updated criterion dict, or None if not found
    """
    allowed_fields = {
        "criterion",
        "category",
        "measurement",
        "threshold",
        "verify_command",
        "verify_by",
        "expected_output",
    }
    filtered = {k: v for k, v in updates.items() if k in allowed_fields}

    if not filtered:
        # No valid fields to update, just return current state
        return get_criterion(conn, project_id, criterion_id)

    # Build dynamic UPDATE clause using psycopg.sql for type safety
    set_clauses = sql.SQL(", ").join(
        sql.SQL("{} = %s").format(sql.Identifier(field)) for field in filtered
    )
    values = list(filtered.values())
    values.extend([project_id, criterion_id])

    query = sql.SQL("""
        UPDATE acceptance_criteria
        SET {}
        WHERE project_id = %s AND criterion_id = %s
        RETURNING id, project_id, criterion_id, criterion, category, measurement, threshold,
                  created_at, created_by_task_id, verify_command, verify_by, expected_output
    """).format(set_clauses)

    with conn.cursor() as cur:
        cur.execute(query, values)
        row = cur.fetchone()
        conn.commit()

    if row is None:
        return None

    return {
        "id": row[0],
        "project_id": row[1],
        "criterion_id": row[2],
        "criterion": row[3],
        "category": row[4],
        "measurement": row[5],
        "threshold": row[6],
        "created_at": row[7],
        "created_by_task_id": row[8],
        "verify_command": row[9],
        "verify_by": row[10],
        "expected_output": row[11],
    }


def check_and_delete_orphan(conn: psycopg.Connection, criterion_db_id: int) -> bool:
    """Check if criterion is orphaned and delete if so.

    A criterion is orphaned if it has no links in task_criteria.
    Returns True if criterion was deleted, False if still in use.
    """
    with conn.cursor() as cur:
        # Check for any references
        cur.execute(
            """
            SELECT EXISTS (
                SELECT 1 FROM task_criteria WHERE criterion_id = %s
            )
            """,
            (criterion_db_id,),
        )
        result = cur.fetchone()
        assert result is not None, "EXISTS query should always return a row"
        has_references = result[0]

        if not has_references:
            cur.execute("DELETE FROM acceptance_criteria WHERE id = %s", (criterion_db_id,))
            conn.commit()
            logger.info(f"Deleted orphaned criterion id={criterion_db_id}")
            return True

    return False


# =============================================================================
# Task-Criteria Junction Operations
# =============================================================================


def link_criterion_to_task(conn: psycopg.Connection, task_id: str, criterion_db_id: int) -> bool:
    """Link a criterion to a task."""
    with conn.cursor() as cur:
        try:
            cur.execute(
                """
                INSERT INTO task_criteria (task_id, criterion_id)
                VALUES (%s, %s)
                ON CONFLICT DO NOTHING
                """,
                (task_id, criterion_db_id),
            )
            conn.commit()
            return True
        except Exception as e:
            logger.error(f"Failed to link criterion to task: {e}")
            conn.rollback()
            return False


def unlink_criterion_from_task(
    conn: psycopg.Connection, task_id: str, criterion_db_id: int
) -> bool:
    """Unlink a criterion from a task and clean up orphans."""
    with conn.cursor() as cur:
        cur.execute(
            """
            DELETE FROM task_criteria
            WHERE task_id = %s AND criterion_id = %s
            """,
            (task_id, criterion_db_id),
        )
        deleted = cur.rowcount > 0
        conn.commit()

    if deleted:
        check_and_delete_orphan(conn, criterion_db_id)

    return deleted


def get_criteria_for_task(
    conn: psycopg.Connection, project_id: str, task_id: str
) -> list[dict[str, Any]]:
    """Get all criteria linked to a task with verification state.

    Note: project_id is kept for API compatibility but not used in query.
    The task_criteria junction already constrains results by task_id,
    and criteria may have different project_id if task was moved.
    """
    _ = project_id  # Unused - criteria project may differ from task project
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT ac.id, ac.project_id, ac.criterion_id, ac.criterion,
                   ac.category, ac.measurement, ac.threshold, ac.created_at, ac.created_by_task_id,
                   ac.verify_command, ac.verify_by, ac.expected_output,
                   tc.verified, tc.verified_at, tc.verified_by
            FROM acceptance_criteria ac
            JOIN task_criteria tc ON ac.id = tc.criterion_id
            WHERE tc.task_id = %s
            ORDER BY ac.criterion_id
            """,
            (task_id,),
        )
        rows = cur.fetchall()

    return [
        {
            "id": row[0],
            "project_id": row[1],
            "criterion_id": row[2],
            "criterion": row[3],
            "category": row[4],
            "measurement": row[5],
            "threshold": row[6],
            "created_at": row[7],
            "created_by_task_id": row[8],
            "verify_command": row[9],
            "verify_by": row[10],
            "expected_output": row[11],
            "verified": row[12],
            "verified_at": row[13],
            "verified_by_who": row[14],  # Renamed to avoid conflict with ac.verify_by
        }
        for row in rows
    ]


def get_criteria_count_for_task(task_id: str) -> int:
    """Get count of criteria linked to a task.

    This is a lightweight query for /do_it pre-checks and compact display.
    Does not require project_id since task_id is globally unique.

    Checks task_acceptance_criteria (new model) first, falls back to
    task_criteria (legacy junction) for unmigrated data.
    """
    with get_connection() as conn, conn.cursor() as cur:
        # Check new model first
        cur.execute(
            "SELECT COUNT(*) FROM task_acceptance_criteria WHERE task_id = %s",
            (task_id,),
        )
        row = cur.fetchone()
        count = row[0] if row else 0

        # Fallback to legacy model if new model is empty
        if count == 0:
            cur.execute(
                "SELECT COUNT(*) FROM task_criteria WHERE task_id = %s",
                (task_id,),
            )
            row = cur.fetchone()
            count = row[0] if row else 0

    return count


def get_criteria_counts_batch(task_ids: list[str]) -> dict[str, int]:
    """Get criteria counts for multiple tasks in a single query.

    This eliminates N+1 queries when listing tasks.
    Returns a dict mapping task_id -> count.

    Checks task_acceptance_criteria (new model) first, falls back to
    task_criteria (legacy junction) for unmigrated data.
    """
    if not task_ids:
        return {}

    with get_connection() as conn, conn.cursor() as cur:
        # Get counts from new model
        cur.execute(
            """
            SELECT task_id, COUNT(*) as count
            FROM task_acceptance_criteria
            WHERE task_id = ANY(%s)
            GROUP BY task_id
            """,
            (task_ids,),
        )
        new_counts = {row[0]: row[1] for row in cur.fetchall()}

        # Get counts from legacy model for tasks not in new model
        missing_ids = [tid for tid in task_ids if tid not in new_counts]
        legacy_counts: dict[str, int] = {}
        if missing_ids:
            cur.execute(
                """
                SELECT task_id, COUNT(*) as count
                FROM task_criteria
                WHERE task_id = ANY(%s)
                GROUP BY task_id
                """,
                (missing_ids,),
            )
            legacy_counts = {row[0]: row[1] for row in cur.fetchall()}

    # Merge results, default to 0 for tasks with no criteria
    result = {tid: new_counts.get(tid, legacy_counts.get(tid, 0)) for tid in task_ids}
    return result


def update_task_criterion_verification(
    conn: psycopg.Connection,
    task_id: str,
    criterion_db_id: int,
    verified: bool,
    verified_by: str,
) -> bool:
    """Update the verification status for a task's criterion."""
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE task_criteria
            SET verified = %s, verified_at = %s, verified_by = %s
            WHERE task_id = %s AND criterion_id = %s
            """,
            (
                verified,
                datetime.now(UTC) if verified else None,
                verified_by,
                task_id,
                criterion_db_id,
            ),
        )
        updated = cur.rowcount > 0
        conn.commit()
    return updated


# =============================================================================
# Criterion-Tests Junction Operations
# =============================================================================


def link_test_to_criterion(
    conn: psycopg.Connection, criterion_db_id: int, test_db_id: int, is_primary: bool = False
) -> bool:
    """Link a test to a criterion."""
    with conn.cursor() as cur:
        try:
            cur.execute(
                """
                INSERT INTO criterion_tests (criterion_id, test_id, is_primary)
                VALUES (%s, %s, %s)
                ON CONFLICT (criterion_id, test_id) DO UPDATE SET is_primary = EXCLUDED.is_primary
                """,
                (criterion_db_id, test_db_id, is_primary),
            )
            conn.commit()
            return True
        except Exception as e:
            logger.error(f"Failed to link test to criterion: {e}")
            conn.rollback()
            return False


def unlink_test_from_criterion(
    conn: psycopg.Connection, criterion_db_id: int, test_db_id: int
) -> bool:
    """Unlink a test from a criterion."""
    with conn.cursor() as cur:
        cur.execute(
            """
            DELETE FROM criterion_tests
            WHERE criterion_id = %s AND test_id = %s
            """,
            (criterion_db_id, test_db_id),
        )
        deleted = cur.rowcount > 0
        conn.commit()
    return deleted


def get_tests_for_criterion(conn: psycopg.Connection, criterion_db_id: int) -> list[dict[str, Any]]:
    """Get all tests linked to a criterion."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT t.id, t.project_id, t.test_id, t.name, t.test_type,
                   t.last_result, t.last_run_at, ct.is_primary
            FROM tests t
            JOIN criterion_tests ct ON t.id = ct.test_id
            WHERE ct.criterion_id = %s
            ORDER BY ct.is_primary DESC, t.name
            """,
            (criterion_db_id,),
        )
        rows = cur.fetchall()

    return [
        {
            "id": row[0],
            "project_id": row[1],
            "test_id": row[2],
            "name": row[3],
            "test_type": row[4],
            "last_result": row[5],
            "last_run_at": row[6],
            "is_primary": row[7],
        }
        for row in rows
    ]


def get_criteria_for_test(conn: psycopg.Connection, test_db_id: int) -> list[dict[str, Any]]:
    """Get all criteria that a test verifies."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT ac.id, ac.project_id, ac.criterion_id, ac.criterion,
                   ac.category, ac.measurement, ac.threshold, ct.is_primary
            FROM acceptance_criteria ac
            JOIN criterion_tests ct ON ac.id = ct.criterion_id
            WHERE ct.test_id = %s
            ORDER BY ac.criterion_id
            """,
            (test_db_id,),
        )
        rows = cur.fetchall()

    return [
        {
            "id": row[0],
            "project_id": row[1],
            "criterion_id": row[2],
            "criterion": row[3],
            "category": row[4],
            "measurement": row[5],
            "threshold": row[6],
            "is_primary": row[7],
        }
        for row in rows
    ]


# =============================================================================
# Effective Criteria Retrieval (dual-source)
# =============================================================================


def get_effective_criteria(
    conn: psycopg.Connection,
    project_id: str,
    task: dict[str, Any],
) -> list[dict[str, Any]]:
    """Get effective criteria for a task.

    Sources criteria from (in order):
    1. task_acceptance_criteria table (new task-scoped model - preferred)
    2. acceptance_criteria + task_criteria junction (legacy model - fallback)
    3. JSONB fallback (very old model - deprecated)

    Args:
        conn: Database connection
        project_id: Project ID
        task: Task dict with id, capability_id, acceptance_criteria fields

    Returns:
        List of criterion dicts with id, criterion_id, criterion, category,
        and verification state fields.
    """
    from .verification import get_criteria_for_task_v2

    task_id = task.get("id")
    capability_id = task.get("capability_id")

    # Source 1: task_acceptance_criteria (new model - preferred)
    if task_id:
        criteria = get_criteria_for_task_v2(conn, task_id)
        if criteria:
            logger.debug(
                f"criteria_from_task_acceptance_criteria: task_id={task_id}, count={len(criteria)}"
            )
            return criteria

    # Source 2: Legacy junction model (fallback for unmigrated data)
    if task_id:
        criteria = get_criteria_for_task(conn, project_id, task_id)
        if criteria:
            logger.debug(f"criteria_from_legacy_junction: task_id={task_id}, count={len(criteria)}")
            return criteria

    # Source 3: JSONB fallback (very old model - deprecated)
    jsonb_criteria = task.get("acceptance_criteria") or []
    if jsonb_criteria:
        logger.debug(
            f"criteria_from_jsonb_fallback: task_id={task_id}, count={len(jsonb_criteria)}"
        )
        # Normalize JSONB format to match junction table format
        return [
            {
                "id": None,  # No DB id for JSONB
                "criterion_id": c.get("id", f"legacy-{i}"),
                "criterion": c.get("criterion", c.get("description", "")),
                "category": c.get("category", "correctness"),
                "measurement": c.get("measurement", "test"),
                "threshold": c.get("threshold"),
                "verify_command": c.get("verify_command"),
                "verify_by": c.get("verify_by", "test"),
                "expected_output": c.get("expected_output"),
                "verified": c.get("verified", False),
                "verified_at": c.get("verified_at"),
                "verified_by_who": c.get("verified_by_who"),
            }
            for i, c in enumerate(jsonb_criteria)
        ]

    # No criteria found
    logger.debug(f"no_criteria_found: task_id={task_id}, capability_id={capability_id}")
    return []
