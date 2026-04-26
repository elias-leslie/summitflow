from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from psycopg.types.json import Jsonb

from .connection import generate_prefixed_id, get_connection, get_cursor

SESSION_COLUMNS = """
    session_id,
    project_id,
    title,
    target_url,
    target_mode,
    state,
    sensitive,
    control_owner,
    control_expires_at,
    browser_target_source,
    media_strategy,
    evidence_policy,
    created_by_kind,
    created_by_display,
    created_at,
    updated_at,
    closed_at
"""

PARTICIPANT_COLUMNS = """
    participant_id,
    session_id,
    participant_key,
    actor_kind,
    display_name,
    role,
    status,
    last_seen_at,
    joined_at
"""

ANNOTATION_COLUMNS = """
    annotation_id,
    session_id,
    kind,
    page_key,
    page_url_snapshot,
    selector,
    anchor,
    comment,
    created_by_kind,
    created_by_display,
    created_at
"""

EVIDENCE_COLUMNS = """
    evidence_id,
    session_id,
    annotation_id,
    title,
    url,
    page_url_snapshot,
    viewport,
    selector,
    bbox,
    context_summary,
    artifact_id,
    token_estimate,
    created_by_kind,
    created_by_display,
    created_at
"""

AUDIT_COLUMNS = """
    audit_id,
    session_id,
    actor_kind,
    action,
    detail,
    created_at
"""


def _iso(value: Any) -> str | None:
    return value.isoformat() if isinstance(value, datetime) else None


def _session_from_row(row: tuple[Any, ...]) -> dict[str, Any]:
    return {
        "session_id": row[0],
        "project_id": row[1],
        "title": row[2],
        "target_url": row[3],
        "target_mode": row[4],
        "state": row[5],
        "sensitive": row[6],
        "control_owner": row[7],
        "control_expires_at": _iso(row[8]),
        "browser_target_source": row[9],
        "media_strategy": row[10],
        "evidence_policy": row[11],
        "created_by_kind": row[12],
        "created_by_display": row[13],
        "created_at": _iso(row[14]),
        "updated_at": _iso(row[15]),
        "closed_at": _iso(row[16]),
    }


def _participant_from_row(row: tuple[Any, ...]) -> dict[str, Any]:
    return {
        "participant_id": row[0],
        "session_id": row[1],
        "participant_key": row[2],
        "actor_kind": row[3],
        "display_name": row[4],
        "role": row[5],
        "status": row[6],
        "last_seen_at": _iso(row[7]),
        "joined_at": _iso(row[8]),
    }


def _annotation_from_row(row: tuple[Any, ...]) -> dict[str, Any]:
    return {
        "annotation_id": row[0],
        "session_id": row[1],
        "kind": row[2],
        "page_key": row[3],
        "page_url_snapshot": row[4],
        "selector": row[5],
        "anchor": row[6] or {},
        "comment": row[7],
        "created_by_kind": row[8],
        "created_by_display": row[9],
        "created_at": _iso(row[10]),
    }


def _evidence_from_row(row: tuple[Any, ...]) -> dict[str, Any]:
    return {
        "evidence_id": row[0],
        "session_id": row[1],
        "annotation_id": row[2],
        "title": row[3],
        "url": row[4],
        "page_url_snapshot": row[5],
        "viewport": row[6] or {},
        "selector": row[7],
        "bbox": row[8],
        "context_summary": row[9],
        "artifact_id": row[10],
        "token_estimate": row[11],
        "created_by_kind": row[12],
        "created_by_display": row[13],
        "created_at": _iso(row[14]),
    }


def _audit_from_row(row: tuple[Any, ...]) -> dict[str, Any]:
    return {
        "audit_id": row[0],
        "session_id": row[1],
        "actor_kind": row[2],
        "action": row[3],
        "detail": row[4] or {},
        "created_at": _iso(row[5]),
    }


