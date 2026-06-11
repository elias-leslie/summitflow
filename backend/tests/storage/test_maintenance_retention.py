"""Integration tests for maintenance retention helpers."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from app.storage.connection import generate_prefixed_id, get_connection
from app.storage.events import cleanup_old_events
from app.storage.maintenance_runs import (
    cleanup_old_maintenance_runs,
    list_maintenance_runs,
    record_maintenance_run,
)
from app.storage.notifications import cleanup_old_notifications
from app.storage.quality_check_results import cleanup_old_results, create_check_result, mark_fixed
from app.storage.scan_history import cleanup_old_scan_history, fail_stale_running_scans


def _insert_notification(
    conn: Any,
    *,
    notification_id: str,
    project_id: str,
    status: str,
    created_at: datetime,
    read_at: datetime | None = None,
    dismissed_at: datetime | None = None,
) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO notifications (
                id, project_id, type, title, message, severity, status,
                metadata, created_at, read_at, dismissed_at
            )
            VALUES (%s, %s, 'system', %s, %s, 'info', %s, '{}'::jsonb, %s, %s, %s)
            """,
            (
                notification_id,
                project_id,
                notification_id,
                notification_id,
                status,
                created_at,
                read_at,
                dismissed_at,
            ),
        )
        conn.commit()


def _insert_task(
    conn: Any,
    *,
    task_id: str,
    project_id: str,
    status: str,
) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO tasks (id, project_id, title, status)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (id) DO UPDATE SET status = EXCLUDED.status
            """,
            (task_id, project_id, task_id, status),
        )
        conn.commit()


def _insert_event(
    conn: Any,
    *,
    project_id: str,
    trace_id: str,
    visibility: str,
    timestamp: datetime,
    message: str,
) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO events (
                project_id, trace_id, span_id, event_type, source, level,
                visibility, message, attributes, timestamp
            )
            VALUES (%s, %s, %s, 'log', 'test', 'info', %s, %s, '{}'::jsonb, %s)
            """,
            (project_id, trace_id, f"span-{message}", visibility, message, timestamp),
        )
        conn.commit()


class TestNotificationRetention:
    """Notification cleanup removes only old terminal rows."""

    def test_cleanup_old_notifications_prunes_old_pending(self, ensure_test_project: str) -> None:
        project_id = ensure_test_project
        old_read_id = "notif-old-read"
        old_dismissed_id = "notif-old-dismissed"
        old_pending_id = "notif-pending-old"
        recent_pending_id = "notif-pending-recent"
        now = datetime.now(UTC)

        with get_connection() as conn:
            _insert_notification(
                conn,
                notification_id=old_read_id,
                project_id=project_id,
                status="read",
                created_at=now - timedelta(days=50),
                read_at=now - timedelta(days=50),
            )
            _insert_notification(
                conn,
                notification_id=old_dismissed_id,
                project_id=project_id,
                status="dismissed",
                created_at=now - timedelta(days=20),
                dismissed_at=now - timedelta(days=20),
            )
            _insert_notification(
                conn,
                notification_id=old_pending_id,
                project_id=project_id,
                status="pending",
                created_at=now - timedelta(days=100),
            )
            _insert_notification(
                conn,
                notification_id=recent_pending_id,
                project_id=project_id,
                status="pending",
                created_at=now - timedelta(days=10),
            )

        result = cleanup_old_notifications(
            max_read_age_days=30,
            max_dismissed_age_days=14,
            max_pending_age_days=90,
        )

        assert result == {"read_deleted": 1, "dismissed_deleted": 1, "pending_deleted": 1}

        with get_connection() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT id FROM notifications WHERE id = ANY(%s::text[]) ORDER BY id",
                ([old_read_id, old_dismissed_id, old_pending_id, recent_pending_id],),
            )
            remaining = [row[0] for row in cur.fetchall()]
            cur.execute(
                "DELETE FROM notifications WHERE id = ANY(%s::text[])",
                ([recent_pending_id],),
            )
            conn.commit()

        assert remaining == [recent_pending_id]


