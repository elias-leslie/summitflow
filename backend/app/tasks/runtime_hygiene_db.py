"""Database bloat checks for runtime hygiene."""

from __future__ import annotations

from typing import Any

from .runtime_hygiene_common import (
    BLOAT_CRIT_DEAD_BYTES,
    BLOAT_CRIT_PCT,
    BLOAT_WARN_PCT,
    MIN_BLOAT_DEAD_TUPLES,
    MIN_BLOAT_TABLE_BYTES,
    Severity,
    json_safe,
    severity_rank,
    status_from_severity,
)


def query_bloat_candidates(project_id: str, deps: Any) -> dict[str, Any]:
    db_url = deps.get_db_url_for_project(project_id)
    if not db_url:
        return _unavailable_result(project_id, "db_url_missing")

    try:
        with deps.psycopg.connect(db_url, autocommit=True) as conn, conn.cursor() as cur:
            cur.execute(_BLOAT_QUERY)
            rows = cur.fetchall()
    except Exception as exc:
        deps.logger.warning("runtime_hygiene_bloat_query_failed", project_id=project_id, error=str(exc))
        return _unavailable_result(project_id, str(exc))

    normalized = [_normalize_bloat_row(row) for row in rows]
    candidates = [row for row in normalized if row.get("severity")]
    return {
        "status": status_from_severity(_candidate_severity(candidates)),
        "project_id": project_id,
        "db_url_available": True,
        "candidate_count": len(candidates),
        "candidates": candidates,
    }


def vacuum_analyze_table(
    project_id: str,
    schema_name: str,
    table_name: str,
    deps: Any,
) -> dict[str, Any]:
    db_url = deps.get_db_url_for_project(project_id)
    if not db_url:
        return {"status": "failed", "error": "db_url_missing"}
    table_ref = f"{schema_name}.{table_name}"
    try:
        with deps.psycopg.connect(db_url, autocommit=True) as conn, conn.cursor() as cur:
            cur.execute(
                deps.sql.SQL("VACUUM (ANALYZE) {}.{};").format(
                    deps.sql.Identifier(schema_name),
                    deps.sql.Identifier(table_name),
                )
            )
        return {"status": "completed", "schema": schema_name, "table": table_name, "table_ref": table_ref}
    except Exception as exc:
        deps.logger.warning("runtime_hygiene_vacuum_failed", project_id=project_id, table=table_ref, error=str(exc))
        return {
            "status": "failed",
            "schema": schema_name,
            "table": table_name,
            "table_ref": table_ref,
            "error": str(exc),
        }


def _unavailable_result(project_id: str, reason: str) -> dict[str, Any]:
    return {
        "status": "unavailable",
        "reason": reason,
        "project_id": project_id,
        "candidates": [],
    }


def _normalize_bloat_row(row: Any) -> dict[str, Any]:
    schemaname, relname, total_bytes, n_live_tup, n_dead_tup, last_autovacuum, last_vacuum = row
    schema = str(schemaname or "public")
    live = int(n_live_tup or 0)
    dead = int(n_dead_tup or 0)
    total = int(total_bytes or 0)
    total_tuples = live + dead
    dead_pct = round((dead / total_tuples) * 100, 2) if total_tuples else 0.0
    dead_bytes = int(total * (dead / total_tuples)) if total_tuples else 0
    return _bloat_row(schema, str(relname), total, live, dead, dead_pct, dead_bytes, last_autovacuum, last_vacuum)


def _bloat_row(
    schema: str,
    relname: str,
    total: int,
    live: int,
    dead: int,
    dead_pct: float,
    dead_bytes: int,
    last_autovacuum: Any,
    last_vacuum: Any,
) -> dict[str, Any]:
    severity = _bloat_severity(total, dead, dead_pct, dead_bytes)
    return {
        "schema": schema,
        "table": relname,
        "table_ref": f"{schema}.{relname}",
        "total_bytes": total,
        "total_mb": round(total / (1024 * 1024), 1),
        "n_live_tup": live,
        "n_dead_tup": dead,
        "dead_pct": dead_pct,
        "dead_bytes": dead_bytes,
        "dead_mb": round(dead_bytes / (1024 * 1024), 1),
        "severity": severity,
        "last_autovacuum": json_safe(last_autovacuum),
        "last_vacuum": json_safe(last_vacuum),
    }


def _bloat_severity(total: int, dead: int, dead_pct: float, dead_bytes: int) -> Severity | None:
    if total < MIN_BLOAT_TABLE_BYTES or dead < MIN_BLOAT_DEAD_TUPLES or dead_pct < BLOAT_WARN_PCT:
        return None
    return "critical" if dead_pct >= BLOAT_CRIT_PCT or dead_bytes >= BLOAT_CRIT_DEAD_BYTES else "warning"


def _candidate_severity(candidates: list[dict[str, Any]]) -> Severity | None:
    severity: Severity | None = None
    for candidate in candidates:
        candidate_severity = candidate.get("severity")
        if candidate_severity and (severity is None or severity_rank(candidate_severity) > severity_rank(severity)):
            severity = candidate_severity
    return severity


_BLOAT_QUERY = """
    SELECT
        schemaname,
        relname,
        pg_total_relation_size(relid) AS total_bytes,
        n_live_tup,
        n_dead_tup,
        last_autovacuum,
        last_vacuum
    FROM pg_stat_user_tables
    ORDER BY pg_total_relation_size(relid) DESC, relname ASC
"""