def create_session(
    *,
    project_id: str | None,
    title: str,
    target_url: str | None,
    target_mode: str,
    sensitive: bool,
    created_by_display: str | None,
) -> dict[str, Any]:
    session_id = generate_prefixed_id("collab")
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            f"""
            INSERT INTO collab_sessions (
                session_id,
                project_id,
                title,
                target_url,
                target_mode,
                sensitive,
                evidence_policy,
                created_by_display
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING {SESSION_COLUMNS}
            """,
            (
                session_id,
                project_id,
                title,
                target_url,
                target_mode,
                sensitive,
                "sensitive_blocked" if sensitive else "compact_only",
                created_by_display,
            ),
        )
        row = cur.fetchone()
        _upsert_participant(
            cur,
            session_id=session_id,
            actor_kind="user",
            display_name=created_by_display,
            role="controller",
        )
        _insert_audit_event(
            cur,
            session_id=session_id,
            actor_kind="user",
            action="created",
            detail={"target_mode": target_mode, "project_id": project_id},
        )
        conn.commit()
    assert row is not None
    return _session_from_row(row)


def list_sessions(*, project_id: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
    safe_limit = max(1, min(int(limit), 250))
    if project_id is None:
        with get_cursor() as cur:
            cur.execute(
                f"""
                SELECT {SESSION_COLUMNS}
                FROM collab_sessions
                ORDER BY created_at DESC, session_id DESC
                LIMIT %s
                """,
                (safe_limit,),
            )
            rows = cur.fetchall()
    else:
        with get_cursor() as cur:
            cur.execute(
                f"""
                SELECT {SESSION_COLUMNS}
                FROM collab_sessions
                WHERE project_id = %s
                ORDER BY created_at DESC, session_id DESC
                LIMIT %s
                """,
                (project_id, safe_limit),
            )
            rows = cur.fetchall()
    return [_session_from_row(row) for row in rows]


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
    return _session_from_row(row) if row else None


def get_session_detail(session_id: str) -> dict[str, Any] | None:
    session = get_session(session_id)
    if not session:
        return None
    session["participants"] = list_participants(session_id=session_id, limit=50)
    session["annotations"] = list_annotations(session_id=session_id, limit=100)
    session["evidence_packets"] = list_evidence_packets(session_id=session_id, limit=50)
    session["audit_events"] = list_audit_events(session_id=session_id, limit=50)
    return session


def _participant_key(
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
        row = _upsert_participant(
            cur,
            session_id=session_id,
            actor_kind=actor_kind,
            display_name=display_name,
            role=role,
        )
        _touch_session(cur, session_id)
        _insert_audit_event(
            cur,
            session_id=session_id,
            actor_kind=actor_kind,
            action="participant-seen",
            detail={"role": role, "display_name": display_name},
        )
        conn.commit()
    return _participant_from_row(row)


def _upsert_participant(
    cur: Any,
    *,
    session_id: str,
    actor_kind: str,
    display_name: str | None,
    role: str,
) -> tuple[Any, ...]:
    participant_key = _participant_key(
        actor_kind=actor_kind,
        display_name=display_name,
        role=role,
    )
    cur.execute(
        f"""
        INSERT INTO collab_participants (
            participant_id,
            session_id,
            participant_key,
            actor_kind,
            display_name,
            role
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
            participant_key,
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
    return [_participant_from_row(row) for row in rows]


def create_annotation(
    *,
    session_id: str,
    kind: str,
    page_key: str | None,
    page_url_snapshot: str | None,
    selector: str | None,
    anchor: dict[str, Any],
    comment: str,
    created_by_display: str | None,
) -> dict[str, Any]:
    annotation_id = generate_prefixed_id("annotation")
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            f"""
            INSERT INTO collab_annotations (
                annotation_id,
                session_id,
                kind,
                page_key,
                page_url_snapshot,
                selector,
                anchor,
                comment,
                created_by_display
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING {ANNOTATION_COLUMNS}
            """,
            (
                annotation_id,
                session_id,
                kind,
                page_key,
                page_url_snapshot,
                selector,
                Jsonb(anchor),
                comment,
                created_by_display,
            ),
        )
        row = cur.fetchone()
        _touch_session(cur, session_id)
        _insert_audit_event(
            cur,
            session_id=session_id,
            actor_kind="user",
            action="annotation-created",
            detail={"annotation_id": annotation_id, "kind": kind},
        )
        conn.commit()
    assert row is not None
    return _annotation_from_row(row)


def list_annotations(*, session_id: str, limit: int = 100) -> list[dict[str, Any]]:
    safe_limit = max(1, min(int(limit), 250))
    with get_cursor() as cur:
        cur.execute(
            f"""
            SELECT {ANNOTATION_COLUMNS}
            FROM collab_annotations
            WHERE session_id = %s
            ORDER BY created_at DESC, annotation_id DESC
            LIMIT %s
            """,
            (session_id, safe_limit),
        )
        rows = cur.fetchall()
    return [_annotation_from_row(row) for row in rows]


def create_evidence_packet(
    *,
    session_id: str,
    annotation_id: str | None,
    title: str | None,
    url: str | None,
    page_url_snapshot: str | None,
    viewport: dict[str, Any],
    selector: str | None,
    bbox: dict[str, Any] | None,
    context_summary: str,
    artifact_id: str | None,
    created_by_display: str | None,
) -> dict[str, Any]:
    evidence_id = generate_prefixed_id("evidence")
    token_estimate = max(1, len(context_summary) // 4)
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            f"""
            INSERT INTO collab_evidence_packets (
                evidence_id,
                session_id,
                annotation_id,
                title,
                url,
                page_url_snapshot,
                viewport,
                selector,
                bbox,
                context_summary,
                artifact_id,
                token_estimate,
                created_by_display
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING {EVIDENCE_COLUMNS}
            """,
            (
                evidence_id,
                session_id,
                annotation_id,
                title,
                url,
                page_url_snapshot,
                Jsonb(viewport),
                selector,
                Jsonb(bbox) if bbox is not None else None,
                context_summary,
                artifact_id,
                token_estimate,
                created_by_display,
            ),
        )
        row = cur.fetchone()
        _touch_session(cur, session_id)
        _insert_audit_event(
            cur,
            session_id=session_id,
            actor_kind="user",
            action="evidence-created",
            detail={"evidence_id": evidence_id, "token_estimate": token_estimate},
        )
        conn.commit()
    assert row is not None
    return _evidence_from_row(row)


def list_evidence_packets(*, session_id: str, limit: int = 50) -> list[dict[str, Any]]:
    safe_limit = max(1, min(int(limit), 100))
    with get_cursor() as cur:
        cur.execute(
            f"""
            SELECT {EVIDENCE_COLUMNS}
            FROM collab_evidence_packets
            WHERE session_id = %s
            ORDER BY created_at DESC, evidence_id DESC
            LIMIT %s
            """,
            (session_id, safe_limit),
        )
        rows = cur.fetchall()
    return [_evidence_from_row(row) for row in rows]


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
            _insert_audit_event(
                cur,
                session_id=session_id,
                actor_kind="user",
                action="control-granted" if owner else "control-released",
                detail={"owner": owner},
            )
        conn.commit()
    return _session_from_row(row) if row else None


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
            _insert_audit_event(
                cur,
                session_id=session_id,
                actor_kind="user",
                action="teardown",
                detail={},
            )
        conn.commit()
    return _session_from_row(row) if row else None


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
    return [_audit_from_row(row) for row in rows]


def _touch_session(cur: Any, session_id: str) -> None:
    cur.execute(
        "UPDATE collab_sessions SET updated_at = NOW() WHERE session_id = %s",
        (session_id,),
    )


def _insert_audit_event(
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
