"""Durable completion intent lives on the canonical task, separate from CI evidence."""
from __future__ import annotations

from contextlib import contextmanager
from typing import Any

import psycopg
from psycopg.types.json import Jsonb

from ...config import DATABASE_URL
from ..connection import get_connection
from .core import canonicalize_task_id


def store_closeout(task_id: str, project_id: str, closeout: dict[str, Any], *, expected_request_id: str | None = None) -> bool:
    """Merge only the closeout key; preserve independent verification receipts."""
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """UPDATE tasks SET verification_result =
               COALESCE(verification_result, '{}'::jsonb) || %s::jsonb,
               updated_at = NOW() WHERE id = %s AND project_id = %s
               AND (%s::text IS NULL OR verification_result->'closeout'->>'request_id' = %s)""",
            (Jsonb({"closeout": closeout}), canonicalize_task_id(task_id), project_id,
             expected_request_id, expected_request_id),
        )
        if cur.rowcount != 1 and expected_request_id is None:
            raise ValueError("Closeout task does not belong to the selected project")
        return cur.rowcount == 1


def pending_closeout_ids() -> list[str]:
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("""SELECT id FROM tasks
                       WHERE verification_result->'closeout'->>'state' = 'pending'
                       AND status NOT IN ('paused', 'cancelled', 'abandoned', 'closed', 'failed')
                       ORDER BY updated_at, id""")
        return [row[0] for row in cur.fetchall()]


@contextmanager
def closeout_lock(task_id: str):
    """Serialize CLI and worker continuation without an invented claim expiry."""
    # A process-held advisory lock needs its own connection: keeping all pooled
    # slots busy with locks would deadlock concurrent workers' task reads/writes.
    assert DATABASE_URL is not None
    with psycopg.connect(DATABASE_URL) as conn, conn.cursor() as cur:
        cur.execute("SELECT pg_try_advisory_xact_lock(hashtextextended(%s, 0))",
                    ("task-closeout:" + canonicalize_task_id(task_id),))
        row = cur.fetchone()
        yield bool(row and row[0])
