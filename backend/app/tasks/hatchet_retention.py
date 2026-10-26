"""Retention guard for Hatchet OLAP and lookup tables."""

from __future__ import annotations

import os
import re
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import psycopg
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo

from ..config import settings
from ..logging_config import get_logger
from ..storage import maintenance_runs as maintenance_store
from ..utils import safe_subprocess
from ..utils.pg_client import pg_client

logger = get_logger(__name__)

WORKFLOW_NAME = "hatchet_retention_guard"
DEFAULT_RETENTION_HOURS = 720.0
DEFAULT_BATCH_SIZE = 50_000
DEFAULT_BACKUP_TIMEOUT_SECONDS = 3600
# Hatchet only schedules onto workers that heartbeated in the last 5 seconds;
# an hour of silence means the process is gone but its row still says active.
DEFAULT_STALE_WORKER_SECONDS = 3600

_DURATION_RE = re.compile(r"(\d+(?:\.\d+)?)(ns|us|µs|ms|s|m|h)")
_DURATION_UNIT_SECONDS = {
    "ns": 0.000000001,
    "us": 0.000001,
    "µs": 0.000001,
    "ms": 0.001,
    "s": 1.0,
    "m": 60.0,
    "h": 3600.0,
}


@dataclass(frozen=True)
class HatchetRetentionTable:
    """One Hatchet table and the timestamp column that defines retention."""

    name: str
    timestamp_column: str


RETENTION_TABLES: tuple[HatchetRetentionTable, ...] = (
    HatchetRetentionTable("v1_task_events_olap", "event_timestamp"),
    HatchetRetentionTable("v1_statuses_olap", "inserted_at"),
    HatchetRetentionTable("v1_lookup_table_olap", "inserted_at"),
    HatchetRetentionTable("v1_lookup_table", "inserted_at"),
)


def _parse_duration_hours(value: Any) -> float | None:
    """Parse Hatchet/Go duration strings such as ``720h`` or ``1h30m``."""
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None

    total_seconds = 0.0
    position = 0
    for match in _DURATION_RE.finditer(text):
        if match.start() != position:
            return None
        amount = float(match.group(1))
        total_seconds += amount * _DURATION_UNIT_SECONDS[match.group(2)]
        position = match.end()

    if position != len(text) or total_seconds <= 0:
        return None
    return total_seconds / 3600.0


def _hatchet_conninfo() -> str:
    base_conninfo = settings.database_admin_url or settings.database_url
    if not base_conninfo:
        raise RuntimeError("DATABASE_ADMIN_URL or DATABASE_URL is required")
    parts = conninfo_to_dict(base_conninfo)
    parts["dbname"] = "hatchet"
    conn_parts = {key: str(value) for key, value in parts.items() if value is not None}
    return make_conninfo(**conn_parts)


def _hatchet_pg_env(conninfo: str) -> dict[str, str]:
    parts = conninfo_to_dict(conninfo)
    env = os.environ.copy()
    mapping = {
        "host": "PGHOST",
        "hostaddr": "PGHOSTADDR",
        "port": "PGPORT",
        "dbname": "PGDATABASE",
        "user": "PGUSER",
        "password": "PGPASSWORD",
        "sslmode": "PGSSLMODE",
    }
    for key, env_key in mapping.items():
        value = parts.get(key)
        if value:
            env[env_key] = str(value)
    return env


def _default_backup_dir() -> Path:
    cache_root = Path(os.environ.get("ST_WORKSPACES_ROOT", Path.home() / ".local" / "share" / "summitflow" / "workspaces")) / "cache"
    if cache_root.exists() and os.access(cache_root, os.W_OK):
        return cache_root / "hatchet-retention-backups"
    return Path.home() / ".local" / "share" / "summitflow" / "hatchet-retention-backups"


