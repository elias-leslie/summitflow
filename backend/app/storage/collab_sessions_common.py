from __future__ import annotations

from typing import Any

from psycopg.types.json import Jsonb

from .collab_sessions_rows import AUDIT_COLUMNS, audit_from_row
from .connection import generate_prefixed_id, get_cursor


def touch_session(cur: Any, session_id: str) -> None:
    cur.execute(
        "UPDATE collab_sessions SET updated_at = NOW() WHERE session_id = %s",
        (session_id,),
    )


def expire_connector_pairings(cur: Any, *, session_id: str | None = None) -> int:
    params: tuple[Any, ...]
    where_session = ""
    if session_id is None:
        params = ()
    else:
        where_session = "AND session_id = %s"
        params = (session_id,)
    cur.execute(
        f"""
        UPDATE collab_connector_pairings
        SET state = 'expired',
            updated_at = NOW()
        WHERE state = 'pending'
          AND expires_at <= NOW()
          {where_session}
        """,
        params,
    )
    return int(cur.rowcount or 0)


def revoke_connector_pairings_for_session(cur: Any, *, session_id: str) -> int:
    cur.execute(
        """
        UPDATE collab_connector_pairings
        SET state = 'revoked',
            connector_token_hash = NULL,
            revoked_at = COALESCE(revoked_at, NOW()),
            updated_at = NOW()
        WHERE session_id = %s
          AND state IN ('pending', 'claimed')
        """,
        (session_id,),
    )
    return int(cur.rowcount or 0)


def insert_audit_event(
    cur: Any,
    *,
    session_id: str,
    actor_kind: str,
    action: str,
    detail: dict[str, Any],
) -> None:
    cur.execute(
        """
        INSERT INTO collab_audit_events (
            audit_id,
            session_id,
            actor_kind,
            action,
            detail
        )
        VALUES (%s, %s, %s, %s, %s)
        """,
        (
            generate_prefixed_id("audit"),
            session_id,
            actor_kind,
            action,
            Jsonb(detail),
        ),
    )


def list_audit_events(*, session_id: str, limit: int = 50) -> list[dict[str, Any]]:
    safe_limit = max(1, min(int(limit), 100))
    with get_cursor() as cur:
        cur.execute(
            f"""
            SELECT {AUDIT_COLUMNS}
            FROM collab_audit_events
            WHERE session_id = %s
            ORDER BY created_at DESC, audit_id DESC
            LIMIT %s
            """,
            (session_id, safe_limit),
        )
        rows = cur.fetchall()
    return [audit_from_row(row) for row in rows]
