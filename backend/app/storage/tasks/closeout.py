"""Durable completion intent lives on the canonical task, separate from CI evidence."""
from __future__ import annotations

from collections.abc import Callable
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Any

import psycopg
from psycopg.types.json import Jsonb

from ...config import DATABASE_URL
from ..connection import get_connection
from .core import canonicalize_task_id


def store_closeout(task_id: str, project_id: str, closeout: dict[str, Any], *,
                   expected_request_id: str | None = None,
                   expected_closeout: dict[str, Any] | None = None,
                   expected_source_sha: str | None = None,
                   expected_worker: str | None = None,
                   expected_claimed_at: Any = None,
                   expected_acceptance: dict[str, Any] | None = None,
                   expected_verification: dict[str, Any] | None = None) -> bool:
    """Merge only the closeout key; preserve independent verification receipts."""
    if expected_worker is not None and not expected_claimed_at:
        raise ValueError("An exact active claim is required for a new closeout request")
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """UPDATE tasks SET verification_result =
               COALESCE(verification_result, '{}'::jsonb) || %s::jsonb,
               updated_at = NOW() WHERE id = %s AND project_id = %s
               AND (%s::text IS NULL OR verification_result->'closeout'->>'request_id' = %s)
               AND (%s::jsonb IS NULL OR COALESCE(verification_result->'closeout', '{}'::jsonb) = %s::jsonb)
               AND (%s::text IS NULL OR (status IN ('pending', 'running', 'completed')
                    AND verification_result->'acceptance'->>'state' = 'success'
                    AND verification_result->'acceptance'->>'source_commit' = %s))
               AND (%s::text IS NULL OR (status = 'running' AND claimed_by = %s
                    AND claimed_at = %s::timestamptz AND lock_expires_at > NOW()))
               AND (%s::jsonb IS NULL OR COALESCE(verification_result->'acceptance', '{}'::jsonb) = %s::jsonb)
               AND NOT EXISTS (SELECT 1 FROM jsonb_each(%s::jsonb) AS prior(key, value)
                    WHERE COALESCE(verification_result->prior.key, '{}'::jsonb) IS DISTINCT FROM prior.value)""",
            (Jsonb({"closeout": closeout}), canonicalize_task_id(task_id), project_id,
             expected_request_id, expected_request_id,
             Jsonb(expected_closeout) if expected_closeout is not None else None,
             Jsonb(expected_closeout) if expected_closeout is not None else None,
             expected_source_sha, expected_source_sha, expected_worker, expected_worker, expected_claimed_at,
             Jsonb(expected_acceptance) if expected_acceptance is not None else None,
             Jsonb(expected_acceptance) if expected_acceptance is not None else None,
             Jsonb(expected_verification or {})),
        )
        if cur.rowcount != 1 and expected_request_id is None and expected_closeout is None and expected_source_sha is None:
            raise ValueError("Closeout task does not belong to the selected project")
        return cur.rowcount == 1


def pending_closeout_ids() -> list[str]:
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("""SELECT id FROM tasks
                       WHERE verification_result->'closeout'->>'state' = 'pending'
                       AND verification_result->'closeout'->>'kind' = 'local_closeout.v1'
                       AND status IN ('pending', 'running', 'completed')
                       ORDER BY updated_at, id""")
        return [row[0] for row in cur.fetchall()]


def release_closeout_claim(task_id: str, project_id: str, request_id: str) -> bool:
    """Release an exact queued request without invalidating its accepted source."""
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("""UPDATE tasks SET status = 'pending', claimed_by = NULL,
                       claimed_at = NULL, lock_expires_at = NULL, updated_at = NOW()
                       WHERE id = %s AND project_id = %s AND status IN ('pending','running')
                       AND verification_result->'closeout'->>'request_id' = %s
                       AND verification_result->'closeout'->>'state' IN ('pending','blocked')""",
                    (canonicalize_task_id(task_id), project_id, request_id))
        return cur.rowcount == 1


def store_verification(task_id: str, project_id: str, receipts: dict[str, Any]) -> None:
    """Merge source-bound local evidence without overwriting publication/history."""
    if not receipts or set(receipts) - {"acceptance", "deployment", "live_validation"}:
        raise ValueError("Unsupported local verification receipt")
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """UPDATE tasks SET verification_result =
               COALESCE(verification_result, '{}'::jsonb) || %s::jsonb,
               updated_at = NOW() WHERE id = %s AND project_id = %s""",
            (Jsonb(receipts), canonicalize_task_id(task_id), project_id),
        )
        if cur.rowcount != 1:
            raise ValueError("Verification task does not belong to selected project")


def store_owned_acceptance(task_id: str, project_id: str, receipt: dict[str, Any], *,
                           expected_worker: str, expected_claimed_at: Any,
                           expected_acceptance: dict[str, Any]) -> bool:
    """Attach a proof only to the same active claim and prior evidence revision."""
    if not expected_worker or not expected_claimed_at or receipt.get("state") != "success":
        raise ValueError("Successful acceptance and an exact active claim are required")
    return store_owned_verification(task_id, project_id, {"acceptance": receipt},
        expected_worker=expected_worker, expected_claimed_at=expected_claimed_at,
        expected_verification={"acceptance": expected_acceptance})


