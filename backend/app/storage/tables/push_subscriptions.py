"""Push subscriptions table for Web Push API."""

import psycopg


def create_push_subscriptions_table(cur: psycopg.Cursor) -> None:
    """Create push_subscriptions table and indexes."""
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS push_subscriptions (
            id TEXT PRIMARY KEY,
            user_email TEXT,
            endpoint TEXT NOT NULL UNIQUE,
            p256dh_key TEXT NOT NULL,
            auth_key TEXT NOT NULL,
            created_at TIMESTAMPTZ DEFAULT NOW(),
            last_used_at TIMESTAMPTZ
        )
        """
    )

    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_push_sub_user_email ON push_subscriptions(user_email)"
    )
    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_push_sub_endpoint ON push_subscriptions(endpoint)"
    )
