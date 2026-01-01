"""Tests storage layer - Test registry CRUD operations.

This module provides data access for the centralized test registry.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from psycopg import sql

from .connection import get_connection


def create_test(
    project_id: str,
    test_id: str,
    name: str,
    test_type: str,
    command: str | None = None,
    script: str | None = None,
    config: dict[str, Any] | None = None,
    working_dir: str | None = None,
    timeout_seconds: int = 60,
) -> dict[str, Any]:
    """Create a new test.

    Args:
        project_id: Project ID
        test_id: Unique test identifier
        name: Human-readable test name
        test_type: Type of test (pytest, mypy, ruff, vitest, api, ui)
        command: Command to run the test
        script: Script content for UI tests
        config: Additional configuration as JSON
        working_dir: Working directory for test execution
        timeout_seconds: Timeout in seconds (default 60)

    Returns:
        The created test dict with all columns.
    """
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO tests (project_id, test_id, name, test_type, command, script,
                              config, working_dir, timeout_seconds)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id, project_id, test_id, name, test_type, command, script,
                      config, working_dir, timeout_seconds, last_run_at, last_result,
                      last_duration_ms, last_output, last_error, run_count, pass_count,
                      fail_count, flaky_score, created_at, updated_at
            """,
            (
                project_id,
                test_id,
                name,
                test_type,
                command,
                script,
                json.dumps(config) if config else "{}",
                working_dir,
                timeout_seconds,
            ),
        )
        row = cur.fetchone()
        conn.commit()

    return _row_to_dict(row)


def get_test(project_id: str, test_id: str) -> dict[str, Any] | None:
    """Get a test by project_id and test_id.

    Returns:
        Test dict or None if not found.
    """
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, project_id, test_id, name, test_type, command, script,
                   config, working_dir, timeout_seconds, last_run_at, last_result,
                   last_duration_ms, last_output, last_error, run_count, pass_count,
                   fail_count, flaky_score, created_at, updated_at
            FROM tests
            WHERE project_id = %s AND test_id = %s
            """,
            (project_id, test_id),
        )
        row = cur.fetchone()

    return _row_to_dict(row) if row else None


def get_test_by_id(test_db_id: int) -> dict[str, Any] | None:
    """Get a test by database ID.

    Returns:
        Test dict or None if not found.
    """
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, project_id, test_id, name, test_type, command, script,
                   config, working_dir, timeout_seconds, last_run_at, last_result,
                   last_duration_ms, last_output, last_error, run_count, pass_count,
                   fail_count, flaky_score, created_at, updated_at
            FROM tests
            WHERE id = %s
            """,
            (test_db_id,),
        )
        row = cur.fetchone()

    return _row_to_dict(row) if row else None


def list_tests(
    project_id: str,
    test_type: str | None = None,
) -> list[dict[str, Any]]:
    """List tests for a project, optionally filtered by type.

    Args:
        project_id: Project ID
        test_type: Optional test type to filter by

    Returns:
        List of test dicts, ordered by type then name.
    """
    with get_connection() as conn, conn.cursor() as cur:
        if test_type is not None:
            cur.execute(
                """
                SELECT id, project_id, test_id, name, test_type, command, script,
                       config, working_dir, timeout_seconds, last_run_at, last_result,
                       last_duration_ms, last_output, last_error, run_count, pass_count,
                       fail_count, flaky_score, created_at, updated_at
                FROM tests
                WHERE project_id = %s AND test_type = %s
                ORDER BY name ASC
                """,
                (project_id, test_type),
            )
        else:
            cur.execute(
                """
                SELECT id, project_id, test_id, name, test_type, command, script,
                       config, working_dir, timeout_seconds, last_run_at, last_result,
                       last_duration_ms, last_output, last_error, run_count, pass_count,
                       fail_count, flaky_score, created_at, updated_at
                FROM tests
                WHERE project_id = %s
                ORDER BY test_type ASC, name ASC
                """,
                (project_id,),
            )
        rows = cur.fetchall()

    return [_row_to_dict(row) for row in rows]


