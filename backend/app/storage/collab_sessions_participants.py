from __future__ import annotations

from typing import Any

from .collab_sessions_common import insert_audit_event, touch_session
from .collab_sessions_rows import PARTICIPANT_COLUMNS, participant_from_row
from .connection import generate_prefixed_id, get_connection, get_cursor


def participant_key(
    *,
    actor_kind: str,
    display_name: str | None,
    role: str,
) -> str:
    display = (display_name or "operator").strip().lower()
    normalized = "-".join(display.split()) or "operator"
    return f"{actor_kind}:{role}:{normalized}"


def upsert_participant(
    *,
    session_id: str,
    actor_kind: str,
    display_name: str | None,
    role: str,
) -> dict[str, Any]:
    with get_connection() as conn, conn.cursor() as cur:
        row = upsert_participant_row(
            cur,
            session_id=session_id,
            actor_kind=actor_kind,
            display_name=display_name,
            role=role,
        )
        touch_session(cur, session_id)
        insert_audit_event(
            cur,
            session_id=session_id,
            actor_kind=actor_kind,
            action="participant-seen",
            detail={"role": role, "display_name": display_name},
        )
        conn.commit()
    return participant_from_row(row)


def upsert_participant_row(
    cur: Any,
    *,
    session_id: str,
    actor_kind: str,
    display_name: str | None,
    role: str,
) -> tuple[Any, ...]:
    cur.execute(
        f"""
        INSERT INTO collab_participants (
            participant_id, session_id, participant_key, actor_kind, display_name, role
        )
        VALUES (%s, %s, %s, %s, %s, %s)
        ON CONFLICT (session_id, participant_key) DO UPDATE
        SET display_name = EXCLUDED.display_name,
            role = EXCLUDED.role,
            status = 'active',
            last_seen_at = NOW()
        RETURNING {PARTICIPANT_COLUMNS}
        """,
        (
            generate_prefixed_id("participant"),
            session_id,
            participant_key(
                actor_kind=actor_kind,
                display_name=display_name,
                role=role,
            ),
            actor_kind,
            display_name,
            role,
        ),
    )
    row = cur.fetchone()
    assert row is not None
    return row


def list_participants(*, session_id: str, limit: int = 50) -> list[dict[str, Any]]:
    safe_limit = max(1, min(int(limit), 100))
    with get_cursor() as cur:
        cur.execute(
            f"""
            SELECT {PARTICIPANT_COLUMNS}
            FROM collab_participants
            WHERE session_id = %s
            ORDER BY last_seen_at DESC, joined_at DESC
            LIMIT %s
            """,
            (session_id, safe_limit),
        )
        rows = cur.fetchall()
    return [participant_from_row(row) for row in rows]
