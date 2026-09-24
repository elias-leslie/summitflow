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
        conn.commit()
    if row is None:
        raise RuntimeError("Dependency review insert returned no row")
    return _row(row), True
