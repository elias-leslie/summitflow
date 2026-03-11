"""Integration tests for maintenance retention helpers."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from app.storage.connection import get_connection
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
