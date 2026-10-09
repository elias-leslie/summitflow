"""Fleet's advisory, source-revision stream; PostgreSQL is the replay authority.

Sequences are allocated under a transaction advisory lock, not a PostgreSQL
sequence: a cursor must never pass an uncommitted earlier allocation. Wakeups
are best effort and occur only after commit. Idempotency applies to retained rows.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

import redis
from psycopg.types.json import Jsonb

from ..logging_config import get_logger
from ..services.redis_pool import get_redis
from .connection import get_connection

logger = get_logger(__name__)
_COLUMNS = "id, project_id, trace_id, stream_sequence, source_key, source_digest, event_type, attributes, timestamp"


class SourceKeyConflict(ValueError):
    """A retained source revision was reused with different content."""


class StaleCursor(ValueError):
    """Retention removed a row after the caller's cursor."""

    def __init__(self, cursor: int, next_sequence: int) -> None:
        self.cursor = cursor
        self.next_sequence = next_sequence
        super().__init__(f"Fleet cursor {cursor} has a gap; next retained sequence is {next_sequence}")


def content_digest(event_type: str, attributes: dict[str, Any]) -> str:
    """Digest exact canonical sanitized content, including scope and source revision."""
    encoded = json.dumps([event_type, attributes], sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(encoded.encode()).hexdigest()


def _lock(cur: Any, trace_id: str) -> None:
    cur.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", (f"fleet:{trace_id}",))


def _record(row: Any) -> dict[str, Any]:
    return dict(zip(
        ("id", "project_id", "root", "sequence", "source_key", "digest", "event_type", "attributes", "timestamp"),
        row, strict=True,
    ))


def append_fleet_event(
    project_id: str, trace_id: str, *, source_key: str, event_type: str,
    attributes: dict[str, Any], digest: str | None = None, require_open: bool = False,
    return_created: bool = False,
) -> dict[str, Any]:
    """Append a compact source reference, returning the same retained retry identity."""
    if not source_key or len(source_key) > 256 or not event_type or len(event_type) > 128:
        raise ValueError("A bounded source key and event type are required")
    canonical_digest = content_digest(event_type, attributes)
    if digest is not None and digest != canonical_digest:
        raise SourceKeyConflict("Supplied digest does not match exact event content")
    if len(json.dumps(attributes).encode()) > 16384:
        raise ValueError("Fleet attributes must be a compact source reference (maximum 16 KiB)")
    with get_connection() as conn, conn.cursor() as cur:
        _lock(cur, trace_id)
        cur.execute(
            f"SELECT {_COLUMNS} FROM events WHERE trace_id = %s AND source_key = %s AND stream_sequence IS NOT NULL",
            (trace_id, source_key),
        )
        existing = cur.fetchone()
        if existing:
            if existing[1] != project_id or existing[5] != canonical_digest:
                raise SourceKeyConflict("Source key already retained with different content or scope")
            conn.commit()
            record = _record(existing)
            if return_created:
                record["created"] = False
            return record
        if require_open:
            cur.execute(
                "SELECT 1 FROM events WHERE trace_id = %s AND event_type IN ('root.closed', 'root.close-uncertain') AND stream_sequence IS NOT NULL",
                (trace_id,),
            )
            if cur.fetchone():
                raise ValueError("Fleet root is closed")
        if event_type == "root.started" and attributes.get("role") == "neri-support-root":
            lead = attributes["lead_root"]
            _lock(cur, lead)
            cur.execute("SELECT 1 FROM events WHERE trace_id = %s AND event_type = 'root.closed'", (lead,))
            if cur.fetchone():
                raise ValueError("Support lead is closed")
            cur.execute(
                "SELECT 1 FROM events e WHERE e.event_type = 'root.started' "
                "AND e.attributes->>'lead_root' = %s AND e.attributes->>'facet' = %s "
                "AND NOT EXISTS (SELECT 1 FROM events c WHERE c.trace_id = e.trace_id AND c.event_type = 'root.closed')",
                (lead, attributes["facet"]),
            )
            if cur.fetchone():
                raise ValueError("Lead already has an open support root for this facet")
        if event_type == "root.started" and attributes.get("role") == "neri-target-root":
            target = attributes["scope"]["target"]
            _lock(cur, f"allocation:{project_id}:{target}")
            cur.execute(
                "SELECT 1 FROM events e WHERE e.project_id = %s AND e.event_type = 'root.started' "
                "AND e.attributes->>'role' = 'neri-target-root' AND e.attributes->'scope'->>'target' = %s "
                "AND NOT EXISTS (SELECT 1 FROM events c WHERE c.trace_id = e.trace_id AND c.event_type = 'root.closed')",
                (project_id, target),
            )
            if cur.fetchone():
                raise ValueError("Target already has an open lead root")
        cur.execute(
            "SELECT COALESCE(MAX(stream_sequence), 0) + 1 FROM events WHERE trace_id = %s",
            (trace_id,),
        )
        allocation = cur.fetchone()
        if allocation is None:
            raise RuntimeError("Fleet sequence allocation failed")
        sequence = allocation[0]
        cur.execute(
            f"""INSERT INTO events (
                project_id, trace_id, event_type, source, level, visibility,
                attributes, stream_sequence, source_key, source_digest
            ) VALUES (%s, %s, %s, 'fleet', 'info', 'internal', %s, %s, %s, %s)
            RETURNING {_COLUMNS}""",
            (project_id, trace_id, event_type, Jsonb(attributes), sequence, source_key, canonical_digest),
        )
        row = cur.fetchone()
        conn.commit()
    # A failed database transaction never publishes. Redis failure never rolls
    # back committed history and readers recover through their durable cursor.
    try:
        get_redis().publish(f"fleet:{trace_id}", str(sequence))
    except (redis.RedisError, OSError):
        logger.warning("Fleet wake unavailable; committed sequence retained", trace_id=trace_id, sequence=sequence)
    record = _record(row)
    if return_created:
        record["created"] = True
    return record


def read_fleet_page(project_id: str, trace_id: str, *, cursor: int = 0, limit: int = 100) -> list[dict[str, Any]]:
    """Read by exclusive sequence cursor; never silently skip a retention gap."""
    if cursor < 0 or not 1 <= limit <= 1000:
        raise ValueError("Invalid fleet cursor or page limit")
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            f"SELECT {_COLUMNS} FROM events WHERE project_id = %s AND trace_id = %s "
            "AND stream_sequence > %s ORDER BY stream_sequence LIMIT %s",
            (project_id, trace_id, cursor, limit),
        )
        rows = cur.fetchall()
    expected = cursor + 1
    for row in rows:
        if row[3] != expected:
            raise StaleCursor(expected - 1, row[3])
        expected += 1
    return [_record(row) for row in rows]


