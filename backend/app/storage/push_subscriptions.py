"""Push subscription storage - CRUD for Web Push subscriptions."""

from __future__ import annotations

import uuid
from typing import Any

from .connection import get_connection

_COLS = "id, user_email, endpoint, p256dh_key, auth_key, created_at, last_used_at"


def _row_to_dict(row: tuple[Any, ...]) -> dict[str, Any]:
    """Convert a database row to a dict."""
    keys = [k.strip() for k in _COLS.split(",")]
    return dict(zip(keys, row, strict=False))


def save_subscription(
    endpoint: str,
    p256dh_key: str,
    auth_key: str,
    user_email: str | None = None,
) -> dict[str, Any]:
    """Save or update a push subscription.

    Uses UPSERT on endpoint — re-subscribing the same browser updates keys.
    """
    sub_id = str(uuid.uuid4())[:8]

    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            f"""
            INSERT INTO push_subscriptions (id, user_email, endpoint, p256dh_key, auth_key)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (endpoint) DO UPDATE SET
                p256dh_key = EXCLUDED.p256dh_key,
                auth_key = EXCLUDED.auth_key,
                user_email = EXCLUDED.user_email
            RETURNING {_COLS}
            """,
            (sub_id, user_email, endpoint, p256dh_key, auth_key),
        )
        row = cur.fetchone()
        conn.commit()

    return _row_to_dict(row) if row else {}


def delete_subscription(endpoint: str) -> bool:
    """Remove a push subscription by endpoint."""
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            "DELETE FROM push_subscriptions WHERE endpoint = %s RETURNING id",
            (endpoint,),
        )
        result = cur.fetchone()
        conn.commit()

    return result is not None


def get_all_subscriptions() -> list[dict[str, Any]]:
    """Get all active push subscriptions.

    For single-user setup, returns all subscriptions.
    """
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(f"SELECT {_COLS} FROM push_subscriptions ORDER BY created_at DESC")
        rows = cur.fetchall()

    return [_row_to_dict(row) for row in rows]


def get_subscriptions_by_email(user_email: str) -> list[dict[str, Any]]:
    """Get push subscriptions for a specific user."""
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            f"SELECT {_COLS} FROM push_subscriptions WHERE user_email = %s",
            (user_email,),
        )
        rows = cur.fetchall()

    return [_row_to_dict(row) for row in rows]


def touch_subscription(endpoint: str) -> None:
    """Update last_used_at timestamp for a subscription."""
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            "UPDATE push_subscriptions SET last_used_at = NOW() WHERE endpoint = %s",
            (endpoint,),
        )
        conn.commit()
