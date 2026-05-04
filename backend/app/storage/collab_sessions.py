from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from .collab_sessions_artifacts import (
    create_annotation,
    create_evidence_packet,
    list_annotations,
    list_evidence_packets,
)
from .collab_sessions_common import (
    insert_audit_event,
    list_audit_events,
    revoke_connector_pairings_for_session,
)
from .collab_sessions_connectors import (
    claim_connector_pairing,
    create_connector_pairing,
    heartbeat_connector_pairing,
    list_connector_pairings,
    revoke_connector_pairing,
)
from .collab_sessions_participants import (
    list_participants,
    upsert_participant,
    upsert_participant_row,
)
from .collab_sessions_rows import SESSION_COLUMNS, session_from_row
from .connection import generate_prefixed_id, get_connection, get_cursor

__all__ = [
    "claim_connector_pairing",
    "create_annotation",
    "create_connector_pairing",
    "create_evidence_packet",
    "create_session",
    "get_session",
    "get_session_detail",
    "heartbeat_connector_pairing",
    "list_annotations",
    "list_audit_events",
    "list_connector_pairings",
    "list_evidence_packets",
    "list_participants",
    "list_sessions",
    "revoke_connector_pairing",
    "set_control_grant",
    "teardown_session",
    "upsert_participant",
]


def create_session(
    *,
    project_id: str | None,
    title: str,
    target_url: str | None,
    target_mode: str,
    agent_hub_session_id: str | None,
    sensitive: bool,
    created_by_display: str | None,
) -> dict[str, Any]:
    session_id = generate_prefixed_id("collab")
    with get_connection() as conn, conn.cursor() as cur:
        row = _insert_session_row(
            cur,
            session_id=session_id,
            project_id=project_id,
            title=title,
            target_url=target_url,
            target_mode=target_mode,
            agent_hub_session_id=agent_hub_session_id,
            sensitive=sensitive,
            created_by_display=created_by_display,
        )
        _bootstrap_session(cur, session_id, project_id, target_mode, agent_hub_session_id, created_by_display)
        conn.commit()
    assert row is not None
    return session_from_row(row)


def _insert_session_row(
    cur: Any,
    *,
    session_id: str,
    project_id: str | None,
    title: str,
    target_url: str | None,
    target_mode: str,
    agent_hub_session_id: str | None,
    sensitive: bool,
    created_by_display: str | None,
) -> tuple[Any, ...] | None:
    cur.execute(
        f"""
        INSERT INTO collab_sessions (
            session_id, project_id, title, target_url, target_mode,
            agent_hub_session_id, sensitive, evidence_policy, created_by_display
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        RETURNING {SESSION_COLUMNS}
        """,
        (
            session_id,
            project_id,
            title,
            target_url,
            target_mode,
            agent_hub_session_id,
            sensitive,
            "sensitive_blocked" if sensitive else "compact_only",
            created_by_display,
        ),
    )
    return cur.fetchone()


def _bootstrap_session(
    cur: Any,
    session_id: str,
    project_id: str | None,
    target_mode: str,
    agent_hub_session_id: str | None,
    created_by_display: str | None,
) -> None:
    upsert_participant_row(
        cur,
        session_id=session_id,
        actor_kind="user",
        display_name=created_by_display,
        role="controller",
    )
    insert_audit_event(
        cur,
        session_id=session_id,
        actor_kind="user",
        action="created",
        detail={
            "target_mode": target_mode,
            "project_id": project_id,
            "agent_hub_session_id": agent_hub_session_id,
        },
    )


def list_sessions(*, project_id: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
    safe_limit = max(1, min(int(limit), 250))
    if project_id is None:
        query = f"""
            SELECT {SESSION_COLUMNS}
            FROM collab_sessions
            ORDER BY created_at DESC, session_id DESC
            LIMIT %s
            """
        params: tuple[Any, ...] = (safe_limit,)
    else:
        query = f"""
            SELECT {SESSION_COLUMNS}
            FROM collab_sessions
            WHERE project_id = %s
            ORDER BY created_at DESC, session_id DESC
            LIMIT %s
            """
        params = (project_id, safe_limit)
    with get_cursor() as cur:
        cur.execute(query, params)
        rows = cur.fetchall()
    return [session_from_row(row) for row in rows]


def get_session(session_id: str) -> dict[str, Any] | None:
    with get_cursor() as cur:
        cur.execute(
            f"""
            SELECT {SESSION_COLUMNS}
            FROM collab_sessions
            WHERE session_id = %s
            """,
            (session_id,),
        )
        row = cur.fetchone()
    return session_from_row(row) if row else None


def get_session_detail(session_id: str) -> dict[str, Any] | None:
    session = get_session(session_id)
    if not session:
        return None
    session["participants"] = list_participants(session_id=session_id, limit=50)
    session["annotations"] = list_annotations(session_id=session_id, limit=100)
    session["evidence_packets"] = list_evidence_packets(session_id=session_id, limit=50)
    session["audit_events"] = list_audit_events(session_id=session_id, limit=50)
    return session


def set_control_grant(
    *,
    session_id: str,
    owner: str | None,
    ttl_seconds: int,
) -> dict[str, Any] | None:
    expires_at = datetime.now(UTC) + timedelta(seconds=max(1, min(ttl_seconds, 3600))) if owner else None
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            f"""
            UPDATE collab_sessions
            SET control_owner = %s,
                control_expires_at = %s,
                updated_at = NOW()
            WHERE session_id = %s AND state = 'active'
            RETURNING {SESSION_COLUMNS}
            """,
            (owner, expires_at, session_id),
        )
        row = cur.fetchone()
        if row:
            insert_audit_event(
                cur,
                session_id=session_id,
                actor_kind="user",
                action="control-granted" if owner else "control-released",
                detail={"owner": owner},
            )
        conn.commit()
    return session_from_row(row) if row else None


def teardown_session(session_id: str) -> dict[str, Any] | None:
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            f"""
            UPDATE collab_sessions
            SET state = 'closed',
                control_owner = NULL,
                control_expires_at = NULL,
                closed_at = NOW(),
                updated_at = NOW()
            WHERE session_id = %s
            RETURNING {SESSION_COLUMNS}
            """,
            (session_id,),
        )
        row = cur.fetchone()
        if row:
            revoked_count = revoke_connector_pairings_for_session(cur, session_id=session_id)
            insert_audit_event(
                cur,
                session_id=session_id,
                actor_kind="user",
                action="teardown",
                detail={"revoked_connector_pairings": revoked_count},
            )
        conn.commit()
    return session_from_row(row) if row else None
