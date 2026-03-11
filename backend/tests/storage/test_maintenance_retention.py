"""Integration tests for maintenance retention helpers."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from app.storage.celery_results import cleanup_old_celery_results
from app.storage.connection import generate_prefixed_id, get_connection
from app.storage.events import cleanup_old_events
from app.storage.maintenance_runs import cleanup_old_maintenance_runs, record_maintenance_run
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


def _ensure_celery_result_tables(conn: Any) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS celery_taskmeta (
                id INTEGER PRIMARY KEY,
                task_id VARCHAR UNIQUE,
                status VARCHAR,
                result BYTEA,
                date_done TIMESTAMP,
                traceback TEXT,
                name VARCHAR,
                args BYTEA,
                kwargs BYTEA,
                worker VARCHAR,
                retries INTEGER,
                queue VARCHAR
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS celery_tasksetmeta (
                id INTEGER PRIMARY KEY,
                taskset_id VARCHAR UNIQUE,
                result BYTEA,
                date_done TIMESTAMP
            )
            """
        )
        conn.commit()


class TestNotificationRetention:
    """Notification cleanup removes only old terminal rows."""

    def test_cleanup_old_notifications_keeps_pending(self, ensure_test_project: str) -> None:
        project_id = ensure_test_project
        old_read_id = "notif-old-read"
        old_dismissed_id = "notif-old-dismissed"
        pending_id = "notif-pending"
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
                notification_id=pending_id,
                project_id=project_id,
                status="pending",
                created_at=now - timedelta(days=100),
            )

        result = cleanup_old_notifications(max_read_age_days=30, max_dismissed_age_days=14)

        assert result == {"read_deleted": 1, "dismissed_deleted": 1}

        with get_connection() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT id FROM notifications WHERE id = ANY(%s::text[]) ORDER BY id",
                ([old_read_id, old_dismissed_id, pending_id],),
            )
            remaining = [row[0] for row in cur.fetchall()]
            cur.execute("DELETE FROM notifications WHERE id = ANY(%s::text[])", ([pending_id],))
            conn.commit()

        assert remaining == [pending_id]


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


class TestCeleryResultRetention:
    """Celery result cleanup covers task and task-group metadata tables."""

    def test_cleanup_old_celery_results_prunes_old_taskmeta_and_tasksetmeta(self) -> None:
        with get_connection() as conn:
            _ensure_celery_result_tables(conn)
            with conn.cursor() as cur:
                cur.execute("DELETE FROM celery_taskmeta WHERE id = ANY(%s::int[])", ([900001, 900002],))
                cur.execute(
                    "DELETE FROM celery_tasksetmeta WHERE id = ANY(%s::int[])",
                    ([910001, 910002],),
                )
                cur.execute(
                    """
                    INSERT INTO celery_taskmeta (id, task_id, status, date_done)
                    VALUES
                        (900001, 'taskmeta-old', 'SUCCESS', NOW() - INTERVAL '45 days'),
                        (900002, 'taskmeta-new', 'SUCCESS', NOW() - INTERVAL '5 days')
                    """
                )
                cur.execute(
                    """
                    INSERT INTO celery_tasksetmeta (id, taskset_id, date_done)
                    VALUES
                        (910001, 'taskset-old', NOW() - INTERVAL '45 days'),
                        (910002, 'taskset-new', NOW() - INTERVAL '5 days')
                    """
                )
                conn.commit()

        result = cleanup_old_celery_results(max_task_age_days=30, max_group_age_days=30)

        assert result == {
            "taskmeta_deleted": 1,
            "tasksetmeta_deleted": 1,
        }

        with get_connection() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT id FROM celery_taskmeta WHERE id = ANY(%s::int[]) ORDER BY id",
                ([900001, 900002],),
            )
            remaining_taskmeta = [row[0] for row in cur.fetchall()]
            cur.execute(
                "SELECT id FROM celery_tasksetmeta WHERE id = ANY(%s::int[]) ORDER BY id",
                ([910001, 910002],),
            )
            remaining_tasksetmeta = [row[0] for row in cur.fetchall()]
            cur.execute("DELETE FROM celery_taskmeta WHERE id = ANY(%s::int[])", ([900002],))
            cur.execute("DELETE FROM celery_tasksetmeta WHERE id = ANY(%s::int[])", ([910002],))
            conn.commit()

        assert remaining_taskmeta == [900002]
        assert remaining_tasksetmeta == [910002]


class TestMaintenanceRunRetention:
    """Maintenance run ledger cleanup stays bounded per workflow."""

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
            scan_id = cur.fetchone()[0]
            conn.commit()

        updated = fail_stale_running_scans(max_age_hours=6)

        assert updated >= 1

        with get_connection() as conn, conn.cursor() as cur:
            cur.execute("SELECT status, completed_at FROM scan_history WHERE id = %s", (scan_id,))
            status, completed_at = cur.fetchone()
            cur.execute("DELETE FROM scan_history WHERE id = %s", (scan_id,))
            conn.commit()

        assert status == "failed"
        assert completed_at is not None

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