def store_owned_verification(task_id: str, project_id: str, receipts: dict[str, Any], *,
                             expected_worker: str, expected_claimed_at: Any,
                             expected_verification: dict[str, Any]) -> bool:
    """Merge selected receipts only for the same active claim and prior evidence."""
    if not receipts or set(receipts) - {"acceptance", "deployment", "live_validation"}:
        raise ValueError("Unsupported local verification receipt")
    if not expected_worker or not expected_claimed_at:
        raise ValueError("An exact active claim is required for completion evidence")
    prior = {key: expected_verification.get(key) or {} for key in receipts}
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("""UPDATE tasks SET verification_result =
            COALESCE(verification_result, '{}'::jsonb) || %s::jsonb, updated_at = NOW()
            WHERE id = %s AND project_id = %s AND status = 'running'
            AND claimed_by = %s AND claimed_at = %s::timestamptz AND lock_expires_at > NOW()
            AND NOT EXISTS (SELECT 1 FROM jsonb_each(%s::jsonb) AS prior(key, value)
                WHERE COALESCE(verification_result->prior.key, '{}'::jsonb) IS DISTINCT FROM prior.value)""",
            (Jsonb(receipts), canonicalize_task_id(task_id), project_id,
             expected_worker, expected_claimed_at, Jsonb(prior)))
        return cur.rowcount == 1


_EXECUTION_VERIFICATION_KEYS = {
    "autonomous_failure",
    "evidence_verified",
    "execution_clean",
    "external_work",
    "subtask_count",
    "total_extensions_granted",
    "total_self_fix_attempts",
    "total_supervisor_attempts",
    "verification_source",
}


def store_execution_verification(
    task_id: str,
    project_id: str,
    facts: dict[str, Any],
) -> None:
    """Merge generated execution facts while retaining independent receipts."""
    if not facts or set(facts) - _EXECUTION_VERIFICATION_KEYS:
        raise ValueError("Unsupported autonomous execution verification fact")
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """UPDATE tasks SET verification_result =
               COALESCE(verification_result, '{}'::jsonb) || %s::jsonb,
               updated_at = NOW() WHERE id = %s AND project_id = %s""",
            (Jsonb(facts), canonicalize_task_id(task_id), project_id),
        )
        if cur.rowcount != 1:
            raise ValueError("Verification task does not belong to selected project")


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


def retire_remote_closeout(task_id: str, project_id: str, *, expected_closeout: dict[str, Any]) -> bool:
    """Explicit owner migration; compare the full intent and preserve its history."""
    if not expected_closeout or expected_closeout.get("kind") == "local_closeout.v1":
        raise ValueError("Only a reviewed legacy remote closeout may be retired")
    retired = {**expected_closeout, "state": "retired", "reason": "no_longer_required",
               "retired_at": datetime.now(UTC).isoformat(), "previous_closeout": expected_closeout}
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("""UPDATE tasks SET verification_result =
                       COALESCE(verification_result, '{}'::jsonb) || %s::jsonb,
                       updated_at = NOW() WHERE id = %s AND project_id = %s
                       AND verification_result->'closeout' = %s::jsonb""",
                    (Jsonb({"closeout": retired}), canonicalize_task_id(task_id), project_id, Jsonb(expected_closeout)))
        return cur.rowcount == 1


def finish_closeout_cleanup(task_id: str, project_id: str, request_id: str,
                            source_sha: str, cleanup: Callable[[], None]) -> bool:
    """Keep lifecycle changes from racing destructive metadata/lease cleanup."""
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT status, verification_result FROM tasks WHERE id = %s AND project_id = %s FOR UPDATE",
                    (canonicalize_task_id(task_id), project_id))
        row = cur.fetchone()
        verification = (row[1] or {}) if row else {}
        intent = verification.get("closeout") or {}
        acceptance = verification.get("acceptance") or {}
        if (not row or row[0] != "completed" or intent.get("kind") != "local_closeout.v1"
                or intent.get("request_id") != request_id or intent.get("source_sha") != source_sha
                or acceptance.get("state") != "success" or acceptance.get("source_commit") != source_sha):
            return False
        cleanup()
        finished = {**intent, "state": "complete", "completed_at": datetime.now(UTC).isoformat(), "reason": ""}
        cur.execute("""UPDATE tasks SET verification_result = verification_result || %s::jsonb,
                       updated_at = NOW() WHERE id = %s AND project_id = %s""",
                    (Jsonb({"closeout": finished}), canonicalize_task_id(task_id), project_id))
        return cur.rowcount == 1


def cleanup_completed_checkpoint(task_id: str, project_id: str, *,
                                 expected_acceptance: dict[str, Any], cleanup: Callable[[], None],
                                 require_acceptance: bool = True) -> bool:
    """Guard historical metadata cleanup without writing a new completion intent."""
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT status, verification_result FROM tasks WHERE id = %s AND project_id = %s FOR UPDATE",
                    (canonicalize_task_id(task_id), project_id))
        row = cur.fetchone()
        acceptance = ((row[1] or {}).get("acceptance") or {}) if row else {}
        if not row or row[0] != "completed" or acceptance != expected_acceptance or (require_acceptance and acceptance.get("state") != "success"):
            return False
        cleanup()
        return True
