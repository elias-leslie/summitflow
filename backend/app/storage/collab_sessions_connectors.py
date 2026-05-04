from __future__ import annotations

from datetime import datetime
from typing import Any

from psycopg.types.json import Jsonb

from .collab_sessions_common import (
    expire_connector_pairings,
    insert_audit_event,
    touch_session,
)
from .collab_sessions_participants import upsert_participant_row
from .collab_sessions_rows import (
    CONNECTOR_PAIRING_COLUMNS,
    CONNECTOR_PAIRING_JOIN_COLUMNS,
    connector_pairing_from_row,
)
from .connection import generate_prefixed_id, get_connection


def create_connector_pairing(
    *,
    session_id: str,
    pairing_token_hash: str,
    expires_at: datetime,
    connector_host: str | None,
    profile_label: str | None,
) -> dict[str, Any] | None:
    pairing_id = generate_prefixed_id("pairing")
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            f"""
            INSERT INTO collab_connector_pairings (
                pairing_id, session_id, pairing_token_hash, connector_host,
                profile_label, expires_at
            )
            SELECT %s, session_id, %s, %s, %s, %s
            FROM collab_sessions
            WHERE session_id = %s AND state = 'active'
            RETURNING {CONNECTOR_PAIRING_COLUMNS}
            """,
            (pairing_id, pairing_token_hash, connector_host, profile_label, expires_at, session_id),
        )
        row = cur.fetchone()
        if row:
            touch_session(cur, session_id)
            insert_audit_event(
                cur,
                session_id=session_id,
                actor_kind="user",
                action="connector-pairing-created",
                detail={"pairing_id": pairing_id, "expires_at": expires_at.isoformat()},
            )
        conn.commit()
    return connector_pairing_from_row(row) if row else None


def list_connector_pairings(*, session_id: str, limit: int = 50) -> list[dict[str, Any]]:
    safe_limit = max(1, min(int(limit), 100))
    with get_connection() as conn, conn.cursor() as cur:
        expire_connector_pairings(cur, session_id=session_id)
        cur.execute(
            f"""
            SELECT {CONNECTOR_PAIRING_COLUMNS}
            FROM collab_connector_pairings
            WHERE session_id = %s
            ORDER BY created_at DESC, pairing_id DESC
            LIMIT %s
            """,
            (session_id, safe_limit),
        )
        rows = cur.fetchall()
        conn.commit()
    return [connector_pairing_from_row(row) for row in rows]


def claim_connector_pairing(
    *,
    pairing_id: str,
    pairing_token_hash: str,
    connector_token_hash: str,
    connector_host: str | None,
    profile_label: str | None,
    connector_version: str | None,
) -> tuple[dict[str, Any] | None, str | None]:
    with get_connection() as conn, conn.cursor() as cur:
        expire_connector_pairings(cur)
        row = _fetch_pairing_for_update(cur, pairing_id, token_column="pairing_token_hash")
        if not row:
            conn.commit()
            return None, "not_found"
        pairing, stored_token, session_state = _parse_joined_pairing(row)
        error = _claim_preflight(pairing, stored_token, session_state, pairing_token_hash)
        if error:
            _record_claim_error(cur, pairing, pairing_id, error)
            conn.commit()
            return (None, error) if error == "invalid_token" else (pairing, error)
        claimed_row = _complete_pairing_claim(
            cur,
            pairing,
            pairing_id,
            connector_token_hash,
            connector_host,
            profile_label,
            connector_version,
        )
        conn.commit()
    return connector_pairing_from_row(claimed_row) if claimed_row else None, None


def heartbeat_connector_pairing(
    *,
    pairing_id: str,
    connector_token_hash: str,
    connector_state: dict[str, Any],
) -> tuple[dict[str, Any] | None, str | None]:
    with get_connection() as conn, conn.cursor() as cur:
        row = _fetch_pairing_for_update(cur, pairing_id, token_column="connector_token_hash")
        if not row:
            conn.commit()
            return None, "not_found"
        pairing, stored_token, session_state = _parse_joined_pairing(row)
        error = _heartbeat_preflight(pairing, stored_token, session_state, connector_token_hash)
        if error:
            if error == "invalid_token":
                _record_connector_token_error(cur, pairing, pairing_id)
            conn.commit()
            return (None, error) if error == "invalid_token" else (pairing, error)
        heartbeat_row = _update_connector_heartbeat(cur, pairing, pairing_id, connector_state)
        conn.commit()
    return connector_pairing_from_row(heartbeat_row) if heartbeat_row else None, None


