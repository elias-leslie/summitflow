"""Runtime CPU and memory metric persistence."""

from __future__ import annotations

import math
import re
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

from psycopg.types.json import Jsonb

from ._sql import static_sql
from .connection import get_connection, get_cursor

_PERCENT_RE = re.compile(r"([-+]?\d+(?:\.\d+)?)")
_BYTES_RE = re.compile(r"^\s*([-+]?\d+(?:\.\d+)?)\s*([kmgtp]?i?b|b)?\s*$", re.I)
_BUCKET_SECONDS = 30

_BYTE_FACTORS = {
    "b": 1,
    "kb": 1000,
    "mb": 1000**2,
    "gb": 1000**3,
    "tb": 1000**4,
    "pb": 1000**5,
    "kib": 1024,
    "mib": 1024**2,
    "gib": 1024**3,
    "tib": 1024**4,
    "pib": 1024**5,
}


def _value(obj: Any, key: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def parse_percent(value: str | None) -> float | None:
    """Parse strings like ``3.5%`` into floats."""
    if not value:
        return None
    match = _PERCENT_RE.search(value)
    if match is None:
        return None
    try:
        return float(match.group(1))
    except ValueError:
        return None


def parse_bytes(value: str | None) -> int | None:
    """Parse Docker/ps byte strings like ``120MiB`` or ``1.4 GB``."""
    if not value:
        return None
    match = _BYTES_RE.match(value.strip())
    if match is None:
        return None
    unit = (match.group(2) or "b").lower()
    try:
        return int(float(match.group(1)) * _BYTE_FACTORS.get(unit, 1))
    except ValueError:
        return None


def parse_mem_usage(value: str | None) -> tuple[int | None, int | None]:
    """Return used and limit bytes from ``used / limit`` memory strings."""
    if not value:
        return None, None
    if "/" not in value:
        return parse_bytes(value), None
    used, limit = value.split("/", 1)
    return parse_bytes(used), parse_bytes(limit)


def _sample_bucket(sampled_at: datetime, bucket_seconds: int = _BUCKET_SECONDS) -> datetime:
    if sampled_at.tzinfo is None:
        sampled_at = sampled_at.replace(tzinfo=UTC)
    epoch = math.floor(sampled_at.timestamp())
    return datetime.fromtimestamp(epoch - (epoch % bucket_seconds), UTC)


def _sample_row(
    status: Any,
    metric: Any | None,
    sampled_at: datetime,
    sample_bucket: datetime,
) -> tuple[Any, ...]:
    service = str(_value(status, "service", _value(metric, "service", "")) or "")
    display_name = str(_value(status, "display_name", service) or service)
    manager = str(_value(status, "manager", "unknown") or "unknown")
    category = str(_value(status, "category", "unknown") or "unknown")
    state = str(_value(status, "state", "unknown") or "unknown")
    status_text = str(_value(status, "status", "") or "")
    source_name = str(_value(metric, "name", _value(status, "name", service)) or service)

    cpu_percent = parse_percent(_value(metric, "cpu_percent", None))
    mem_percent = parse_percent(_value(metric, "mem_percent", None))
    raw_mem_usage = _value(metric, "mem_usage", None)
    mem_used_bytes, mem_limit_bytes = parse_mem_usage(raw_mem_usage)
    net_io = _value(metric, "net_io", None)
    block_io = _value(metric, "block_io", None)

    return (
        sampled_at,
        sample_bucket,
        service,
        display_name,
        manager,
        category,
        state,
        status_text,
        source_name,
        cpu_percent,
        mem_percent,
        mem_used_bytes,
        mem_limit_bytes,
        raw_mem_usage,
        net_io,
        block_io,
        Jsonb(
            {
                "metric_name": _value(metric, "name", None),
                "raw_cpu_percent": _value(metric, "cpu_percent", None),
                "raw_mem_percent": _value(metric, "mem_percent", None),
            }
        ),
    )


def record_runtime_metric_samples(
    statuses: Sequence[Any],
    metrics: Sequence[Any],
    *,
    sampled_at: datetime | None = None,
) -> int:
    """Persist one sampled row per runtime service."""
    if sampled_at is None:
        sampled_at = datetime.now(UTC)
    elif sampled_at.tzinfo is None:
        sampled_at = sampled_at.replace(tzinfo=UTC)

    sample_bucket = _sample_bucket(sampled_at)
    metrics_by_service = {str(_value(metric, "service", "")): metric for metric in metrics}
    seen_services: set[str] = set()
    rows: list[tuple[Any, ...]] = []

    for status in statuses:
        service = str(_value(status, "service", "") or "")
        if not service:
            continue
        seen_services.add(service)
        rows.append(_sample_row(status, metrics_by_service.get(service), sampled_at, sample_bucket))

    for metric in metrics:
        service = str(_value(metric, "service", "") or "")
        if not service or service in seen_services:
            continue
        rows.append(
            _sample_row(
                {
                    "service": service,
                    "display_name": service,
                    "manager": "unknown",
                    "category": "unknown",
                    "state": "running",
                    "status": "",
                    "name": _value(metric, "name", service),
                },
                metric,
                sampled_at,
                sample_bucket,
            )
        )

    if not rows:
        return 0

    with get_connection() as conn, conn.cursor() as cur:
        cur.executemany(
            """
            INSERT INTO runtime_metric_samples (
                sampled_at, sample_bucket, service, display_name, manager,
                category, state, status, source_name, cpu_percent, memory_percent,
                memory_used_bytes, memory_limit_bytes, raw_mem_usage, net_io,
                block_io, metadata
            )
            VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
            )
            ON CONFLICT (service, sample_bucket) DO UPDATE SET
                sampled_at = EXCLUDED.sampled_at,
                display_name = EXCLUDED.display_name,
                manager = EXCLUDED.manager,
                category = EXCLUDED.category,
                state = EXCLUDED.state,
                status = EXCLUDED.status,
                source_name = EXCLUDED.source_name,
                cpu_percent = EXCLUDED.cpu_percent,
                memory_percent = EXCLUDED.memory_percent,
                memory_used_bytes = EXCLUDED.memory_used_bytes,
                memory_limit_bytes = EXCLUDED.memory_limit_bytes,
                raw_mem_usage = EXCLUDED.raw_mem_usage,
                net_io = EXCLUDED.net_io,
                block_io = EXCLUDED.block_io,
                metadata = EXCLUDED.metadata
            """,
            rows,
        )
        conn.commit()
    return len(rows)


def cleanup_old_runtime_metric_samples(*, max_age_days: int = 30) -> int:
    """Delete old runtime metric samples."""
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            DELETE FROM runtime_metric_samples
            WHERE sampled_at < NOW() - (%s * INTERVAL '1 day')
            """,
            (max_age_days,),
        )
        deleted = cur.rowcount
        conn.commit()
    return int(deleted or 0)


def _series_sample(row: tuple[Any, ...]) -> dict[str, Any]:
    return {
        "sampled_at": row[6],
        "sample_count": int(row[7] or 0),
        "state": row[8],
        "status": row[9],
        "cpu_percent": float(row[10]) if row[10] is not None else None,
        "cpu_percent_max": float(row[11]) if row[11] is not None else None,
        "memory_percent": float(row[12]) if row[12] is not None else None,
        "memory_percent_max": float(row[13]) if row[13] is not None else None,
        "memory_used_bytes": int(row[14]) if row[14] is not None else None,
        "memory_used_bytes_max": int(row[15]) if row[15] is not None else None,
        "memory_limit_bytes": int(row[16]) if row[16] is not None else None,
        "raw_mem_usage": row[17],
        "net_io": row[18],
        "block_io": row[19],
    }


def list_runtime_metric_series(
    *,
    service: str | None = None,
    manager: str | None = None,
    category: str | None = None,
    since_minutes: int = 360,
    bucket_seconds: int = 60,
    limit: int = 20000,
) -> list[dict[str, Any]]:
    """Return bucketed runtime metric series for graphing."""
    bucket_seconds = max(15, min(bucket_seconds, 3600))
    since_minutes = max(1, min(since_minutes, 60 * 24 * 30))
    limit = max(1, min(limit, 50000))

    conditions = ["sampled_at >= NOW() - (%s * INTERVAL '1 minute')"]
    condition_params: list[Any] = [since_minutes]
    if service:
        conditions.append("service = %s")
        condition_params.append(service)
    if manager:
        conditions.append("manager = %s")
        condition_params.append(manager)
    if category:
        conditions.append("category = %s")
        condition_params.append(category)
    params: list[Any] = [bucket_seconds, bucket_seconds, *condition_params, limit]

    with get_cursor() as cur:
        cur.execute(
            static_sql(
                f"""
                WITH bucketed AS (
                    SELECT
                        service,
                        MAX(display_name) AS display_name,
                        MAX(manager) AS manager,
                        MAX(category) AS category,
                        to_timestamp(
                            floor(extract(epoch from sampled_at) / %s) * %s
                        ) AS bucket_at,
                        COUNT(*) AS sample_count,
                        (array_agg(state ORDER BY sampled_at DESC))[1] AS latest_state,
                        (array_agg(status ORDER BY sampled_at DESC))[1] AS latest_status,
                        AVG(cpu_percent) AS cpu_percent,
                        MAX(cpu_percent) AS cpu_percent_max,
                        AVG(memory_percent) AS memory_percent,
                        MAX(memory_percent) AS memory_percent_max,
                        AVG(memory_used_bytes)::bigint AS memory_used_bytes,
                        MAX(memory_used_bytes) AS memory_used_bytes_max,
                        MAX(memory_limit_bytes) AS memory_limit_bytes,
                        (array_agg(raw_mem_usage ORDER BY sampled_at DESC))[1] AS raw_mem_usage,
                        (array_agg(net_io ORDER BY sampled_at DESC))[1] AS net_io,
                        (array_agg(block_io ORDER BY sampled_at DESC))[1] AS block_io
                    FROM runtime_metric_samples
                    WHERE {" AND ".join(conditions)}
                    GROUP BY service, bucket_at
                    ORDER BY bucket_at ASC, service ASC
                    LIMIT %s
                )
                SELECT
                    service, display_name, manager, category, bucket_at,
                    sample_count, bucket_at, sample_count, latest_state, latest_status,
                    cpu_percent, cpu_percent_max, memory_percent, memory_percent_max,
                    memory_used_bytes, memory_used_bytes_max, memory_limit_bytes,
                    raw_mem_usage, net_io, block_io
                FROM bucketed
                ORDER BY bucket_at ASC, service ASC
                """
            ),
            params,
        )
        rows = cur.fetchall()

    series_by_service: dict[str, dict[str, Any]] = {}
    for row in rows:
        service_id = str(row[0])
        entry = series_by_service.setdefault(
            service_id,
            {
                "service": service_id,
                "display_name": row[1] or service_id,
                "manager": row[2] or "unknown",
                "category": row[3] or "unknown",
                "samples": [],
            },
        )
        entry["samples"].append(_series_sample(row))

    return list(series_by_service.values())


def summarize_runtime_metric_samples(
    *,
    service: str | None = None,
    since_minutes: int = 360,
    limit: int = 40,
) -> list[dict[str, Any]]:
    """Return compact per-service aggregates for agent troubleshooting."""
    since_minutes = max(1, min(since_minutes, 60 * 24 * 30))
    limit = max(1, min(limit, 200))
    conditions = ["sampled_at >= NOW() - (%s * INTERVAL '1 minute')"]
    params: list[Any] = [since_minutes]
    if service:
        conditions.append("service = %s")
        params.append(service)
    params.append(limit)

    with get_cursor() as cur:
        cur.execute(
            static_sql(
                f"""
                SELECT
                    service,
                    MAX(display_name) AS display_name,
                    MAX(manager) AS manager,
                    MAX(category) AS category,
                    COUNT(*) AS sample_count,
                    AVG(cpu_percent) AS cpu_avg,
                    MAX(cpu_percent) AS cpu_max,
                    AVG(memory_percent) AS mem_pct_avg,
                    MAX(memory_percent) AS mem_pct_max,
                    AVG(memory_used_bytes)::bigint AS mem_bytes_avg,
                    MAX(memory_used_bytes) AS mem_bytes_max,
                    MAX(sampled_at) AS last_sampled_at,
                    (array_agg(state ORDER BY sampled_at DESC))[1] AS latest_state
                FROM runtime_metric_samples
                WHERE {" AND ".join(conditions)}
                GROUP BY service
                ORDER BY COALESCE(MAX(cpu_percent), 0) DESC,
                    COALESCE(MAX(memory_used_bytes), 0) DESC,
                    service ASC
                LIMIT %s
                """
            ),
            params,
        )
        rows = cur.fetchall()

    return [
        {
            "service": row[0],
            "display_name": row[1],
            "manager": row[2],
            "category": row[3],
            "sample_count": int(row[4] or 0),
            "cpu_percent_avg": float(row[5]) if row[5] is not None else None,
            "cpu_percent_max": float(row[6]) if row[6] is not None else None,
            "memory_percent_avg": float(row[7]) if row[7] is not None else None,
            "memory_percent_max": float(row[8]) if row[8] is not None else None,
            "memory_used_bytes_avg": int(row[9]) if row[9] is not None else None,
            "memory_used_bytes_max": int(row[10]) if row[10] is not None else None,
            "last_sampled_at": row[11],
            "state": row[12],
        }
        for row in rows
    ]
