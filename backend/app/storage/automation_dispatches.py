"""Durable receipts and outbox state for Agent Hub automation dispatches."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from psycopg.types.json import Jsonb

from .connection import get_connection, get_cursor

_COLUMNS = """
    run_id, profile_id, project_id, workflow_key, definition_version, profile_revision,
    occurrence_key, trigger, scheduled_for, request_payload, owner_run_id,
    status, worker_run_id, result, error, completion_reported_at,
    created_at, updated_at, completed_at
"""


def _row_to_dict(row: tuple[Any, ...]) -> dict[str, Any]:
    return {
        "run_id": str(row[0]),
        "profile_id": str(row[1]),
        "project_id": str(row[2]),
        "workflow_key": str(row[3]),
        "definition_version": int(row[4]),
        "profile_revision": int(row[5]),
        "occurrence_key": str(row[6]),
        "trigger": str(row[7]),
        "scheduled_for": row[8],
        "request_payload": row[9] or {},
        "owner_run_id": str(row[10]),
        "status": str(row[11]),
        "worker_run_id": row[12],
        "result": row[13],
        "error": row[14],
        "completion_reported_at": row[15],
        "created_at": row[16],
        "updated_at": row[17],
        "completed_at": row[18],
    }


def get_automation_run(run_id: str) -> dict[str, Any] | None:
    with get_cursor() as cur:
        cur.execute(
            f"SELECT {_COLUMNS} FROM automation_dispatch_receipts WHERE run_id = %s",
            (run_id,),
        )
        row = cur.fetchone()
    return _row_to_dict(row) if row else None


def list_pending_automation_runs(limit: int = 50) -> list[dict[str, Any]]:
    """List durable outbox rows not yet confirmed in Hatchet."""
    with get_cursor() as cur:
        cur.execute(
            f"""
            SELECT {_COLUMNS} FROM automation_dispatch_receipts
            WHERE status = 'pending'
              AND updated_at < NOW() - INTERVAL '1 minute'
            ORDER BY created_at ASC
            LIMIT %s
            """,
            (limit,),
        )
        rows = cur.fetchall()
    return [_row_to_dict(row) for row in rows]


def defer_pending_automation_run(run_id: str) -> None:
    """Back off a failed reconciliation enqueue without losing its receipt."""
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            "UPDATE automation_dispatch_receipts SET updated_at = NOW() "
            "WHERE run_id = %s AND status = 'pending'",
            (run_id,),
        )
        conn.commit()


def create_or_get_automation_run(
    payload: dict[str, Any],
    owner_run_id: str,
) -> dict[str, Any]:
    """Persist the callback envelope before any workflow is queued.

    A repeated run ID is accepted only when its immutable callback envelope is
    byte-for-byte equivalent after JSON decoding.
    """
    run_id = str(payload["run_id"])
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            f"""
            INSERT INTO automation_dispatch_receipts (
                run_id, profile_id, project_id, workflow_key, definition_version,
                profile_revision, occurrence_key, trigger, scheduled_for,
                request_payload, owner_run_id, status
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'pending')
            ON CONFLICT (run_id) DO NOTHING
            RETURNING {_COLUMNS}
            """,
            (
                run_id,
                payload["profile_id"],
                payload["project_id"],
                payload["workflow_key"],
                payload["definition_version"],
                payload["profile_revision"],
                payload["occurrence_key"],
                payload["trigger"],
                payload["scheduled_for"],
                Jsonb(payload),
                owner_run_id,
            ),
        )
        row = cur.fetchone()
        if row is None:
            cur.execute(
                f"SELECT {_COLUMNS} FROM automation_dispatch_receipts WHERE run_id = %s",
                (run_id,),
            )
            row = cur.fetchone()
        conn.commit()

    if row is None:
        raise RuntimeError("Automation dispatch receipt was not persisted")
    receipt = _row_to_dict(row)
    if receipt["request_payload"] != payload:
        raise ValueError("Run ID was already used with a different callback envelope")
    return receipt


def mark_automation_run_queued(run_id: str) -> dict[str, Any]:
    """Mark an outbox row queued without overwriting a worker's newer state."""
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            f"""
            UPDATE automation_dispatch_receipts
            SET status = 'queued', updated_at = NOW()
            WHERE run_id = %s AND status = 'pending'
            RETURNING {_COLUMNS}
            """,
            (run_id,),
        )
        row = cur.fetchone()
        if row is None:
            cur.execute(
                f"SELECT {_COLUMNS} FROM automation_dispatch_receipts WHERE run_id = %s",
                (run_id,),
            )
            row = cur.fetchone()
        conn.commit()
    if row is None:
        raise RuntimeError("Automation dispatch receipt disappeared after enqueue")
    return _row_to_dict(row)


def claim_automation_run(run_id: str, worker_run_id: str) -> dict[str, Any] | None:
    """Claim owner work once; Hatchet retries may resume their own run ID."""
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            f"""
            UPDATE automation_dispatch_receipts
            SET status = 'running', worker_run_id = %s, updated_at = NOW()
            WHERE run_id = %s
              AND (
                    status IN ('pending', 'queued')
                    OR (status = 'running' AND worker_run_id = %s)
              )
            RETURNING {_COLUMNS}
            """,
            (worker_run_id, run_id, worker_run_id),
        )
        row = cur.fetchone()
        conn.commit()
    return _row_to_dict(row) if row else None


def finish_automation_run(
    run_id: str,
    worker_run_id: str,
    *,
    status: str,
    result: dict[str, Any] | None = None,
    error: str | None = None,
) -> dict[str, Any]:
    if status not in {"succeeded", "failed", "skipped", "cancelled"}:
        raise ValueError(f"Unsupported terminal automation status: {status}")
    now = datetime.now(UTC)
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            f"""
            UPDATE automation_dispatch_receipts
            SET status = %s, result = %s, error = %s,
                completed_at = %s, updated_at = %s
            WHERE run_id = %s AND worker_run_id = %s AND status = 'running'
            RETURNING {_COLUMNS}
            """,
            (status, Jsonb(result) if result is not None else None, error, now, now, run_id, worker_run_id),
        )
        row = cur.fetchone()
        conn.commit()
    if row is None:
        raise RuntimeError("Automation run is not owned by this worker")
    return _row_to_dict(row)


def mark_automation_completion_reported(run_id: str) -> None:
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            UPDATE automation_dispatch_receipts
            SET completion_reported_at = NOW(), updated_at = NOW()
            WHERE run_id = %s AND status IN ('succeeded', 'failed', 'skipped', 'cancelled')
            """,
            (run_id,),
        )
        conn.commit()