def fleet_root_events(trace_id: str) -> list[dict[str, Any]]:
    """Retained lifecycle rows support show/close without a second session store."""
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            f"SELECT {_COLUMNS} FROM events WHERE trace_id = %s AND stream_sequence IS NOT NULL "
            "AND event_type LIKE 'root.%%' ORDER BY stream_sequence",
            (trace_id,),
        )
        return [_record(row) for row in cur.fetchall()]


def list_fleet_roots(project_id: str | None = None, *, limit: int = 20) -> list[str]:
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT trace_id FROM events WHERE event_type = 'root.started' AND stream_sequence IS NOT NULL "
            "AND (%s::text IS NULL OR project_id = %s) ORDER BY timestamp DESC LIMIT %s",
            (project_id, project_id, limit),
        )
        return [row[0] for row in cur.fetchall()]


def cleanup_fleet_events(*, max_age_days: int = 30) -> int:
    """Preserve lifecycle and latest high-water row under the append lock."""
    if max_age_days < 0:
        raise ValueError("Retention age must be nonnegative")
    deleted = 0
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT DISTINCT trace_id FROM events WHERE stream_sequence IS NOT NULL ORDER BY trace_id")
        roots = [row[0] for row in cur.fetchall()]
        for root in roots:
            _lock(cur, root)
            cur.execute(
                "DELETE FROM events WHERE trace_id = %s AND stream_sequence IS NOT NULL "
                "AND event_type NOT LIKE 'root.%%' AND event_type NOT LIKE 'native.delivery.%%' "
                "AND timestamp < NOW() - (%s * INTERVAL '1 day') "
                "AND stream_sequence < (SELECT MAX(stream_sequence) FROM events WHERE trace_id = %s)",
                (root, max_age_days, root),
            )
            deleted += cur.rowcount
        conn.commit()
    return deleted
