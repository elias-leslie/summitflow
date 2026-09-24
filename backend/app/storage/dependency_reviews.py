"""Immutable dependency evidence and decision revisions."""

from __future__ import annotations

import json
from typing import Any

from .connection import get_connection, get_cursor


def _row(row: tuple[Any, ...]) -> dict[str, Any]:
    return {
        "id": row[0],
        "project_id": row[1],
        "entry_path": row[2],
        "revision": row[3],
        "evidence_hash": row[4],
        "evidence": row[5],
        "decision": row[6],
        "recommended_version": row[7],
        "rationale": row[8],
        "task_id": row[9],
        "created_at": row[10].isoformat() if row[10] else None,
    }


_COLUMNS = (
    "id, project_id, entry_path, revision, evidence_hash, evidence, "
    "decision, recommended_version, rationale, task_id, created_at"
)


def latest(project_id: str, entry_path: str) -> dict[str, Any] | None:
    with get_cursor() as cur:
        cur.execute(
            f"SELECT {_COLUMNS} FROM dependency_review_events "
            "WHERE project_id = %s AND entry_path = %s ORDER BY revision DESC LIMIT 1",
            (project_id, entry_path),
        )
        row = cur.fetchone()
    return _row(row) if row else None


def latest_for_project(project_id: str) -> dict[str, dict[str, Any]]:
    with get_cursor() as cur:
        cur.execute(
            f"SELECT DISTINCT ON (entry_path) {_COLUMNS} FROM dependency_review_events "
            "WHERE project_id = %s ORDER BY entry_path, revision DESC",
            (project_id,),
        )
        rows = cur.fetchall()
    return {str(row[2]): _row(row) for row in rows}


def checks_for_project(project_id: str) -> dict[str, str]:
    """Return the last actual evidence-check time for weekly scheduling."""
    with get_cursor() as cur:
        cur.execute(
            "SELECT entry_path, checked_at FROM dependency_review_checks WHERE project_id = %s",
            (project_id,),
        )
        rows = cur.fetchall()
    return {str(path): checked_at.isoformat() for path, checked_at in rows}


def _record_check(cur: Any, project_id: str, entry_path: str, evidence_hash: str) -> None:
    cur.execute(
        """INSERT INTO dependency_review_checks (project_id, entry_path, evidence_hash)
        VALUES (%s, %s, %s)
        ON CONFLICT (project_id, entry_path) DO UPDATE SET
            evidence_hash = EXCLUDED.evidence_hash,
            checked_at = NOW()""",
        (project_id, entry_path, evidence_hash),
    )


def attach_task(project_id: str, entry_path: str, event_id: int, task_id: str) -> dict[str, Any]:
    """Link a queued task to the already committed decision that authorized it."""
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            f"UPDATE dependency_review_events SET task_id = %s "
            f"WHERE id = %s AND project_id = %s AND entry_path = %s "
            f"AND decision = 'update' AND (task_id IS NULL OR task_id = %s) "
            f"AND revision = (SELECT MAX(revision) FROM dependency_review_events "
            f"WHERE project_id = %s AND entry_path = %s) "
            f"RETURNING {_COLUMNS}",
            (task_id, event_id, project_id, entry_path, task_id, project_id, entry_path),
        )
        row = cur.fetchone()
        if row is None:
            raise ValueError("Dependency decision was superseded before its task could be linked")
        conn.commit()
    return _row(row)


def append(
    project_id: str,
    entry_path: str,
    *,
    evidence_hash: str,
    evidence: dict[str, Any],
    decision: str = "pending",
    recommended_version: str | None = None,
    rationale: str | None = None,
    task_id: str | None = None,
    expected_revision: int | None = None,
    skip_same_evidence: bool = False,
) -> tuple[dict[str, Any], bool]:
    """Append under a per-package transaction lock; reuse unchanged evidence."""
    if decision not in {"pending", "update", "hold", "investigate"}:
        raise ValueError("Invalid dependency decision")
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
            (f"dependency-review:{project_id}:{entry_path}",),
        )
        cur.execute(
            f"SELECT {_COLUMNS} FROM dependency_review_events "
            "WHERE project_id = %s AND entry_path = %s ORDER BY revision DESC LIMIT 1",
            (project_id, entry_path),
        )
        previous = cur.fetchone()
        prev_revision = int(previous[3]) if previous else 0
        if expected_revision is not None and prev_revision != expected_revision:
            raise ValueError(f"Stale dependency review revision: current {prev_revision}")
        if previous and skip_same_evidence and previous[4] == evidence_hash:
            _record_check(cur, project_id, entry_path, evidence_hash)
            conn.commit()
            return _row(previous), False
        cur.execute(
            """INSERT INTO dependency_review_events
            (project_id, entry_path, revision, evidence_hash, evidence, decision,
             recommended_version, rationale, task_id)
            VALUES (%s, %s, %s, %s, %s::jsonb, %s, %s, %s, %s)
            RETURNING id, project_id, entry_path, revision, evidence_hash, evidence,
                      decision, recommended_version, rationale, task_id, created_at""",
            (
                project_id, entry_path, prev_revision + 1, evidence_hash,
                json.dumps(evidence, sort_keys=True), decision, recommended_version,
                rationale, task_id,
            ),
        )
        row = cur.fetchone()
        if skip_same_evidence:
            _record_check(cur, project_id, entry_path, evidence_hash)
        conn.commit()
    if row is None:
        raise RuntimeError("Dependency review insert returned no row")
    return _row(row), True