def revoke_connector_pairing(*, pairing_id: str) -> dict[str, Any] | None:
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            f"""
            UPDATE collab_connector_pairings
            SET state = 'revoked',
                connector_token_hash = NULL,
                revoked_at = COALESCE(revoked_at, NOW()),
                updated_at = NOW()
            WHERE pairing_id = %s
            RETURNING {CONNECTOR_PAIRING_COLUMNS}
            """,
            (pairing_id,),
        )
        row = cur.fetchone()
        if row:
            pairing = connector_pairing_from_row(row)
            touch_session(cur, pairing["session_id"])
            insert_audit_event(
                cur,
                session_id=pairing["session_id"],
                actor_kind="user",
                action="connector-revoked",
                detail={"pairing_id": pairing_id},
            )
        conn.commit()
    return connector_pairing_from_row(row) if row else None


def _fetch_pairing_for_update(cur: Any, pairing_id: str, *, token_column: str) -> tuple[Any, ...] | None:
    cur.execute(
        f"""
        SELECT {CONNECTOR_PAIRING_JOIN_COLUMNS},
               {token_column},
               collab_sessions.state
        FROM collab_connector_pairings
        JOIN collab_sessions USING (session_id)
        WHERE pairing_id = %s
        FOR UPDATE OF collab_connector_pairings
        """,
        (pairing_id,),
    )
    return cur.fetchone()


def _parse_joined_pairing(row: tuple[Any, ...]) -> tuple[dict[str, Any], str | None, str]:
    return connector_pairing_from_row(row[:13]), row[13], row[14]


def _claim_preflight(
    pairing: dict[str, Any],
    stored_token: str | None,
    session_state: str,
    pairing_token_hash: str,
) -> str | None:
    if session_state != "active":
        return "session_closed"
    if pairing["state"] != "pending":
        return str(pairing["state"])
    return None if stored_token == pairing_token_hash else "invalid_token"


def _heartbeat_preflight(
    pairing: dict[str, Any],
    stored_token: str | None,
    session_state: str,
    connector_token_hash: str,
) -> str | None:
    if session_state != "active":
        return "session_closed"
    if pairing["state"] != "claimed":
        return str(pairing["state"])
    if not stored_token or stored_token != connector_token_hash:
        return "invalid_token"
    return None


def _record_claim_error(
    cur: Any,
    pairing: dict[str, Any],
    pairing_id: str,
    error: str,
) -> None:
    if error != "invalid_token":
        return
    insert_audit_event(
        cur,
        session_id=pairing["session_id"],
        actor_kind="agent",
        action="connector-pairing-rejected",
        detail={"pairing_id": pairing_id, "reason": "invalid_token"},
    )


def _complete_pairing_claim(
    cur: Any,
    pairing: dict[str, Any],
    pairing_id: str,
    connector_token_hash: str,
    connector_host: str | None,
    profile_label: str | None,
    connector_version: str | None,
) -> tuple[Any, ...] | None:
    cur.execute(
        f"""
        UPDATE collab_connector_pairings
        SET state = 'claimed', connector_token_hash = %s, connector_host = %s,
            profile_label = %s, connector_version = %s, claimed_at = NOW(),
            connector_last_seen_at = NOW(), updated_at = NOW()
        WHERE pairing_id = %s
        RETURNING {CONNECTOR_PAIRING_COLUMNS}
        """,
        (connector_token_hash, connector_host, profile_label, connector_version, pairing_id),
    )
    row = cur.fetchone()
    display_name = connector_host or profile_label or "Windows connector"
    upsert_participant_row(
        cur,
        session_id=pairing["session_id"],
        actor_kind="agent",
        display_name=display_name,
        role="observer",
    )
    touch_session(cur, pairing["session_id"])
    insert_audit_event(
        cur,
        session_id=pairing["session_id"],
        actor_kind="agent",
        action="connector-paired",
        detail={
            "pairing_id": pairing_id,
            "connector_host": connector_host,
            "profile_label": profile_label,
            "connector_version": connector_version,
        },
    )
    return row


def _record_connector_token_error(cur: Any, pairing: dict[str, Any], pairing_id: str) -> None:
    insert_audit_event(
        cur,
        session_id=pairing["session_id"],
        actor_kind="agent",
        action="connector-token-rejected",
        detail={"pairing_id": pairing_id},
    )


def _update_connector_heartbeat(
    cur: Any,
    pairing: dict[str, Any],
    pairing_id: str,
    connector_state: dict[str, Any],
) -> tuple[Any, ...] | None:
    cur.execute(
        f"""
        UPDATE collab_connector_pairings
        SET connector_state = %s,
            connector_last_seen_at = NOW(),
            updated_at = NOW()
        WHERE pairing_id = %s
        RETURNING {CONNECTOR_PAIRING_COLUMNS}
        """,
        (Jsonb(connector_state), pairing_id),
    )
    heartbeat_row = cur.fetchone()
    touch_session(cur, pairing["session_id"])
    return heartbeat_row