def update_test(
    project_id: str,
    test_id: str,
    **kwargs: Any,
) -> dict[str, Any] | None:
    """Update a test.

    Args:
        project_id: Project ID
        test_id: Test ID
        **kwargs: Fields to update (name, test_type, command, script, config,
                  working_dir, timeout_seconds)

    Returns:
        Updated test dict or None if not found.
    """
    allowed_fields = {
        "name",
        "test_type",
        "command",
        "script",
        "config",
        "working_dir",
        "timeout_seconds",
    }
    updates = {}
    for k, v in kwargs.items():
        if k in allowed_fields:
            if k == "config" and isinstance(v, dict):
                updates[k] = json.dumps(v)
            else:
                updates[k] = v

    if not updates:
        return get_test(project_id, test_id)

    # Always update updated_at
    updates["updated_at"] = datetime.now(UTC).isoformat()

    set_clauses = [sql.SQL("{} = %s").format(sql.Identifier(k)) for k in updates]
    values = [*list(updates.values()), project_id, test_id]

    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            sql.SQL("""
            UPDATE tests
            SET {set_clause}
            WHERE project_id = %s AND test_id = %s
            RETURNING id, project_id, test_id, name, test_type, command, script,
                      config, working_dir, timeout_seconds, last_run_at, last_result,
                      last_duration_ms, last_output, last_error, run_count, pass_count,
                      fail_count, flaky_score, created_at, updated_at
            """).format(set_clause=sql.SQL(", ").join(set_clauses)),
            values,
        )
        row = cur.fetchone()
        conn.commit()

    return _row_to_dict(row) if row else None


def update_test_result(
    project_id: str,
    test_id: str,
    result: str,
    duration_ms: int,
    output: str | None = None,
    error: str | None = None,
) -> dict[str, Any] | None:
    """Update a test with execution results.

    Updates last_* fields and increments run/pass/fail counts.
    Also recalculates flaky_score.

    Args:
        project_id: Project ID
        test_id: Test ID
        result: Test result ('passed', 'failed', 'error', 'timeout')
        duration_ms: Execution duration in milliseconds
        output: Test output (truncated if necessary)
        error: Error message if failed

    Returns:
        Updated test dict or None if not found.
    """
    now = datetime.now(UTC)

    # Determine count increments
    pass_increment = 1 if result == "passed" else 0
    fail_increment = 1 if result in ("failed", "error", "timeout") else 0

    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            UPDATE tests
            SET last_run_at = %s,
                last_result = %s,
                last_duration_ms = %s,
                last_output = %s,
                last_error = %s,
                run_count = run_count + 1,
                pass_count = pass_count + %s,
                fail_count = fail_count + %s,
                flaky_score = CASE
                    WHEN run_count >= 5 THEN
                        CAST(fail_count + %s AS FLOAT) / CAST(run_count + 1 AS FLOAT)
                    ELSE flaky_score
                END,
                updated_at = %s
            WHERE project_id = %s AND test_id = %s
            RETURNING id, project_id, test_id, name, test_type, command, script,
                      config, working_dir, timeout_seconds, last_run_at, last_result,
                      last_duration_ms, last_output, last_error, run_count, pass_count,
                      fail_count, flaky_score, created_at, updated_at
            """,
            (
                now,
                result,
                duration_ms,
                output,
                error,
                pass_increment,
                fail_increment,
                fail_increment,
                now,
                project_id,
                test_id,
            ),
        )
        row = cur.fetchone()
        conn.commit()

    return _row_to_dict(row) if row else None


def delete_test(project_id: str, test_id: str) -> bool:
    """Delete a test.

    Returns:
        True if deleted, False if not found.
    """
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            DELETE FROM tests
            WHERE project_id = %s AND test_id = %s
            RETURNING id
            """,
            (project_id, test_id),
        )
        deleted = cur.fetchone() is not None
        conn.commit()

    return deleted


# ============================================================
# Capability-Test Linking Functions
# ============================================================