def create_hatchet_retention_backup(
    *,
    conninfo: str | None = None,
    backup_dir: Path | None = None,
    timeout_seconds: int = DEFAULT_BACKUP_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    """Create a custom-format pg_dump of the Hatchet database before pruning."""
    if timeout_seconds <= 0:
        raise ValueError("timeout_seconds must be positive")

    started_at = datetime.now(UTC)
    resolved_conninfo = conninfo or _hatchet_conninfo()
    target_dir = backup_dir or _default_backup_dir()
    target_dir.mkdir(parents=True, exist_ok=True)
    timestamp = started_at.strftime("%Y%m%dT%H%M%SZ")
    backup_path = target_dir / f"hatchet-retention-{timestamp}.dump"

    try:
        pg_env = _hatchet_pg_env(resolved_conninfo)
        client = pg_client(
            "pg_dump", host=pg_env.get("PGHOST", "localhost"), port=pg_env.get("PGPORT", "5432"),
            user=pg_env.get("PGUSER", ""), password=pg_env.get("PGPASSWORD", ""), dbname=pg_env.get("PGDATABASE", "postgres"),
        )
        completed = safe_subprocess.run(
            [
                client,
                "--format=custom",
                "--no-password",
                "--file",
                str(backup_path),
            ],
            env=pg_env,
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout_seconds,
        )
    except Exception:
        with suppress(OSError):
            backup_path.unlink()
        raise

    if completed.returncode != 0:
        with suppress(OSError):
            backup_path.unlink()
        stderr = str(completed.stderr or "").strip()
        raise RuntimeError(
            f"pg_dump failed with return code {completed.returncode}: {stderr[:500]}"
        )

    finished_at = datetime.now(UTC)
    return {
        "path": str(backup_path),
        "size_bytes": backup_path.stat().st_size,
        "started_at": started_at.isoformat(),
        "finished_at": finished_at.isoformat(),
    }


def _existing_target_names(cur: psycopg.Cursor[Any]) -> set[str]:
    names = [target.name for target in RETENTION_TABLES]
    cur.execute(
        """
        SELECT table_name
        FROM information_schema.tables
        WHERE table_schema = 'public'
          AND table_name = ANY(%s)
        """,
        (names,),
    )
    return {str(row[0]) for row in cur.fetchall()}


def _tenant_retention_hours(cur: psycopg.Cursor[Any]) -> dict[str, Any]:
    cur.execute('SELECT "dataRetentionPeriod" FROM "Tenant"')
    raw_periods = [str(row[0]) for row in cur.fetchall() if row[0] is not None]
    if not raw_periods:
        return {
            "retention_hours": DEFAULT_RETENTION_HOURS,
            "periods": [],
            "source": "default",
        }

    parsed: list[float] = []
    invalid: list[str] = []
    for period in raw_periods:
        hours = _parse_duration_hours(period)
        if hours is None:
            invalid.append(period)
        else:
            parsed.append(hours)

    if invalid:
        raise RuntimeError(f"Cannot parse Hatchet tenant retention periods: {invalid}")

    return {
        "retention_hours": max(parsed),
        "periods": raw_periods,
        "source": "hatchet_tenant",
    }


def _get_hatchet_context(
    conninfo: str,
    retention_hours: float | None,
) -> tuple[set[str], dict[str, Any], float]:
    with psycopg.connect(conninfo) as conn, conn.cursor() as cur:
        existing_names = _existing_target_names(cur)
        tenant_retention = _tenant_retention_hours(cur)

    resolved_retention_hours = (
        float(retention_hours) if retention_hours is not None else tenant_retention["retention_hours"]
    )
    if resolved_retention_hours <= 0:
        raise ValueError("retention_hours must be positive")
    return existing_names, tenant_retention, resolved_retention_hours


def _set_maintenance_timeouts(conn: psycopg.Connection[Any]) -> None:
    with conn.cursor() as cur:
        cur.execute("SET lock_timeout = '5s'")
        cur.execute("SET statement_timeout = '30min'")


def _count_expired(
    conn: psycopg.Connection[Any],
    target: HatchetRetentionTable,
    cutoff: datetime,
) -> int:
    with conn.cursor() as cur:
        cur.execute(
            sql.SQL("SELECT count(*) FROM {table} WHERE {column} < %(cutoff)s").format(
                table=sql.Identifier(target.name),
                column=sql.Identifier(target.timestamp_column),
            ),
            {"cutoff": cutoff},
        )
        value = cur.fetchone()
    return int(value[0] if value else 0)


def _delete_batch(
    conn: psycopg.Connection[Any],
    target: HatchetRetentionTable,
    cutoff: datetime,
    batch_size: int,
) -> int:
    with conn.cursor() as cur:
        cur.execute(
            sql.SQL(
                """
                WITH expired AS (
                    SELECT ctid
                    FROM {table}
                    WHERE {column} < %(cutoff)s
                    LIMIT %(batch_size)s
                )
                DELETE FROM {table}
                WHERE ctid IN (SELECT ctid FROM expired)
                """
            ).format(
                table=sql.Identifier(target.name),
                column=sql.Identifier(target.timestamp_column),
            ),
            {"cutoff": cutoff, "batch_size": batch_size},
        )
        deleted = cur.rowcount if cur.rowcount >= 0 else 0
    conn.commit()
    return int(deleted)


def _cleanup_table(
    conn: psycopg.Connection[Any],
    target: HatchetRetentionTable,
    cutoff: datetime,
    *,
    batch_size: int,
    dry_run: bool,
) -> dict[str, Any]:
    expired_before = _count_expired(conn, target, cutoff)
    if dry_run:
        return {
            "expired_before": expired_before,
            "deleted": 0,
            "remaining_expired": expired_before,
        }

    deleted_total = 0
    batches = 0
    while True:
        deleted = _delete_batch(conn, target, cutoff, batch_size)
        if deleted == 0:
            break
        deleted_total += deleted
        batches += 1
        if deleted < batch_size:
            break

    remaining_expired = _count_expired(conn, target, cutoff)
    return {
        "expired_before": expired_before,
        "deleted": deleted_total,
        "remaining_expired": remaining_expired,
        "batches": batches,
    }


def _cleanup_existing_tables(
    conninfo: str,
    targets: tuple[HatchetRetentionTable, ...],
    cutoff: datetime,
    *,
    batch_size: int,
    dry_run: bool,
) -> dict[str, dict[str, Any]]:
    with psycopg.connect(conninfo) as conn:
        _set_maintenance_timeouts(conn)
        return {
            target.name: _cleanup_table(
                conn,
                target,
                cutoff,
                batch_size=batch_size,
                dry_run=dry_run,
            )
            for target in targets
        }


def _vacuum_tables(
    conninfo: str,
    targets: tuple[HatchetRetentionTable, ...],
) -> dict[str, dict[str, Any]]:
    results: dict[str, dict[str, Any]] = {}
    with psycopg.connect(conninfo, autocommit=True) as conn:
        _set_maintenance_timeouts(conn)
        with conn.cursor() as cur:
            for target in targets:
                cur.execute(
                    sql.SQL("VACUUM (ANALYZE) {table}").format(
                        table=sql.Identifier(target.name),
                    )
                )
                results[target.name] = {"status": "completed"}
    return results


def _reap_stale_workers(
    conninfo: str,
    *,
    stale_after_seconds: int,
    dry_run: bool,
) -> dict[str, Any]:
    """Mark long-silent Hatchet workers inactive and drop their expired leases.

    Uses Hatchet's own semantics: the dispatcher flips ``isActive`` false when a
    worker disconnects, and the scheduler only leases workers with a heartbeat
    in the last 5 seconds. Only already-expired WORKER leases are removed, so a
    lease held by a running scheduler is never touched.
    """
    params = {"stale_after_seconds": stale_after_seconds}
    stale_worker = """
        COALESCE(w."lastHeartbeatAt", w."createdAt")
            < NOW() - make_interval(secs => %(stale_after_seconds)s)
    """
    stale_lease = f"""
        l."kind" = 'WORKER'
        AND l."expiresAt" < NOW()
        AND NOT EXISTS (
            SELECT 1 FROM "Worker" w
            WHERE w."id"::text = l."resourceId" AND NOT ({stale_worker})
        )
    """
    with psycopg.connect(conninfo) as conn:
        _set_maintenance_timeouts(conn)
        with conn.cursor() as cur:
            if dry_run:
                cur.execute(
                    f'SELECT count(*) FROM "Worker" w WHERE w."isActive" AND {stale_worker}',
                    params,
                )
                workers = int(cur.fetchone()[0])  # type: ignore[index]
                cur.execute(f'SELECT count(*) FROM "Lease" l WHERE {stale_lease}', params)
                leases = int(cur.fetchone()[0])  # type: ignore[index]
            else:
                cur.execute(
                    f'UPDATE "Worker" w SET "isActive" = false WHERE w."isActive" AND {stale_worker}',
                    params,
                )
                workers = max(cur.rowcount, 0)
                cur.execute(f'DELETE FROM "Lease" l WHERE {stale_lease}', params)
                leases = max(cur.rowcount, 0)
        conn.commit()
    return {
        "stale_after_seconds": stale_after_seconds,
        "workers_deactivated": 0 if dry_run else workers,
        "leases_deleted": 0 if dry_run else leases,
        "stale_active_workers": workers,
        "stale_worker_leases": leases,
    }


def run_hatchet_retention_guard(
    *,
    dry_run: bool = False,
    retention_hours: float | None = None,
    batch_size: int = DEFAULT_BATCH_SIZE,
    backup: bool = True,
    backup_dir: Path | None = None,
    vacuum: bool = True,
    now: datetime | None = None,
    stale_worker_seconds: int = DEFAULT_STALE_WORKER_SECONDS,
) -> dict[str, Any]:
    """Prune Hatchet OLAP/lookup rows older than Hatchet tenant retention.

    Also deactivates workers silent for ``stale_worker_seconds`` and removes
    their expired leases.
    """
    if batch_size <= 0:
        raise ValueError("batch_size must be positive")

    started_at = datetime.now(UTC)
    conninfo = _hatchet_conninfo()
    backup_result: dict[str, Any] | None = None

    try:
        existing_names, tenant_retention, resolved_retention_hours = _get_hatchet_context(
            conninfo,
            retention_hours,
        )
        stale_workers = _reap_stale_workers(
            conninfo,
            stale_after_seconds=stale_worker_seconds,
            dry_run=dry_run,
        )
        cutoff_base = now or datetime.now(UTC)
        if cutoff_base.tzinfo is None:
            cutoff_base = cutoff_base.replace(tzinfo=UTC)
        cutoff = cutoff_base - timedelta(hours=resolved_retention_hours)

        targets = tuple(target for target in RETENTION_TABLES if target.name in existing_names)
        missing_tables = [target.name for target in RETENTION_TABLES if target.name not in existing_names]
        if not targets:
            result = {
                "status": "partial",
                "dry_run": dry_run,
                "retention_hours": resolved_retention_hours,
                "cutoff": cutoff.isoformat(),
                "missing_tables": missing_tables,
                "tables": {},
                "total_deleted": 0,
                "backup": None,
                "vacuum": {},
                "tenant_retention": tenant_retention,
                "stale_workers": stale_workers,
            }
            return result

        if not dry_run and backup:
            backup_result = create_hatchet_retention_backup(
                conninfo=conninfo,
                backup_dir=backup_dir,
            )

        table_results = _cleanup_existing_tables(
            conninfo,
            targets,
            cutoff,
            batch_size=batch_size,
            dry_run=dry_run,
        )
        vacuum_results = (
            _vacuum_tables(conninfo, targets)
            if not dry_run and vacuum and any(result.get("deleted", 0) for result in table_results.values())
            else {}
        )
        total_deleted = sum(int(result.get("deleted", 0)) for result in table_results.values())
        status = "partial" if missing_tables else "success"
        result = {
            "status": status,
            "dry_run": dry_run,
            "retention_hours": resolved_retention_hours,
            "cutoff": cutoff.isoformat(),
            "missing_tables": missing_tables,
            "tables": table_results,
            "total_deleted": total_deleted,
            "backup": backup_result,
            "vacuum": vacuum_results,
            "tenant_retention": tenant_retention,
            "stale_workers": stale_workers,
        }

        if not dry_run:
            finished_at = datetime.now(UTC)
            maintenance_store.record_maintenance_run(
                WORKFLOW_NAME,
                status,
                started_at=started_at,
                finished_at=finished_at,
                rows_cleaned=total_deleted,
                summary=result,
            )

        logger.info(
            "hatchet_retention_guard_completed",
            status=status,
            dry_run=dry_run,
            total_deleted=total_deleted,
            missing_tables=missing_tables,
        )
        return result
    except Exception as exc:
        if not dry_run:
            finished_at = datetime.now(UTC)
            maintenance_store.record_maintenance_run(
                WORKFLOW_NAME,
                "failed",
                started_at=started_at,
                finished_at=finished_at,
                rows_cleaned=0,
                summary={"backup": backup_result},
                error_message=str(exc),
            )
        logger.exception("hatchet_retention_guard_failed", dry_run=dry_run)
        raise