class TestQualityCheckRetention:
    """Quality result cleanup prunes old resolved/pass rows while retaining active failures."""

    def test_cleanup_old_results_keeps_unfixed_failures(self, ensure_test_project: str) -> None:
        project_id = ensure_test_project

        with get_connection() as conn:
            old_pass = create_check_result(conn, project_id, "ruff", "pass")
            fixed_fail = create_check_result(conn, project_id, "types", "fail")
            open_fail = create_check_result(conn, project_id, "pytest", "fail")
            mark_fixed(conn, fixed_fail["id"], "tester")
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE quality_check_results
                    SET created_at = NOW() - INTERVAL '40 days'
                    WHERE id = %s
                    """,
                    (old_pass["id"],),
                )
                cur.execute(
                    """
                    UPDATE quality_check_results
                    SET fixed_at = NOW() - INTERVAL '50 days', updated_at = NOW() - INTERVAL '50 days'
                    WHERE id = %s
                    """,
                    (fixed_fail["id"],),
                )
                conn.commit()

        result = cleanup_old_results(max_pass_age_days=21, max_fixed_age_days=30)

        assert result["pass_deleted"] == 1
        assert result["fixed_deleted"] == 1

        with get_connection() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT id FROM quality_check_results WHERE id = ANY(%s::int[]) ORDER BY id",
                ([old_pass["id"], fixed_fail["id"], open_fail["id"]],),
            )
            remaining = [row[0] for row in cur.fetchall()]
            cur.execute(
                "DELETE FROM quality_check_results WHERE id = ANY(%s::int[])",
                ([open_fail["id"]],),
            )
            conn.commit()

        assert remaining == [open_fail["id"]]


class TestEventRetention:
    """Event cleanup keeps active traces and recent user context."""

    def test_cleanup_old_events_preserves_active_and_latest_user_trace_context(
        self, ensure_test_project: str
    ) -> None:
        project_id = ensure_test_project
        completed_task_id = "task-event-retention-completed"
        active_task_id = "task-event-retention-active"
        older = datetime.now(UTC) - timedelta(days=40)
        newer = datetime.now(UTC) - timedelta(days=39)

        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM events WHERE trace_id = ANY(%s::text[])", ([completed_task_id, active_task_id],))
                cur.execute("DELETE FROM tasks WHERE id = ANY(%s::text[])", ([completed_task_id, active_task_id],))
                conn.commit()
            _insert_task(conn, task_id=completed_task_id, project_id=project_id, status="completed")
            _insert_task(conn, task_id=active_task_id, project_id=project_id, status="running")
            _insert_event(
                conn,
                project_id=project_id,
                trace_id=completed_task_id,
                visibility="user",
                timestamp=older,
                message="completed-older-user",
            )
            _insert_event(
                conn,
                project_id=project_id,
                trace_id=completed_task_id,
                visibility="user",
                timestamp=newer,
                message="completed-newer-user",
            )
            _insert_event(
                conn,
                project_id=project_id,
                trace_id=completed_task_id,
                visibility="internal",
                timestamp=older,
                message="completed-old-internal",
            )
            _insert_event(
                conn,
                project_id=project_id,
                trace_id=active_task_id,
                visibility="internal",
                timestamp=older,
                message="active-old-internal",
            )

        result = cleanup_old_events(
            max_internal_age_days=14,
            max_user_age_days=30,
            recent_trace_age_days=7,
            keep_latest_user_per_trace=1,
        )

        assert result["user_deleted"] >= 1
        assert result["internal_deleted"] >= 1
        assert result["total_deleted"] >= 2

        with get_connection() as conn, conn.cursor() as cur:
            cur.execute(
                """
                SELECT message
                FROM events
                WHERE trace_id = ANY(%s::text[])
                ORDER BY message
                """,
                ([completed_task_id, active_task_id],),
            )
            remaining = [row[0] for row in cur.fetchall()]
            cur.execute("DELETE FROM events WHERE trace_id = ANY(%s::text[])", ([completed_task_id, active_task_id],))
            cur.execute("DELETE FROM tasks WHERE id = ANY(%s::text[])", ([completed_task_id, active_task_id],))
            conn.commit()

        assert remaining == ["active-old-internal", "completed-newer-user"]


class TestMaintenanceRunRetention:
    """Maintenance run ledger cleanup stays bounded per workflow."""

    def test_list_maintenance_runs_can_filter_by_project_summary(self) -> None:
        workflow_name = f"test-maintenance-{generate_prefixed_id('wf')}"
        started_at = datetime.now(UTC)
        run_a = record_maintenance_run(
            workflow_name,
            "completed",
            started_at=started_at,
            finished_at=started_at,
            summary={"project_id": "project-a", "tasks_created": 1},
        )
        run_b = record_maintenance_run(
            workflow_name,
            "completed",
            started_at=started_at,
            finished_at=started_at,
            summary={"project_id": "project-b", "tasks_created": 1},
        )

        assert run_a is not None
        assert run_b is not None

        runs = list_maintenance_runs(
            workflow_name=workflow_name,
            project_id="project-a",
        )

        with get_connection() as conn, conn.cursor() as cur:
            cur.execute("DELETE FROM maintenance_runs WHERE id = ANY(%s::bigint[])", ([run_a["id"], run_b["id"]],))
            conn.commit()

        assert [run["id"] for run in runs] == [run_a["id"]]

    def test_cleanup_old_maintenance_runs_keeps_recent_history(self) -> None:
        workflow_name = f"test-maintenance-{generate_prefixed_id('wf')}"
        older = datetime.now(UTC) - timedelta(days=220)
        newer = datetime.now(UTC) - timedelta(days=2)

        old_run = record_maintenance_run(
            workflow_name,
            "success",
            started_at=older,
            finished_at=older,
            rows_cleaned=1,
            summary={"marker": "old"},
        )
        new_run = record_maintenance_run(
            workflow_name,
            "success",
            started_at=newer,
            finished_at=newer,
            rows_cleaned=2,
            summary={"marker": "new"},
        )

        assert old_run is not None
        assert new_run is not None

        deleted = cleanup_old_maintenance_runs(max_age_days=180, keep_latest_per_workflow=1)

        assert deleted >= 1

        with get_connection() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT id FROM maintenance_runs WHERE id = ANY(%s::bigint[]) ORDER BY id",
                ([old_run["id"], new_run["id"]],),
            )
            remaining = [row[0] for row in cur.fetchall()]
            cur.execute("DELETE FROM maintenance_runs WHERE id = %s", (new_run["id"],))
            conn.commit()

        assert remaining == [new_run["id"]]


class TestScanHistoryRetention:
    """Scan maintenance recovers stale runs and prunes old unreferenced history."""

    def test_fail_stale_running_scans_marks_row_failed(self, ensure_test_project: str) -> None:
        project_id = ensure_test_project
        with get_connection() as conn, conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO scan_history (project_id, scan_type, triggered_by, started_at, status)
                VALUES (%s, 'file', 'manual', NOW() - INTERVAL '8 hours', 'running')
                RETURNING id
                """,
                (project_id,),
            )
            row = cur.fetchone()
            assert row is not None
            scan_id = row[0]
            conn.commit()

        updated = fail_stale_running_scans(max_age_hours=6)

        assert updated >= 1

        with get_connection() as conn, conn.cursor() as cur:
            cur.execute("SELECT status, completed_at FROM scan_history WHERE id = %s", (scan_id,))
            row = cur.fetchone()
            assert row is not None
            status, completed_at = row
            cur.execute("DELETE FROM scan_history WHERE id = %s", (scan_id,))
            conn.commit()

        assert status == "failed"
        assert completed_at is not None

    def test_fail_stale_running_scans_recovers_stuck_scan_state(self, ensure_test_project: str) -> None:
        """A scan_states row stuck in 'running' blocks all future scans
        (ensure_scan_not_running); maintenance must recover it, not just scan_history."""
        project_id = ensure_test_project
        with get_connection() as conn, conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO scan_states (project_id, status, started_at, updated_at)
                VALUES (%s, 'running', NOW() - INTERVAL '8 hours', NOW() - INTERVAL '8 hours')
                ON CONFLICT (project_id) DO UPDATE SET
                    status = EXCLUDED.status,
                    started_at = EXCLUDED.started_at,
                    completed_at = NULL,
                    error = NULL,
                    updated_at = EXCLUDED.updated_at
                """,
                (project_id,),
            )
            conn.commit()

        updated = fail_stale_running_scans(max_age_hours=6)

        assert updated >= 1

        with get_connection() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT status, completed_at, error FROM scan_states WHERE project_id = %s",
                (project_id,),
            )
            row = cur.fetchone()
            cur.execute("DELETE FROM scan_states WHERE project_id = %s", (project_id,))
            conn.commit()

        assert row is not None
        status, completed_at, error = row
        assert status == "failed"
        assert completed_at is not None
        assert "Auto-failed by maintenance" in error

    def test_fail_stale_running_scans_keeps_fresh_running_scan_state(self, ensure_test_project: str) -> None:
        project_id = ensure_test_project
        with get_connection() as conn, conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO scan_states (project_id, status, started_at, updated_at)
                VALUES (%s, 'running', NOW() - INTERVAL '5 minutes', NOW())
                ON CONFLICT (project_id) DO UPDATE SET
                    status = EXCLUDED.status,
                    started_at = EXCLUDED.started_at,
                    completed_at = NULL,
                    error = NULL,
                    updated_at = EXCLUDED.updated_at
                """,
                (project_id,),
            )
            conn.commit()

        fail_stale_running_scans(max_age_hours=6)

        with get_connection() as conn, conn.cursor() as cur:
            cur.execute("SELECT status FROM scan_states WHERE project_id = %s", (project_id,))
            row = cur.fetchone()
            cur.execute("DELETE FROM scan_states WHERE project_id = %s", (project_id,))
            conn.commit()

        assert row is not None
        assert row[0] == "running"

    def test_cleanup_old_scan_history_preserves_recent_rows(self, ensure_test_project: str) -> None:
        project_id = ensure_test_project
        with get_connection() as conn, conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO scan_history (
                    project_id, scan_type, triggered_by, started_at, completed_at, duration_ms, status
                )
                VALUES
                    (%s, 'file', 'manual', NOW() - INTERVAL '120 days', NOW() - INTERVAL '120 days', 100, 'completed'),
                    (%s, 'file', 'manual', NOW() - INTERVAL '5 days', NOW() - INTERVAL '5 days', 100, 'completed')
                RETURNING id
                """,
                (project_id, project_id),
            )
            old_id, recent_id = [row[0] for row in cur.fetchall()]
            conn.commit()

        deleted = cleanup_old_scan_history(max_age_days=30, keep_latest_per_type=1)

        assert deleted == 1

        with get_connection() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT id FROM scan_history WHERE id = ANY(%s::int[]) ORDER BY id",
                ([old_id, recent_id],),
            )
            remaining = [row[0] for row in cur.fetchall()]
            cur.execute("DELETE FROM scan_history WHERE id = %s", (recent_id,))
            conn.commit()

        assert remaining == [recent_id]
