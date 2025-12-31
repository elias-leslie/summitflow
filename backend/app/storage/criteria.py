"""Storage module for unified acceptance criteria.

Implements the TDD architecture with junction tables linking criteria
to capabilities, tasks, and tests.
"""

import logging
from datetime import UTC, datetime
from typing import Any

import psycopg

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
            WHERE project_id = %s
            ORDER BY criterion_id DESC
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
) -> dict[str, Any]:
    """Create a new acceptance criterion with auto-generated criterion_id."""
    criterion_id = get_next_criterion_id(conn, project_id)

    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO acceptance_criteria
                (project_id, criterion_id, criterion, category, measurement, threshold, created_by_task_id)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            RETURNING id, project_id, criterion_id, criterion, category, measurement, threshold,
                      created_at, created_by_task_id
            """,
            (
                project_id,
                criterion_id,
                criterion,
                category,
                measurement,
                threshold,
                created_by_task_id,
            ),
        )
        row = cur.fetchone()
        conn.commit()

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
    }


def get_criterion(
    conn: psycopg.Connection, project_id: str, criterion_id: str
) -> dict[str, Any] | None:
    """Get a criterion by project + criterion_id string."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, project_id, criterion_id, criterion, category, measurement, threshold,
                   created_at, created_by_task_id
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
    }


def get_criterion_by_id(conn: psycopg.Connection, db_id: int) -> dict[str, Any] | None:
    """Get a criterion by internal database ID."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, project_id, criterion_id, criterion, category, measurement, threshold,
                   created_at, created_by_task_id
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
    }


def delete_criterion(conn: psycopg.Connection, db_id: int) -> bool:
    """Hard delete a criterion by database ID."""
    with conn.cursor() as cur:
        cur.execute("DELETE FROM acceptance_criteria WHERE id = %s", (db_id,))
        deleted = cur.rowcount > 0
        conn.commit()
    return deleted


def check_and_delete_orphan(conn: psycopg.Connection, criterion_db_id: int) -> bool:
    """Check if criterion is orphaned and delete if so.

    A criterion is orphaned if it has no links in capability_criteria or task_criteria.
    Returns True if criterion was deleted, False if still in use.
    """
    with conn.cursor() as cur:
        # Check for any references
        cur.execute(
            """
            SELECT EXISTS (
                SELECT 1 FROM capability_criteria WHERE criterion_id = %s
                UNION ALL
                SELECT 1 FROM task_criteria WHERE criterion_id = %s
            )
            """,
            (criterion_db_id, criterion_db_id),
        )
        has_references = cur.fetchone()[0]

        if not has_references:
            cur.execute("DELETE FROM acceptance_criteria WHERE id = %s", (criterion_db_id,))
            conn.commit()
            logger.info(f"Deleted orphaned criterion id={criterion_db_id}")
            return True

    return False


# =============================================================================
# Capability-Criteria Junction Operations
# =============================================================================


def link_criterion_to_capability(
    conn: psycopg.Connection, capability_db_id: int, criterion_db_id: int
) -> bool:
    """Link a criterion to a capability."""
    with conn.cursor() as cur:
        try:
            cur.execute(
                """
                INSERT INTO capability_criteria (capability_id, criterion_id)
                VALUES (%s, %s)
                ON CONFLICT DO NOTHING
                """,
                (capability_db_id, criterion_db_id),
            )
            conn.commit()
            return True
        except Exception as e:
            logger.error(f"Failed to link criterion to capability: {e}")
            conn.rollback()
            return False


def unlink_criterion_from_capability(
    conn: psycopg.Connection, capability_db_id: int, criterion_db_id: int
) -> bool:
    """Unlink a criterion from a capability and clean up orphans."""
    with conn.cursor() as cur:
        cur.execute(
            """
            DELETE FROM capability_criteria
            WHERE capability_id = %s AND criterion_id = %s
            """,
            (capability_db_id, criterion_db_id),
        )
        deleted = cur.rowcount > 0
        conn.commit()

    if deleted:
        # Check if criterion is now orphaned
        check_and_delete_orphan(conn, criterion_db_id)

    return deleted


def get_criteria_for_capability(
    conn: psycopg.Connection, project_id: str, capability_id: str
) -> list[dict[str, Any]]:
    """Get all criteria linked to a capability.

    Args:
        project_id: Project ID
        capability_id: The string capability_id (e.g., 'login', 'password-reset')
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT ac.id, ac.project_id, ac.criterion_id, ac.criterion,
                   ac.category, ac.measurement, ac.threshold, ac.created_at, ac.created_by_task_id
            FROM acceptance_criteria ac
            JOIN capability_criteria cc ON ac.id = cc.criterion_id
            JOIN capabilities c ON cc.capability_id = c.id
            WHERE c.project_id = %s AND c.capability_id = %s
            ORDER BY ac.criterion_id
            """,
            (project_id, capability_id),
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
        }
        for row in rows
    ]


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
    """Get all criteria linked to a task with verification state."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT ac.id, ac.project_id, ac.criterion_id, ac.criterion,
                   ac.category, ac.measurement, ac.threshold, ac.created_at, ac.created_by_task_id,
                   tc.verified, tc.verified_at, tc.verified_by
            FROM acceptance_criteria ac
            JOIN task_criteria tc ON ac.id = tc.criterion_id
            WHERE ac.project_id = %s AND tc.task_id = %s
            ORDER BY ac.criterion_id
            """,
            (project_id, task_id),
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
            "verified": row[9],
            "verified_at": row[10],
            "verified_by": row[11],
        }
        for row in rows
    ]


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
    """Get effective criteria for a task from capability or task junction tables.

    Sources criteria from:
    1. Capability (if task.capability_id is set) via capability_criteria junction
    2. Task-specific criteria via task_criteria junction
    3. JSONB fallback (for backward compatibility during migration)

    Args:
        conn: Database connection
        project_id: Project ID
        task: Task dict with id, capability_id, acceptance_criteria fields

    Returns:
        List of criterion dicts with id, criterion_id, criterion, category,
        measurement, threshold, and optionally verified/verified_at/verified_by
    """
    task_id = task.get("id")
    capability_id = task.get("capability_id")

    # Source 1: Capability-linked criteria
    if capability_id:
        criteria = get_criteria_for_capability(conn, project_id, capability_id)
        if criteria:
            logger.debug(
                f"criteria_from_capability: task_id={task_id}, capability_id={capability_id}, "
                f"count={len(criteria)}"
            )
            return criteria

    # Source 2: Task-specific criteria
    if task_id:
        criteria = get_criteria_for_task(conn, project_id, task_id)
        if criteria:
            logger.debug(f"criteria_from_task: task_id={task_id}, count={len(criteria)}")
            return criteria

    # Source 3: JSONB fallback (bridge until Phase 7 migration)
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
                "verified": c.get("verified", False),
                "verified_at": c.get("verified_at"),
                "verified_by": c.get("verified_by"),
            }
            for i, c in enumerate(jsonb_criteria)
        ]

    # No criteria found
    logger.debug(f"no_criteria_found: task_id={task_id}, capability_id={capability_id}")
    return []