def link_test_to_capability(
    capability_db_id: int,
    test_db_id: int,
    is_primary: bool = False,
    create_pseudo_criterion: bool = True,
) -> dict[str, Any]:
    """Link a test to a capability via criterion_tests junction.

    This creates an auto-generated criterion for the test and links it
    to the capability via capability_criteria.

    Args:
        capability_db_id: Database ID of the capability
        test_db_id: Database ID of the test
        is_primary: Whether this is the primary test for the capability
        create_pseudo_criterion: If False, skip creating pseudo-criterion
            (use when capability already has real criteria)

    Returns:
        Dict with capability_id, test_id, is_primary, created_at
    """
    from .criteria import (
        create_criterion,
        link_criterion_to_capability,
        link_test_to_criterion,
    )

    with get_connection() as conn:
        with conn.cursor() as cur:
            # Get capability and test info
            cur.execute(
                "SELECT project_id FROM capabilities WHERE id = %s",
                (capability_db_id,),
            )
            cap_row = cur.fetchone()
            if not cap_row:
                raise ValueError(f"Capability {capability_db_id} not found")
            project_id = cap_row[0]

            cur.execute("SELECT name FROM tests WHERE id = %s", (test_db_id,))
            test_row = cur.fetchone()
            if not test_row:
                raise ValueError(f"Test {test_db_id} not found")
            test_name = test_row[0]

            # Check if this test is already linked via criterion_tests
            cur.execute(
                """
                SELECT ct.criterion_id FROM criterion_tests ct
                JOIN capability_criteria cc ON ct.criterion_id = cc.criterion_id
                WHERE cc.capability_id = %s AND ct.test_id = %s
                """,
                (capability_db_id, test_db_id),
            )
            existing = cur.fetchone()
            if existing:
                # Already linked, just update is_primary
                cur.execute(
                    "UPDATE criterion_tests SET is_primary = %s WHERE criterion_id = %s AND test_id = %s",
                    (is_primary, existing[0], test_db_id),
                )
                conn.commit()
                return {
                    "capability_id": capability_db_id,
                    "test_id": test_db_id,
                    "is_primary": is_primary,
                    "created_at": None,
                }

        # Check if capability already has real criteria (non-pseudo)
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT 1 FROM acceptance_criteria ac
                JOIN capability_criteria cc ON ac.id = cc.criterion_id
                WHERE cc.capability_id = %s AND ac.criterion NOT LIKE 'Test passes: %%'
                LIMIT 1
                """,
                (capability_db_id,),
            )
            has_real_criteria = cur.fetchone() is not None

        # Skip pseudo-criterion creation if:
        # 1. Caller explicitly requested no pseudo-criterion, or
        # 2. Capability already has real criteria defined
        if not create_pseudo_criterion or has_real_criteria:
            return {
                "capability_id": capability_db_id,
                "test_id": test_db_id,
                "is_primary": is_primary,
                "created_at": None,
                "skipped_pseudo": True,
            }

        # Create a new criterion for this test (still inside the connection context)
        criterion = create_criterion(
            conn,
            project_id,
            f"Test passes: {test_name}",
            category="correctness",
            measurement="test",
        )
        criterion_db_id = criterion["id"]

        # Link criterion to capability and test
        link_criterion_to_capability(conn, capability_db_id, criterion_db_id)
        link_test_to_criterion(conn, criterion_db_id, test_db_id, is_primary)

        return {
            "capability_id": capability_db_id,
            "test_id": test_db_id,
            "is_primary": is_primary,
            "created_at": criterion["created_at"].isoformat()
            if criterion.get("created_at")
            else None,
        }


def unlink_test_from_capability(capability_db_id: int, test_db_id: int) -> bool:
    """Unlink a test from a capability via criterion_tests junction.

    Removes the criterion_tests link and deletes the criterion if orphaned.

    Returns:
        True if unlinked, False if link didn't exist.
    """
    from .criteria import check_and_delete_orphan

    with get_connection() as conn, conn.cursor() as cur:
        # Find the criterion linking this test to this capability
        cur.execute(
            """
            SELECT ct.criterion_id FROM criterion_tests ct
            JOIN capability_criteria cc ON ct.criterion_id = cc.criterion_id
            WHERE cc.capability_id = %s AND ct.test_id = %s
            """,
            (capability_db_id, test_db_id),
        )
        row = cur.fetchone()
        if not row:
            return False

        criterion_db_id = row[0]

        # Remove the test link
        cur.execute(
            "DELETE FROM criterion_tests WHERE criterion_id = %s AND test_id = %s",
            (criterion_db_id, test_db_id),
        )
        conn.commit()

        # Check if criterion is orphaned (no more tests linked)
        cur.execute(
            "SELECT 1 FROM criterion_tests WHERE criterion_id = %s LIMIT 1",
            (criterion_db_id,),
        )
        if not cur.fetchone():
            # No more tests, remove capability link and delete criterion
            cur.execute(
                "DELETE FROM capability_criteria WHERE criterion_id = %s",
                (criterion_db_id,),
            )
            check_and_delete_orphan(conn, criterion_db_id)

    return True


def get_tests_for_capability(
    project_id: str,
    capability_id: str,
) -> list[dict[str, Any]]:
    """Get all tests linked to a capability via criterion_tests.

    Args:
        project_id: Project ID
        capability_id: Capability ID (not database ID)

    Returns:
        List of test dicts with is_primary flag added.
    """
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT t.id, t.project_id, t.test_id, t.name, t.test_type, t.command, t.script,
                   t.config, t.working_dir, t.timeout_seconds, t.last_run_at, t.last_result,
                   t.last_duration_ms, t.last_output, t.last_error, t.run_count, t.pass_count,
                   t.fail_count, t.flaky_score, t.created_at, t.updated_at, ct.is_primary
            FROM tests t
            INNER JOIN criterion_tests ct ON t.id = ct.test_id
            INNER JOIN acceptance_criteria ac ON ct.criterion_id = ac.id
            INNER JOIN capability_criteria cc ON ac.id = cc.criterion_id
            INNER JOIN capabilities c ON cc.capability_id = c.id
            WHERE c.project_id = %s AND c.capability_id = %s
            ORDER BY ct.is_primary DESC, t.name ASC
            """,
            (project_id, capability_id),
        )
        rows = cur.fetchall()

    result = []
    for row in rows:
        test_dict = _row_to_dict(row[:21])
        test_dict["is_primary"] = row[21]
        result.append(test_dict)
    return result


