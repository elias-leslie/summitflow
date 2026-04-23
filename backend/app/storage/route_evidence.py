from __future__ import annotations

from datetime import datetime
from typing import Any
from urllib.parse import urlsplit

from psycopg.types.json import Jsonb

from .connection import generate_prefixed_id, get_connection, get_cursor

_ROUTE_EVIDENCE_COLUMNS = """
    evidence_id,
    project_id,
    page_key,
    page_url_snapshot,
    comment,
    selector,
    anchor,
    created_by_kind,
    created_by_display,
    created_at
"""


def normalize_page_key(page_key: str | None) -> str:
    raw = str(page_key or "").strip()
    if not raw:
        return ""

    parsed = urlsplit(raw)
    path = parsed.path if any([parsed.scheme, parsed.netloc, parsed.query, parsed.fragment]) else raw
    path = path.split("?", 1)[0].split("#", 1)[0].strip()
    if path != "/":
        path = path.rstrip("/")
    return path or "/"



def _row_to_route_evidence(row: tuple[Any, ...]) -> dict[str, Any]:
    created_at = row[9]
    return {
        "evidence_id": row[0],
        "project_id": row[1],
        "page_key": row[2],
        "page_url_snapshot": row[3],
        "comment": row[4],
        "selector": row[5],
        "anchor": row[6] if row[6] else {},
        "created_by_kind": row[7],
        "created_by_display": row[8],
        "created_at": created_at.isoformat() if isinstance(created_at, datetime) else None,
    }



def create_route_evidence(
    *,
    project_id: str,
    page_key: str,
    page_url_snapshot: str | None,
    comment: str,
    selector: str | None,
    anchor: dict[str, Any],
    created_by_display: str | None,
) -> dict[str, Any]:
    evidence_id = generate_prefixed_id("evidence")
    normalized_page_key = normalize_page_key(page_key)

    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            f"""
            INSERT INTO route_evidence (
                evidence_id,
                project_id,
                page_key,
                page_url_snapshot,
                comment,
                selector,
                anchor,
                created_by_kind,
                created_by_display
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, 'user', %s)
            RETURNING {_ROUTE_EVIDENCE_COLUMNS}
            """,
            (
                evidence_id,
                project_id,
                normalized_page_key,
                page_url_snapshot,
                comment,
                selector,
                Jsonb(anchor),
                created_by_display,
            ),
        )
        row = cur.fetchone()
        conn.commit()

    assert row is not None
    return _row_to_route_evidence(row)



def list_route_evidence(
    *,
    project_id: str,
    page_key: str,
    limit: int = 10,
) -> list[dict[str, Any]]:
    normalized_page_key = normalize_page_key(page_key)
    safe_limit = max(1, min(int(limit), 100))

    with get_cursor() as cur:
        cur.execute(
            f"""
            SELECT {_ROUTE_EVIDENCE_COLUMNS}
            FROM route_evidence
            WHERE project_id = %s AND page_key = %s
            ORDER BY created_at DESC, evidence_id DESC
            LIMIT %s
            """,
            (project_id, normalized_page_key, safe_limit),
        )
        rows = cur.fetchall()

    return [_row_to_route_evidence(row) for row in rows]



def get_page_evidence_summaries(
    *,
    project_id: str,
    page_keys: list[str],
    recent_limit: int = 10,
) -> dict[str, dict[str, Any]]:
    normalized_keys = [normalize_page_key(key) for key in page_keys]
    ordered_keys = list(dict.fromkeys(normalized_keys))
    summaries: dict[str, dict[str, Any]] = {
        key: {
            "evidence_count": 0,
            "last_evidence_at": None,
            "recent_items": [],
        }
        for key in ordered_keys
        if key
    }
    if not summaries:
        return {}

    with get_cursor() as cur:
        cur.execute(
            """
            SELECT page_key, COUNT(*)::int, MAX(created_at)
            FROM route_evidence
            WHERE project_id = %s AND page_key = ANY(%s)
            GROUP BY page_key
            """,
            (project_id, list(summaries.keys())),
        )
        for page_key, count, last_created_at in cur.fetchall():
            summaries[page_key]["evidence_count"] = count
            summaries[page_key]["last_evidence_at"] = (
                last_created_at.isoformat() if isinstance(last_created_at, datetime) else None
            )

        cur.execute(
            f"""
            SELECT evidence_id, project_id, page_key, page_url_snapshot, comment, selector,
                   anchor, created_by_kind, created_by_display, created_at
            FROM (
                SELECT {_ROUTE_EVIDENCE_COLUMNS},
                       ROW_NUMBER() OVER (
                           PARTITION BY page_key
                           ORDER BY created_at DESC, evidence_id DESC
                       ) AS row_num
                FROM route_evidence
                WHERE project_id = %s AND page_key = ANY(%s)
            ) ranked
            WHERE row_num <= %s
            ORDER BY page_key ASC, created_at DESC, evidence_id DESC
            """,
            (project_id, list(summaries.keys()), max(1, min(int(recent_limit), 100))),
        )
        recent_rows = cur.fetchall()

    for row in recent_rows:
        item = _row_to_route_evidence(row)
        summaries[item["page_key"]]["recent_items"].append(item)

    for key in ordered_keys:
        summaries.setdefault(
            key,
            {
                "evidence_count": 0,
                "last_evidence_at": None,
                "recent_items": [],
            },
        )

    return summaries
