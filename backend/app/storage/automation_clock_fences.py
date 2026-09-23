"""Durable local owner fence coordinated with legacy automation ticks."""

from __future__ import annotations

import hashlib
from collections.abc import Iterator
from contextlib import contextmanager
from uuid import NAMESPACE_URL, uuid5

from .connection import get_connection, get_cursor


def _lock_id(project_id: str, workflow_key: str) -> int:
    value = hashlib.sha256(f"{project_id}:{workflow_key}".encode()).digest()[:8]
    return int.from_bytes(value, byteorder="big", signed=True)


def stable_fence_receipt(project_id: str, workflow_key: str) -> str:
    """Return the durable AH acknowledgement ID for one project/profile pair."""
    return str(uuid5(NAMESPACE_URL, f"summitflow-agent-hub-clock-fence:{project_id}:{workflow_key}"))


@contextmanager
def automation_clock_lock(project_id: str, workflow_key: str) -> Iterator[None]:
    """Serialize an old clock tick with central cutover for one project/profile."""
    key = _lock_id(project_id, workflow_key)
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT pg_advisory_lock(%s)", (key,))
        conn.commit()
        try:
            yield
        finally:
            cur.execute("SELECT pg_advisory_unlock(%s)", (key,))
            conn.commit()


def is_agent_hub_clock_fenced(project_id: str, workflow_key: str) -> bool:
    with get_cursor() as cur:
        cur.execute(
            "SELECT 1 FROM automation_clock_fences "
            "WHERE project_id = %s AND workflow_key = %s",
            (project_id, workflow_key),
        )
        return cur.fetchone() is not None


def fence_clock_to_agent_hub(project_id: str, workflow_key: str) -> str:
    """Drain the last legacy tick, then persist Agent Hub as sole clock owner."""
    receipt = stable_fence_receipt(project_id, workflow_key)
    with automation_clock_lock(project_id, workflow_key), get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO automation_clock_fences (project_id, workflow_key, clock_owner, fence_receipt)
            VALUES (%s, %s, 'agent_hub', %s)
            ON CONFLICT (project_id, workflow_key) DO UPDATE
            SET clock_owner = 'agent_hub', fenced_at = NOW()
            RETURNING fence_receipt
            """,
            (project_id, workflow_key, receipt),
        )
        row = cur.fetchone()
        conn.commit()
    if row is None or not row[0]:
        raise RuntimeError("Automation clock fence was not persisted")
    return str(row[0])