def get_capabilities_for_test(
    project_id: str,
    test_id: str,
) -> list[dict[str, Any]]:
    """Get all capabilities linked to a test via criterion_tests.

    Args:
        project_id: Project ID
        test_id: Test ID (not database ID)

    Returns:
        List of capability dicts with is_primary flag added.
    """
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT c.id, c.project_id, c.component_id, c.capability_id, c.name, c.description,
                   c.priority, c.status, c.locked_at, c.created_at, c.updated_at, ct.is_primary
            FROM capabilities c
            INNER JOIN capability_criteria cc ON c.id = cc.capability_id
            INNER JOIN acceptance_criteria ac ON cc.criterion_id = ac.id
            INNER JOIN criterion_tests ct ON ac.id = ct.criterion_id
            INNER JOIN tests t ON ct.test_id = t.id
            WHERE t.project_id = %s AND t.test_id = %s
            ORDER BY c.name ASC
            """,
            (project_id, test_id),
        )
        rows = cur.fetchall()

    result = []
    for row in rows:
        cap_dict = {
            "id": row[0],
            "project_id": row[1],
            "component_id": row[2],
            "capability_id": row[3],
            "name": row[4],
            "description": row[5],
            "priority": row[6],
            "status": row[7],
            "locked_at": row[8].isoformat() if row[8] else None,
            "created_at": row[9].isoformat() if row[9] else None,
            "updated_at": row[10].isoformat() if row[10] else None,
            "is_primary": row[11],
        }
        result.append(cap_dict)
    return result


def _row_to_dict(row: tuple[Any, ...] | None) -> dict[str, Any]:
    """Convert a database row to a dict."""
    if row is None:
        return {}

    return {
        "id": row[0],
        "project_id": row[1],
        "test_id": row[2],
        "name": row[3],
        "test_type": row[4],
        "command": row[5],
        "script": row[6],
        "config": row[7] if isinstance(row[7], dict) else json.loads(row[7] or "{}"),
        "working_dir": row[8],
        "timeout_seconds": row[9],
        "last_run_at": row[10].isoformat() if row[10] else None,
        "last_result": row[11],
        "last_duration_ms": row[12],
        "last_output": row[13],
        "last_error": row[14],
        "run_count": row[15],
        "pass_count": row[16],
        "fail_count": row[17],
        "flaky_score": row[18],
        "created_at": row[19].isoformat() if row[19] else None,
        "updated_at": row[20].isoformat() if row[20] else None,
    }
