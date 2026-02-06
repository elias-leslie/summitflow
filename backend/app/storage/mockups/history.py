"""Mockups history - History tracking and statistics."""

from __future__ import annotations

from typing import Any

from ..connection import get_connection
from .core import get_mockup_by_db_id
from .queries import get_mockup


def get_mockup_history(project_id: str, mockup_id: str) -> list[dict[str, Any]]:
    """Get the iteration history of a mockup (including parent chain)."""
    mockup = get_mockup(project_id, mockup_id)
    if not mockup:
        return []

    history = [mockup]

    # Walk up the parent chain
    current = mockup
    while current.get("parent_mockup_id"):
        parent = get_mockup_by_db_id(current["parent_mockup_id"])
        if not parent:
            break
        history.append(parent)
        current = parent

    # Return oldest first
    return list(reversed(history))


def get_mockup_stats(project_id: str) -> dict[str, Any]:
    """Get mockup statistics for a project."""
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT
                COUNT(*) as total,
                COUNT(*) FILTER (WHERE status = 'generated') as generated,
                COUNT(*) FILTER (WHERE status = 'pending_approval') as pending_approval,
                COUNT(*) FILTER (WHERE status = 'approved') as approved,
                COUNT(*) FILTER (WHERE status = 'rejected') as rejected,
                COUNT(*) FILTER (WHERE status = 'applied') as applied,
                COUNT(*) FILTER (WHERE status = 'archived') as archived,
                COUNT(DISTINCT generator) as unique_generators,
                AVG(generation_time_ms) FILTER (WHERE generation_time_ms IS NOT NULL) as avg_generation_time_ms
            FROM mockups
            WHERE project_id = %s
            """,
            (project_id,),
        )
        row = cur.fetchone()

        if not row:
            return {
                "total": 0,
                "by_status": {},
                "unique_generators": 0,
                "avg_generation_time_ms": None,
            }

        return {
            "total": int(row[0]) if row[0] else 0,
            "by_status": {
                "generated": int(row[1]) if row[1] else 0,
                "pending_approval": int(row[2]) if row[2] else 0,
                "approved": int(row[3]) if row[3] else 0,
                "rejected": int(row[4]) if row[4] else 0,
                "applied": int(row[5]) if row[5] else 0,
                "archived": int(row[6]) if row[6] else 0,
            },
            "unique_generators": int(row[7]) if row[7] else 0,
            "avg_generation_time_ms": float(row[8]) if row[8] else None,
        }
