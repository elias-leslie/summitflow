from __future__ import annotations

from typing import Any

from psycopg.types.json import Jsonb

from .collab_sessions_common import insert_audit_event, touch_session
from .collab_sessions_rows import (
    ANNOTATION_COLUMNS,
    EVIDENCE_COLUMNS,
    annotation_from_row,
    evidence_from_row,
)
from .connection import generate_prefixed_id, get_connection, get_cursor


def create_annotation(
    *,
    session_id: str,
    kind: str,
    page_key: str | None,
    page_url_snapshot: str | None,
    selector: str | None,
    anchor: dict[str, Any],
    comment: str,
    created_by_kind: str,
    created_by_display: str | None,
) -> dict[str, Any]:
    annotation_id = generate_prefixed_id("annotation")
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            f"""
            INSERT INTO collab_annotations (
                annotation_id, session_id, kind, page_key, page_url_snapshot,
                selector, anchor, comment, created_by_kind, created_by_display
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
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
                created_by_kind,
                created_by_display,
            ),
        )
        row = cur.fetchone()
        touch_session(cur, session_id)
        insert_audit_event(
            cur,
            session_id=session_id,
            actor_kind=created_by_kind,
            action="annotation-created",
            detail={"annotation_id": annotation_id, "kind": kind},
        )
        conn.commit()
    assert row is not None
    return annotation_from_row(row)


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
    return [annotation_from_row(row) for row in rows]


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
                evidence_id, session_id, annotation_id, title, url, page_url_snapshot,
                viewport, selector, bbox, context_summary, artifact_id,
                token_estimate, created_by_display
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING {EVIDENCE_COLUMNS}
            """,
            _evidence_insert_values(
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
                created_by_display,
            ),
        )
        row = cur.fetchone()
        _record_evidence_created(cur, session_id, evidence_id, token_estimate)
        conn.commit()
    assert row is not None
    return evidence_from_row(row)


def _evidence_insert_values(
    evidence_id: str,
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
    token_estimate: int,
    created_by_display: str | None,
) -> tuple[Any, ...]:
    return (
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
    )


def _record_evidence_created(
    cur: Any,
    session_id: str,
    evidence_id: str,
    token_estimate: int,
) -> None:
    touch_session(cur, session_id)
    insert_audit_event(
        cur,
        session_id=session_id,
        actor_kind="user",
        action="evidence-created",
        detail={"evidence_id": evidence_id, "token_estimate": token_estimate},
    )


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
    return [evidence_from_row(row) for row in rows]
