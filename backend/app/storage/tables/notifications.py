"""Notifications table for failure escalation alerts."""

import psycopg


def create_notifications_tables(cur: psycopg.Cursor) -> None:
    """Create notifications table and indexes."""
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS notifications (
            id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            task_id TEXT REFERENCES tasks(id) ON DELETE SET NULL,
            user_email TEXT,
            type VARCHAR(50) NOT NULL,
            title TEXT NOT NULL,
            message TEXT NOT NULL,
            severity VARCHAR(20) NOT NULL DEFAULT 'info',
            status VARCHAR(20) NOT NULL DEFAULT 'pending',
            metadata JSONB DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ DEFAULT NOW(),
            read_at TIMESTAMPTZ,
            dismissed_at TIMESTAMPTZ
        )
        """
    )

    # Create indexes
    cur.execute("CREATE INDEX IF NOT EXISTS idx_notification_project ON notifications(project_id)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_notification_status ON notifications(status)")
    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_notification_created ON notifications(created_at DESC)"
    )
    cur.execute("CREATE INDEX IF NOT EXISTS idx_notification_task ON notifications(task_id)")
    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_notification_user_email ON notifications(user_email)"
    )
