"""Integration tests for notification deduplication windows."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.storage.connection import get_connection
from app.storage.notifications import _is_duplicate


def test_is_duplicate_respects_cooldown_minutes(ensure_test_project: str) -> None:
    project_id = ensure_test_project
    task_id = "task-dedup-window"
    notification_ids = ["notif-dedup-recent", "notif-dedup-old"]
    now = datetime.now(UTC)

    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO tasks (id, project_id, title, status)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (id) DO UPDATE SET project_id = EXCLUDED.project_id
            """,
            (task_id, project_id, "Dedup window task", "pending"),
        )
        cur.execute(
            "DELETE FROM notifications WHERE id = ANY(%s::text[])",
            (notification_ids,),
        )
        cur.execute(
            """
            INSERT INTO notifications (
                id, project_id, task_id, type, title, message, severity, status, metadata, created_at
            )
            VALUES
                (%s, %s, %s, 'task_failed', 'Recent notification', 'Recent notification', 'error', 'pending', '{}'::jsonb, %s),
                (%s, %s, %s, 'task_failed', 'Old notification', 'Old notification', 'error', 'pending', '{}'::jsonb, %s)
            """,
            (
                notification_ids[0],
                project_id,
                task_id,
                now - timedelta(minutes=10),
                notification_ids[1],
                project_id,
                task_id,
                now - timedelta(minutes=30),
            ),
        )
        conn.commit()

    try:
        assert _is_duplicate(
            project_id,
            "task_failed",
            "error",
            task_id,
            cooldown_minutes=5,
        ) is False
        assert _is_duplicate(
            project_id,
            "task_failed",
            "error",
            task_id,
            cooldown_minutes=60,
        ) is True
    finally:
        with get_connection() as conn, conn.cursor() as cur:
            cur.execute(
                "DELETE FROM notifications WHERE id = ANY(%s::text[])",
                (notification_ids,),
            )
            cur.execute("DELETE FROM tasks WHERE id = %s", (task_id,))
            conn.commit()
