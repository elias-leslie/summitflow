"""Bounded reads of collector-owned SQLite history.

Times accepted by the public methods are UTC ISO-8601 strings, aware datetimes,
or integer Unix nanoseconds. No method creates, migrates, or checkpoints the DB.
"""

from __future__ import annotations

import base64
import binascii
import fcntl
import gzip
import hashlib
import io
import json
import math
import os
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote

SCHEMA_VERSION = "1"
ENVELOPE_VERSION = 1
DB_NAME = "monitor.sqlite3"
MONITOR_MAINTENANCE_LOCK_VERSION = 2
DEFAULT_BYTES = 4096
MAX_BYTES = 65536
MAX_LIMIT = 100
MAX_WINDOW_NS = 24 * 60 * 60 * 1_000_000_000
MAX_ROWS = 20_000
MAX_ROLLUPS = 20_200
MAX_PROCESS_BLOB_BYTES = 8 * 1024 * 1024
NSEC = 1_000_000_000

HOST_METRICS = {
    "cpu_busy_pct": "%",
    "memory_total_bytes": "bytes",
    "memory_available_bytes": "bytes",
    "swap_used_bytes": "bytes",
    "disk_total_bytes": "bytes",
    "disk_free_bytes": "bytes",
    "cpu_some_avg10_pct": "%",
    "memory_some_avg10_pct": "%",
    "io_some_avg10_pct": "%",
    "net_rx_bytes": "bytes",
    "net_tx_bytes": "bytes",
    "disk_read_bytes": "bytes",
    "disk_write_bytes": "bytes",
    "disk_read_bytes_per_second": "bytes/s",
    "disk_write_bytes_per_second": "bytes/s",
    "net_rx_bytes_per_second": "bytes/s",
    "net_tx_bytes_per_second": "bytes/s",
}
HOST_RATE_METRICS = {
    "disk_read_bytes_per_second": "disk_read_bytes",
    "disk_write_bytes_per_second": "disk_write_bytes",
    "net_rx_bytes_per_second": "net_rx_bytes",
    "net_tx_bytes_per_second": "net_tx_bytes",
}
SERVICE_METRICS = {
    "cpu_usage_usec": "microseconds",
    "memory_current_bytes": "bytes",
    "io_read_bytes": "bytes",
    "io_write_bytes": "bytes",
    "cpu_percent": "%",
    "io_read_bytes_per_second": "bytes/s",
    "io_write_bytes_per_second": "bytes/s",
}
SERVICE_RATE_METRICS = {
    "cpu_percent": ("cpu_usage_usec", 100_000),
    "io_read_bytes_per_second": ("io_read_bytes", NSEC),
    "io_write_bytes_per_second": ("io_write_bytes", NSEC),
}
SOURCE_BY_METRIC = {
    "cpu_busy_pct": "/proc/stat",
    "memory_total_bytes": "memory",
    "memory_available_bytes": "memory",
    "swap_used_bytes": "swap",
    "disk_total_bytes": "root_filesystem",
    "disk_free_bytes": "root_filesystem",
    "cpu_some_avg10_pct": "/proc/pressure/cpu",
    "memory_some_avg10_pct": "/proc/pressure/memory",
    "io_some_avg10_pct": "/proc/pressure/io",
    "net_rx_bytes": "/proc/net/dev",
    "net_tx_bytes": "/proc/net/dev",
    "disk_read_bytes": "/proc/diskstats",
    "disk_write_bytes": "/proc/diskstats",
    "disk_read_bytes_per_second": "/proc/diskstats",
    "disk_write_bytes_per_second": "/proc/diskstats",
    "net_rx_bytes_per_second": "/proc/net/dev",
    "net_tx_bytes_per_second": "/proc/net/dev",
}
AVAILABILITY = {
    "ok", "partial", "disabled", "source_truncated", "unsupported", "permission_denied", "timeout", "error", "stale",
    "collector_stopped", "not_collected", "leaders_only", "retention_expired",
}
GPU_HOST_METRICS = {"gpu_max_utilization_pct": ("max_utilization_pct", "%"),
                    "gpu_memory_used_bytes": ("memory_used_bytes", "bytes"),
                    "gpu_memory_total_bytes": ("memory_total_bytes", "bytes")}
GPU_DEVICE_METRICS = {"gpu_utilization_pct": ("utilization_pct", "%"),
                      "gpu_memory_used_bytes": ("memory_used_bytes", "bytes"),
                      "gpu_memory_total_bytes": ("memory_total_bytes", "bytes"),
                      "gpu_temperature_c": ("temperature_c", "celsius"),
                      "gpu_power_w": ("power_w", "watts")}
HOST_METRICS.update({key: unit for key, (_, unit) in GPU_HOST_METRICS.items()})


class MonitorQueryError(ValueError):
    """Invalid or unbounded public query."""


class MonitorSchemaError(MonitorQueryError):
    """Store schema is absent or incompatible; readers cannot migrate it."""


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":"))


def encode_budgeted_json(payload: dict[str, Any], max_bytes: int = DEFAULT_BYTES) -> str:
    """Serialize an already-budgeted envelope and enforce its wire byte cap."""
    if not 256 <= max_bytes <= MAX_BYTES:
        raise MonitorQueryError(f"max_bytes must be 256..{MAX_BYTES}")
    encoded = _json(payload)
    if len(encoded.encode("utf-8")) > max_bytes:
        raise MonitorQueryError("response exceeds max_bytes")
    return encoded


def _time_ns(value: str | int | datetime | None, default: int) -> int:
    if value is None:
        return default
    if isinstance(value, bool):
        raise MonitorQueryError("invalid UTC time")
    if isinstance(value, int):
        result = value
    elif isinstance(value, datetime):
        if value.tzinfo is None:
            raise MonitorQueryError("time needs a UTC offset")
        result = int(value.timestamp() * NSEC)
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                raise ValueError("time needs a UTC offset")
            result = int(parsed.timestamp() * NSEC)
        except ValueError as exc:
            raise MonitorQueryError("invalid UTC time") from exc
    else:
        raise MonitorQueryError("invalid UTC time")
    if not 0 <= result <= 9_223_372_036_854_775_807:
        raise MonitorQueryError("UTC time outside supported range")
    return result


def _utc(ns: int) -> str:
    seconds, fraction = divmod(ns, NSEC)
    return datetime.fromtimestamp(seconds, UTC).strftime("%Y-%m-%dT%H:%M:%S") + f".{fraction:09d}Z"


def _limit(value: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= MAX_LIMIT:
        raise MonitorQueryError(f"limit must be 1..{MAX_LIMIT}")
    return value


def _budget(value: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 256 <= value <= MAX_BYTES:
        raise MonitorQueryError(f"max_bytes must be 256..{MAX_BYTES}")
    return value


def _text_filter(value: str | None, label: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value or len(value) > 128 or "\x00" in value:
        raise MonitorQueryError(f"invalid {label} filter")
    return value


def _decode_json(raw: str | bytes, expected: type) -> Any:
    value = json.loads(raw)
    if not isinstance(value, expected):
        raise MonitorQueryError("malformed monitor store JSON")
    return value


def _decode_process_blob(blob: bytes) -> list[dict[str, Any]]:
    if len(blob) > MAX_PROCESS_BLOB_BYTES:
        raise MonitorQueryError("compressed process blob exceeds cap")
    try:
        with gzip.GzipFile(fileobj=io.BytesIO(blob)) as stream:
            raw = stream.read(MAX_PROCESS_BLOB_BYTES + 1)
        if len(raw) > MAX_PROCESS_BLOB_BYTES:
            raise MonitorQueryError("decoded process blob exceeds cap")
        return _decode_json(raw, list)
    except (OSError, EOFError) as exc:
        raise MonitorQueryError("invalid compressed process blob") from exc


def _availability(metric: str, value: Any, errors: list[dict[str, Any]]) -> str:
    if value is not None:
        return "ok"
    source = SOURCE_BY_METRIC.get(metric)
    for error in errors:
        if error.get("source") in {source, metric}:
            code = error.get("code", "error")
            return code if code in AVAILABILITY else "error"
    return "not_collected"


def _cursor(filters: dict[str, Any], position: tuple[int, int] | tuple[int, int, int, str] | int) -> str:
    digest = hashlib.sha256(_json(filters).encode()).hexdigest()[:24]
    raw = _json({"v": 1, "f": digest, "p": position}).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _cursor_position(cursor: str | None, filters: dict[str, Any], kind: type) -> Any:
    if cursor is None:
        return None
    if not isinstance(cursor, str) or len(cursor) > 1024:
        raise MonitorQueryError("invalid cursor")
    try:
        decoded = base64.b64decode(cursor + "=" * (-len(cursor) % 4), altchars=b"-_", validate=True)
        body = _decode_json(decoded, dict)
        digest = hashlib.sha256(_json(filters).encode()).hexdigest()[:24]
        position = body["p"]
        if body.get("v") != 1 or body.get("f") != digest:
            raise ValueError("cursor filters changed")
        if kind is tuple:
            if not (isinstance(position, list) and len(position) == 2 and all(type(x) is int for x in position)):
                raise ValueError("invalid position")
            return tuple(position)
        if kind is list:
            if not (isinstance(position, list) and len(position) == 4
                    and all(type(x) is int for x in position[:3])
                    and isinstance(position[3], str) and 0 < len(position[3]) <= 128):
                raise ValueError("invalid process observation position")
            return tuple(position)
        if type(position) is not int:
            raise ValueError("invalid position")
        return position
    except (ValueError, KeyError, UnicodeDecodeError, binascii.Error) as exc:
        raise MonitorQueryError("invalid cursor or cursor filters changed") from exc


class MonitorReader:
    """A short-lived connection per query; safe when all other services are down."""

    def __init__(self, state_dir: Path):
        self.db_path = Path(state_dir) / DB_NAME
        self.maintenance_path = Path(state_dir) / "maintenance.lock"
        self.interlock_path = Path(state_dir) / "migration.interlock"

    @contextmanager
    def _reader_slot(self) -> Iterator[None]:
        """Prevent new SQLite readers during explicit page-size maintenance."""
        fd: int | None = None
        try:
            fd = os.open(
                self.maintenance_path,
                os.O_CREAT | os.O_RDWR | os.O_CLOEXEC | os.O_NOFOLLOW,
                0o600,
            )
            fcntl.flock(fd, fcntl.LOCK_SH | fcntl.LOCK_NB)
        except OSError as exc:
            if fd is not None:
                os.close(fd)
            if isinstance(exc, BlockingIOError):
                raise MonitorQueryError("monitor store maintenance in progress") from exc
            raise MonitorQueryError("monitor store unavailable: maintenance lock") from exc
        try:
            if self.interlock_path.exists() or self.interlock_path.is_symlink():
                raise MonitorQueryError("monitor store maintenance recovery required")
            yield
        finally:
            if fd is not None:
                os.close(fd)

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        # URI mode=ro does not create a missing file. The path is quoted as data.
        uri = "file:" + quote(str(self.db_path.resolve()), safe="/") + "?mode=ro"
        with self._reader_slot():
            try:
                connection = sqlite3.connect(uri, uri=True, timeout=1.0)
            except sqlite3.Error as exc:
                raise MonitorQueryError(f"monitor store unavailable: {exc}") from exc
            try:
                connection.row_factory = sqlite3.Row
                connection.execute("PRAGMA query_only=ON")
                row = connection.execute("SELECT value FROM meta WHERE key IN ('schema_version','schema') ORDER BY key DESC LIMIT 1").fetchone()
                if row is None or row[0] != SCHEMA_VERSION:
                    raise MonitorSchemaError(f"unsupported monitor schema: {row[0] if row else 'missing'}")
                yield connection
            except sqlite3.Error as exc:
                raise MonitorQueryError(f"monitor store read failed: {exc}") from exc
            finally:
                connection.close()

    @staticmethod
    def _base(requested: dict[str, Any], now_ns: int) -> dict[str, Any]:
        return {"schema": ENVELOPE_VERSION, "generated_at": _utc(now_ns), "requested": requested,
                "coverage": {}, "items": [], "next_cursor": None, "truncated": False, "errors": []}

    @staticmethod
    def _pack(base: dict[str, Any], candidates: list[tuple[dict[str, Any], Any]],
              filters: dict[str, Any], limit: int, max_bytes: int, more: bool = False) -> dict[str, Any]:
        base["items"] = []
        for item, position in candidates[:limit]:
            trial = {**base, "items": [*base["items"], item]}
            # Reserve room for a cursor and truncation flag before adding.
            trial["next_cursor"] = _cursor(filters, position)
            trial["truncated"] = True
            if len(_json(trial).encode()) > max_bytes:
                more = True
                break
            base["items"].append(item)
        if len(base["items"]) < len(candidates) or len(candidates) > limit:
            more = True
        base["truncated"] = more
        if more and base["items"]:
            base["next_cursor"] = _cursor(filters, candidates[len(base["items"]) - 1][1])
        if more and not base["items"]:
            base["errors"].append({"code": "output_budget", "message": "first item exceeds max_bytes"})
        if len(_json(base).encode()) > max_bytes:
            # A low budget can be consumed by metadata alone. Keep the envelope valid.
            base["coverage"] = {}
            base["requested"] = {}
            base["errors"] = [{"code": "output_budget"}]
            base["next_cursor"] = None
        encode_budgeted_json(base, max_bytes)
        return base

    def status(self, *, now: str | int | datetime | None = None,
               max_bytes: int = DEFAULT_BYTES) -> dict[str, Any]:
        max_bytes = _budget(max_bytes)
        now_ns = _time_ns(now, int(datetime.now(UTC).timestamp() * NSEC))
        base = self._base({"kind": "status"}, now_ns)
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM samples ORDER BY sampled_at_ns DESC,id DESC LIMIT 1").fetchone()
            meta = dict(conn.execute("SELECT key,value FROM meta WHERE key IN ('host_id','boot_id','collector_version')"))
        if row is None:
            base["coverage"] = {"sample_count": 0, "availability": "not_collected"}
            base["errors"] = [{"code": "not_collected", "message": "no committed samples"}]
            return self._pack(base, [], {}, 1, max_bytes)
        host = _decode_json(row["host_json"], dict)
        # Per-device counters are retained for rate validation, not status output.
        host.pop("net_members", None)
        host.pop("disk_members", None)
        # Sparse device detail has a dedicated paged query; preserve status's
        # small default budget even on multi-GPU hosts.
        host.pop("gpu", None)
        services = _decode_json(row["services_json"], dict)
        errors = _decode_json(row["errors_json"], list)
        cadence = 5
        age = max(0.0, (now_ns - row["sampled_at_ns"]) / NSEC)
        freshness = "ok" if age <= cadence * 2 else "stale"
        base["coverage"] = {"sample_count": 1, "latest_sampled_at": _utc(row["sampled_at_ns"]),
                            "age_seconds": round(age, 3), "availability": freshness,
                            "processes_seen": row["processes_seen"],
                            "processes_permission_denied": row["processes_permission_denied"],
                            "process_io_permission_denied": host.get("process_io_permission_denied"),
                            "processes_exited": row["processes_exited"]}
        item = {"sampled_at": _utc(row["sampled_at_ns"]), "freshness": freshness,
                "source": "sqlite", "provider": meta.get("collector_version", "collector"),
                "mode": row["mode"], "unit": None, "availability": freshness,
                "host": host, "services": services, "boot_id": row["boot_id"],
                "host_id": meta.get("host_id"), "source_errors": errors}
        return self._pack(base, [(item, (row["sampled_at_ns"], row["id"]))], {}, 1, max_bytes)

    def series(self, metric: str, *, entity: str = "host", boot_id: str | None = None,
               since: str | int | datetime | None = None,
               until: str | int | datetime | None = None, step: int = 60,
               limit: int = 10, cursor: str | None = None,
               max_bytes: int = DEFAULT_BYTES, now: str | int | datetime | None = None) -> dict[str, Any]:
        max_bytes, limit = _budget(max_bytes), _limit(limit)
        now_ns = _time_ns(now, int(datetime.now(UTC).timestamp() * NSEC))
        end = _time_ns(until, now_ns)
        start = _time_ns(since, end - 15 * 60 * NSEC)
        if start >= end or end - start > 14 * MAX_WINDOW_NS:
            raise MonitorQueryError("series window must be positive and at most 14 days")
        if type(step) is not int or not 5 <= step <= 3600:
            raise MonitorQueryError("step must be 5..3600 seconds")
        if math.ceil((end - start) / (step * NSEC)) > 5000:
            raise MonitorQueryError("series has too many buckets; increase step")
        entity = _text_filter(entity, "entity") or "host"
        boot_id = _text_filter(boot_id, "boot_id")
        gpu_device = entity.startswith("gpu:") and entity[4:].isascii() and entity[4:].isdecimal() \
            and 0 <= int(entity[4:]) < 32
        if entity.startswith("gpu:") and not gpu_device:
            raise MonitorQueryError("GPU entity must be gpu:<index> with index 0..31")
        if gpu_device and boot_id is None:
            raise MonitorQueryError("GPU device series requires boot_id from st monitor gpu")
        if not gpu_device and boot_id is not None:
            raise MonitorQueryError("boot_id applies only to GPU device series")
        metric_catalog = GPU_DEVICE_METRICS if gpu_device else HOST_METRICS if entity == "host" else SERVICE_METRICS
        if metric not in metric_catalog:
            raise MonitorQueryError("metric is not in the public whitelist")
        historical = end - start > MAX_WINDOW_NS
        gpu_metric = gpu_device or metric in GPU_HOST_METRICS
        if historical and gpu_metric:
            raise MonitorQueryError("GPU series requires retained raw observations within 24 hours")
        if historical and (entity != "host" or step < 60):
            raise MonitorQueryError("windows over 24 hours require host metric and step at least 60 seconds")
        if historical and metric in HOST_RATE_METRICS:
            raise MonitorQueryError("host throughput requires raw samples within 24 hours; rollup counters cannot provide a valid rate")
        if historical and (start % (60 * NSEC) or end % (60 * NSEC) or step % 60):
            raise MonitorQueryError("windows over 24 hours require UTC minute-aligned since/until and step")
        if gpu_device:
            unit = GPU_DEVICE_METRICS[metric][1]
        elif entity == "host":
            unit = HOST_METRICS[metric]
        else:
            unit = SERVICE_METRICS[metric]
        filters = {"kind": "series", "metric": metric, "entity": entity,
                   "boot_id": boot_id, "since": start, "until": end, "step": step, "sort": "time_asc"}
        after = _cursor_position(cursor, filters, int)
        base = self._base(filters, now_ns)
        step_ns = step * NSEC
        first_index = after + 1 if after is not None else 0
        query_start = start + first_index * step_ns
        query_end = min(end, start + (first_index + limit + 1) * step_ns)
        if gpu_metric:
            return self._gpu_series(metric, entity, boot_id, unit, start, end, step, limit,
                                    first_index, query_start, query_end, filters, base, max_bytes, now_ns)
        if historical:
            return self._rollup_series(metric, unit, start, end, step, limit, after,
                                       filters, base, max_bytes, now_ns)
        rate_metric = (metric in HOST_RATE_METRICS if entity == "host" else metric in SERVICE_RATE_METRICS)
        read_start = max(0, query_start - 60 * NSEC) if rate_metric else query_start
        with self._connect() as conn:
            rows = conn.execute("SELECT id,sampled_at_ns,monotonic_ns,boot_id,mode,host_json,services_json,errors_json "
                                "FROM samples WHERE mode='baseline' AND sampled_at_ns>=? AND sampled_at_ns<? "
                                "ORDER BY sampled_at_ns,id LIMIT ?",
                                (read_start, query_end, MAX_ROWS + 1)).fetchall()
        if len(rows) > MAX_ROWS:
            raise MonitorQueryError("series row cap reached; narrow the time window")
        rates = (self._host_rates(rows, metric) if entity == "host" else self._service_rates(rows, entity, metric)) if rate_metric else {}
        buckets: dict[int, list[sqlite3.Row]] = {}
        for row in rows:
            if row["sampled_at_ns"] < query_start:
                continue
            index = (row["sampled_at_ns"] - start) // step_ns
            buckets.setdefault(index, []).append(row)
        candidates: list[tuple[dict[str, Any], int]] = []
        available_buckets = 0
        for index in range(first_index, min(math.ceil((end - start) / step_ns), first_index + limit + 1)):
            subset = buckets.get(index, [])
            values: list[float | int] = []
            unavailable: dict[str, int] = {}
            modes: set[str] = set()
            for row in subset:
                data = _decode_json(row["host_json"] if entity == "host" else row["services_json"], dict)
                if entity != "host":
                    service_data = data.get(entity) or {}
                    data = (service_data.get("metrics") or {}) if isinstance(service_data, dict) else {}
                value = rates.get(row["id"]) if rate_metric else (data.get(metric) if isinstance(data, dict) else None)
                errors = _decode_json(row["errors_json"], list)
                if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value):
                    values.append(value)
                else:
                    code = _availability(metric, None, errors)
                    unavailable[code] = unavailable.get(code, 0) + 1
                modes.add(row["mode"])
            expected = math.ceil(min(step_ns, end - (start + index * step_ns)) / (5 * NSEC))
            missing = max(0, expected - len(subset))
            if values and not (rate_metric and subset and rates.get(subset[-1]["id"]) is None):
                available_buckets += 1
            last_rate_invalid = bool(rate_metric and subset and rates.get(subset[-1]["id"]) is None)
            availability = "ok" if values and not last_rate_invalid else (next(iter(unavailable)) if unavailable else "not_collected")
            bucket_start = start + index * step_ns
            item = {"sampled_at": _utc(bucket_start), "freshness": "ok" if now_ns - bucket_start <= 10 * NSEC else "stale",
                    "last_sampled_at": _utc(subset[-1]["sampled_at_ns"]) if subset else None,
                    "source": "sqlite", "provider": "collector", "mode": ",".join(sorted(modes)) or None,
                    "unit": unit, "availability": availability, "entity": entity, "metric": metric,
                    "value": {"min": min(values), "max": max(values), "mean": sum(values) / len(values),
                              "last": values[-1]} if values and not last_rate_invalid else None,
                    "coverage": {"expected": expected, "observed": len(subset), "valid": len(values),
                                 "missing": missing, "unavailable": unavailable}}
            candidates.append((item, index))
        base["coverage"] = {"from": _utc(start), "until": _utc(end),
                            "returned_bucket_candidates": len(candidates),
                            "available_bucket_candidates": available_buckets,
                            "raw_samples": len(rows)}
        return self._pack(base, candidates, filters, limit, max_bytes)

    def _gpu_series(self, metric: str, entity: str, boot_id: str | None, unit: str,
                    start: int, end: int, step: int, limit: int, first_index: int,
                    query_start: int, query_end: int, filters: dict[str, Any],
                    base: dict[str, Any], max_bytes: int, now_ns: int) -> dict[str, Any]:
        """Bucket only completed GPU polls, using provider rather than commit time."""
        step_ns = step * NSEC
        conditions = ["mode='baseline'", "sampled_at_ns>=?", "sampled_at_ns<?"]
        # A completed poll normally reaches the next 5s baseline. Allow one
        # extra baseline interval for write delay without scanning the rest of
        # retained history on every paged query. Later commits can be missed.
        params: list[Any] = [query_start, query_end + 10 * NSEC]
        if boot_id is not None:
            conditions.append("boot_id=?")
            params.append(boot_id)
        params.append(MAX_ROWS + 1)
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT sampled_at_ns,boot_id,host_json,errors_json FROM samples WHERE "
                + " AND ".join(conditions) + " ORDER BY sampled_at_ns,id LIMIT ?", params,
            ).fetchall()
        if len(rows) > MAX_ROWS:
            raise MonitorQueryError("GPU series row cap reached; narrow the time window")
        buckets: dict[int, list[tuple[sqlite3.Row, dict[str, Any], int]]] = {}
        for row in rows:
            gpu = _decode_json(row["host_json"], dict).get("gpu")
            if not isinstance(gpu, dict):
                continue
            observed = gpu.get("observed_at_ns")
            if type(observed) is not int or not 0 <= observed <= row["sampled_at_ns"]:
                # Malformed source timing cannot be presented as a measured value.
                observed = row["sampled_at_ns"]
                gpu = {**gpu, "availability": "error", "invalid_observation_time": True}
            if not query_start <= observed < query_end:
                continue
            index = (observed - start) // step_ns
            buckets.setdefault(index, []).append((row, gpu, observed))
        candidates: list[tuple[dict[str, Any], int]] = []
        available_buckets = 0
        field = (GPU_HOST_METRICS if entity == "host" else GPU_DEVICE_METRICS)[metric][0]
        device_index = int(entity[4:]) if entity != "host" else None
        for index in range(first_index, min(math.ceil((end - start) / step_ns), first_index + limit + 1)):
            subset = buckets.get(index, [])
            values: list[float | int] = []
            unavailable: dict[str, int] = {}
            source_outcomes: dict[str, int] = {}
            last_value: float | int | None = None
            for _row, gpu, _observed in subset:
                outcome = gpu.get("availability")
                outcome = outcome if isinstance(outcome, str) and outcome in AVAILABILITY else "error"
                source_outcomes[outcome] = source_outcomes.get(outcome, 0) + 1
                source = gpu
                if device_index is not None:
                    devices = gpu.get("devices")
                    matches = [device for device in devices if isinstance(device, dict)
                               and type(device.get("index")) is int and device["index"] == device_index] \
                        if isinstance(devices, list) else []
                    source = matches[0] if len(matches) == 1 else {}
                value = source.get(field) if not gpu.get("invalid_observation_time") else None
                if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value >= 0:
                    values.append(value)
                    last_value = value
                else:
                    last_value = None
                    code = outcome if outcome != "ok" else "not_collected"
                    unavailable[code] = unavailable.get(code, 0) + 1
            last = subset[-1] if subset else None
            last_gpu = last[1] if last else {}
            last_observed = last[2] if last else None
            provider = last_gpu.get("provider") if last else None
            provider = provider if isinstance(provider, str) and provider else "nvidia-smi"
            availability = ("ok" if last_value is not None else
                            last_gpu.get("availability", "not_collected") if last else "not_collected")
            if last and last_value is None and availability == "ok":
                availability = "not_collected"
            if availability not in AVAILABILITY:
                availability = "error"
            if last_value is not None:
                available_buckets += 1
            bucket_start = start + index * step_ns
            expected = math.ceil(min(step_ns, end - bucket_start) / (15 * NSEC))
            item = {"sampled_at": _utc(bucket_start),
                    "observed_at": _utc(last_observed) if last_observed is not None else None,
                    "last_sampled_at": _utc(last[0]["sampled_at_ns"]) if last else None,
                    "freshness": "ok" if last_observed is not None and now_ns - last_observed <= 30 * NSEC else "stale",
                    "source": "sqlite", "provider": provider,
                    "provider_availability": last_gpu.get("availability") if last else None,
                    "mode": "baseline" if last else None, "unit": unit,
                    "availability": availability, "entity": entity, "metric": metric,
                    "boot_id": last[0]["boot_id"] if last else boot_id,
                    "device_identity_scope": "sample_boot_id+index" if device_index is not None else None,
                    "value": {"min": min(values), "max": max(values), "mean": sum(values) / len(values),
                              "last": last_value} if values and last_value is not None else None,
                    "coverage": {"expected": expected, "observed": len(subset), "valid": len(values),
                                 "missing": max(0, expected - len(subset)),
                                 "unavailable": unavailable, "source_outcomes": source_outcomes,
                                 "resolution_seconds": 15}}
            candidates.append((item, index))
        base["coverage"] = {"from": _utc(start), "until": _utc(end),
                            "returned_bucket_candidates": len(candidates),
                            "available_bucket_candidates": available_buckets,
                            "raw_samples": len(rows), "resolution_seconds": 15,
                            "commit_lookahead_seconds": 10,
                            "sparse_observations": sum(len(items) for items in buckets.values())}
        return self._pack(base, candidates, filters, limit, max_bytes)

    def gpu(self, *, at: str | int | datetime | None = None,
            limit: int = 10, cursor: str | None = None,
            max_bytes: int = DEFAULT_BYTES,
            now: str | int | datetime | None = None) -> dict[str, Any]:
        """Latest retained GPU poll with bounded, boot-scoped device pages."""
        max_bytes, limit = _budget(max_bytes), _limit(limit)
        now_ns = _time_ns(now, int(datetime.now(UTC).timestamp() * NSEC))
        at_ns = _time_ns(at, now_ns)
        filters = {"kind": "gpu", "at": at_ns if at is not None else None}
        position = _cursor_position(cursor, filters, list)
        offset = position[1] if position is not None else 0
        base = self._base(filters, now_ns)
        with self._connect() as conn:
            if position is None:
                row = conn.execute(
                    "SELECT id,sampled_at_ns,boot_id,host_json,errors_json FROM samples "
                    "WHERE mode='baseline' AND sampled_at_ns<=? AND sampled_at_ns>=? "
                    "AND json_type(host_json,'$.gpu')='object' "
                    "ORDER BY sampled_at_ns DESC,id DESC LIMIT 1",
                    (at_ns, max(0, now_ns - MAX_WINDOW_NS)),
                ).fetchone()
            else:
                row = conn.execute(
                    "SELECT id,sampled_at_ns,boot_id,host_json,errors_json FROM samples WHERE id=?",
                    (position[0],),
                ).fetchone()
                if row is not None and (row["sampled_at_ns"], row["boot_id"]) != position[2:]:
                    row = None
        if row is None:
            availability = "retention_expired" if position is not None or at_ns < now_ns - MAX_WINDOW_NS else "not_collected"
            base["coverage"] = {"availability": availability, "retention_seconds": 24 * 3600}
            base["errors"] = [{"code": availability, "message": "no retained GPU observation at or before time"}]
            return self._pack(base, [], filters, limit, max_bytes)
        host = _decode_json(row["host_json"], dict)
        gpu = host.get("gpu")
        if not isinstance(gpu, dict):
            raise MonitorQueryError("malformed GPU observation")
        devices = gpu.get("devices")
        if not isinstance(devices, list) or len(devices) > 32:
            raise MonitorQueryError("malformed or oversized GPU device list")
        observed = gpu.get("observed_at_ns")
        if type(observed) is not int or not 0 <= observed <= row["sampled_at_ns"]:
            raise MonitorQueryError("malformed GPU observation time")
        provider = gpu.get("provider")
        provider = provider if isinstance(provider, str) and provider else "unknown"
        availability = gpu.get("availability")
        availability = availability if isinstance(availability, str) and availability in AVAILABILITY else "error"
        age = max(0, now_ns - observed) / NSEC
        refresh = gpu.get("status_refresh_seconds")
        static_status = availability in {"disabled", "unsupported"} and type(refresh) is int and 0 < refresh <= 3600
        fresh_limit = refresh + 30 if static_status else 30
        errors = _decode_json(row["errors_json"], list)
        source_errors = [error.get("code") for error in errors if isinstance(error, dict)
                         and error.get("source") == "nvidia-smi" and isinstance(error.get("code"), str)][:8]
        base["coverage"] = {
            "availability": availability, "freshness": "ok" if age <= fresh_limit else "stale",
            "sampled_at": _utc(row["sampled_at_ns"]), "observed_at": _utc(observed),
            "age_seconds": round(age, 3), "provider": provider,
            "boot_id": row["boot_id"], "sample_id": row["id"],
            "device_identity_scope": "sample_boot_id+index",
            "devices_seen": gpu.get("devices_seen"), "devices_scanned": gpu.get("devices_scanned"),
            "missing_fields": gpu.get("missing_fields") if isinstance(gpu.get("missing_fields"), dict) else {},
            "poll_interval_seconds": gpu.get("poll_interval_seconds"),
            "status_refresh_seconds": refresh if static_status else None,
            "max_utilization_pct": gpu.get("max_utilization_pct"),
            "memory_used_bytes": gpu.get("memory_used_bytes"),
            "memory_total_bytes": gpu.get("memory_total_bytes"),
            "source_errors": source_errors,
        }
        candidates: list[tuple[dict[str, Any], tuple[int, int, int, str]]] = []
        for index, device in enumerate(devices[offset:offset + limit + 1], offset + 1):
            if not isinstance(device, dict):
                raise MonitorQueryError("malformed GPU device")
            item = {"sampled_at": _utc(row["sampled_at_ns"]), "observed_at": _utc(observed),
                    "freshness": base["coverage"]["freshness"], "source": "sqlite", "provider": provider,
                    "availability": availability, "boot_id": row["boot_id"],
                    "identity": {"boot_id": row["boot_id"], "index": device.get("index"),
                                 "scope": "sample_boot_id+index"},
                    "device": device}
            candidates.append((item, (row["id"], index, row["sampled_at_ns"], row["boot_id"])))
        return self._pack(base, candidates, filters, limit, max_bytes)

    @staticmethod
    def _host_rates(rows: list[sqlite3.Row], metric: str) -> dict[int, float | None]:
        """Use distinct same-source host counter observations and monotonic time."""
        counter_key = HOST_RATE_METRICS[metric]
        source_key = "disk_source" if counter_key.startswith("disk_") else "net_source"
        rates: dict[int, float | None] = {}
        previous: tuple[str, str, int, dict[str, tuple[int, int, str]]] | None = None
        for row in rows:
            host = _decode_json(row["host_json"], dict)
            counter = host.get(counter_key)
            provider = host.get(source_key)
            members_key = "disk_members" if counter_key.startswith("disk_") else "net_members"
            raw_members = host.get(members_key)
            mono = row["monotonic_ns"]
            members: dict[str, tuple[int, int, str]] = {}
            if isinstance(raw_members, dict) and raw_members:
                for name, raw in raw_members.items():
                    if (not isinstance(name, str) or not name
                            or not isinstance(raw, list) or len(raw) != 3
                            or any(type(value) is not int or value < 0 for value in raw[:2])
                            or not isinstance(raw[2], str) or not raw[2]):
                        members = {}
                        break
                    members[name] = (raw[0], raw[1], raw[2])
            if (not isinstance(provider, str) or not provider
                    or type(counter) is not int or counter < 0 or type(mono) is not int
                    or not members or counter != sum(pair[0 if counter_key.endswith(("read_bytes", "rx_bytes")) else 1]
                                                     for pair in members.values())):
                previous = None
                continue
            value = None
            if previous is not None:
                old_boot, old_provider, old_mono, old_members = previous
                interval = mono - old_mono
                if (row["boot_id"] == old_boot and provider == old_provider
                        and 0 < interval <= 15 * NSEC and members.keys() == old_members.keys()
                        and all(members[name][2] == old_members[name][2]
                                and members[name][0] >= old_members[name][0]
                                and members[name][1] >= old_members[name][1]
                                for name in members)):
                    index = 0 if counter_key.endswith(("read_bytes", "rx_bytes")) else 1
                    delta = sum(members[name][index] - old_members[name][index] for name in members)
                    value = delta * NSEC / interval
            rates[row["id"]] = value
            previous = (row["boot_id"], provider, mono, members)
        return rates

    @staticmethod
    def _service_rates(rows: list[sqlite3.Row], entity: str, metric: str) -> dict[int, float | None]:
        """Rate only distinct snapshots from one source, boot, and monotonic interval."""
        counter_key, scale = SERVICE_RATE_METRICS[metric]
        rates: dict[int, float | None] = {}
        previous: tuple[str, str, tuple[Any, Any] | None, int, int, float] | None = None
        for row in rows:
            service = _decode_json(row["services_json"], dict).get(entity)
            if not isinstance(service, dict):
                previous = None
                continue
            metrics = service.get("metrics")
            if not isinstance(metrics, dict):
                previous = None
                continue
            source = metrics.get("source")
            counter = metrics.get(counter_key)
            if source == "main_pid_fallback":
                observed_at = metrics.get("observed_at_ns")
                mono = metrics.get("observed_monotonic_ns")
            else:
                observed_at = service.get("observed_at_ns")
                mono = row["monotonic_ns"]
            if (not isinstance(source, str) or not source
                    or not isinstance(counter, (int, float)) or isinstance(counter, bool)
                    or not math.isfinite(counter) or counter < 0
                    or type(observed_at) is not int or type(mono) is not int):
                previous = None
                continue
            if previous is not None and observed_at <= previous[3]:
                # A cached service or process scan is not a fresh counter observation.
                continue
            identity = (metrics.get("pid"), metrics.get("start_ticks")) if source == "main_pid_fallback" else None
            value = None
            if previous is not None:
                old_boot, old_source, old_identity, old_at, old_mono, old_counter = previous
                interval = mono - old_mono
                if (row["boot_id"] == old_boot and source == old_source and identity == old_identity
                        and observed_at > old_at and 0 < interval <= 15 * NSEC and counter >= old_counter):
                    value = (counter - old_counter) * scale / interval
            rates[row["id"]] = value
            previous = (row["boot_id"], source, identity, observed_at, mono, counter)
        return rates

    def _rollup_series(self, metric: str, unit: str, start: int, end: int, step: int,
                       limit: int, after: int | None, filters: dict[str, Any],
                       base: dict[str, Any], max_bytes: int, now_ns: int) -> dict[str, Any]:
        minute_ns = 60 * NSEC
        step_ns = step * NSEC
        first_index = after + 1 if after is not None else 0
        query_start = start + first_index * step_ns
        query_end = min(end, start + (first_index + limit + 1) * step_ns)
        with self._connect() as conn:
            rows = conn.execute("SELECT bucket_start_ns,sample_count,values_json,coverage_json "
                                "FROM host_rollups WHERE bucket_start_ns>=? AND bucket_start_ns<? "
                                "ORDER BY bucket_start_ns LIMIT ?",
                                ((query_start // minute_ns) * minute_ns, query_end,
                                 MAX_ROLLUPS + 1)).fetchall()
        if len(rows) > MAX_ROLLUPS:
            raise MonitorQueryError("rollup row cap reached; narrow the time window")
        buckets: dict[int, list[sqlite3.Row]] = {}
        for row in rows:
            index = max(0, (row["bucket_start_ns"] - start) // step_ns)
            buckets.setdefault(index, []).append(row)
        candidates: list[tuple[dict[str, Any], int]] = []
        available_buckets = 0
        for index in range(first_index, min(math.ceil((end - start) / step_ns), first_index + limit + 1)):
            subset = buckets.get(index, [])
            valid = observed = unavailable_count = gap_count = 0
            minimum = maximum = last = None
            weighted_sum = 0.0
            for row in subset:
                values = _decode_json(row["values_json"], dict).get(metric) or {}
                coverage = _decode_json(row["coverage_json"], dict)
                count = values.get("valid_count", 0)
                if type(count) is not int or count < 0:
                    raise MonitorQueryError("malformed rollup count")
                observed += row["sample_count"]
                unavailable_count += coverage.get(f"{metric}_unavailable_count", 0)
                gap_count += coverage.get("gap_count", 0)
                if count:
                    valid += count
                    weighted_sum += values["mean"] * count
                    minimum = values["min"] if minimum is None else min(minimum, values["min"])
                    maximum = values["max"] if maximum is None else max(maximum, values["max"])
                    last = values["last"]
            expected = math.ceil(min(step_ns, end - (start + index * step_ns)) / (5 * NSEC))
            missing = max(0, expected - observed)
            if valid:
                available_buckets += 1
            bucket_start = start + index * step_ns
            item = {"sampled_at": _utc(bucket_start),
                    "freshness": "ok" if now_ns - bucket_start <= 10 * NSEC else "stale",
                    "source": "sqlite_rollup", "provider": "collector", "mode": "rollup",
                    "unit": unit, "availability": "ok" if valid else "not_collected",
                    "entity": "host", "metric": metric,
                    "value": {"min": minimum, "max": maximum, "mean": weighted_sum / valid,
                              "last": last} if valid else None,
                    "coverage": {"expected": expected, "observed": observed, "valid": valid,
                                 "missing": missing, "unavailable": {"not_collected": unavailable_count}
                                 if unavailable_count else {}, "gap_count": gap_count,
                                 "resolution_seconds": 60}}
            candidates.append((item, index))
        base["coverage"] = {"from": _utc(start), "until": _utc(end),
                            "returned_bucket_candidates": len(candidates),
                            "available_bucket_candidates": available_buckets,
                            "rollup_minutes": len(rows), "resolution_seconds": 60}
        return self._pack(base, candidates, filters, limit, max_bytes)

    def processes(self, *, at: str | int | datetime | None = None,
                  name: str | None = None, user: str | None = None,
                  service: str | None = None, sort: str = "rss", view: str = "list",
                  limit: int = 10, cursor: str | None = None,
                  max_bytes: int = DEFAULT_BYTES,
                  now: str | int | datetime | None = None) -> dict[str, Any]:
        max_bytes, limit = _budget(max_bytes), _limit(limit)
        now_ns = _time_ns(now, int(datetime.now(UTC).timestamp() * NSEC))
        at_ns = _time_ns(at, now_ns)
        name, user, service = (_text_filter(name, "name"), _text_filter(user, "user"),
                               _text_filter(service, "service"))
        if sort not in {"cpu", "rss", "io"}:
            raise MonitorQueryError("sort must be cpu, rss, or io")
        if view not in {"list", "tree"}:
            raise MonitorQueryError("view must be list or tree")
        filters = {"kind": "processes", "at": _time_ns(at, now_ns) if at is not None else None,
                   "name": name, "user": user,
                   "service": service, "sort": sort, "view": view}
        position = _cursor_position(cursor, filters, list if view == "tree" else tuple)
        offset = position[1] if position is not None else 0
        base = self._base(filters, now_ns)
        with self._connect() as conn:
            select = "SELECT id,sampled_at_ns,boot_id,mode,process_blob,processes_seen,processes_permission_denied FROM samples "
            if position is None:
                row = conn.execute(select + "WHERE sampled_at_ns<=? ORDER BY sampled_at_ns DESC,id DESC LIMIT 1",
                                   (at_ns,)).fetchone()
            else:
                row = conn.execute(select + "WHERE id=?", (position[0],)).fetchone()
                if (view == "tree" and row is not None
                        and (row["sampled_at_ns"], row["boot_id"]) != position[2:]):
                    # SQLite can reuse an INTEGER PRIMARY KEY after retention.
                    # Never resume a tree against a different observation.
                    row = None
            previous = []
            if row is not None and sort in {"cpu", "io"}:
                previous = conn.execute("SELECT sampled_at_ns,process_blob FROM samples "
                                        "WHERE sampled_at_ns<? AND sampled_at_ns>=? AND boot_id=? "
                                        "ORDER BY sampled_at_ns DESC,id DESC LIMIT 20",
                                        (row["sampled_at_ns"], row["sampled_at_ns"] - 30 * NSEC,
                                         row["boot_id"])).fetchall()
        if row is None:
            base["coverage"] = {"availability": "retention_expired", "sample_count": 0}
            base["errors"] = [{"code": "retention_expired", "message": "no sample at or before time"}]
            return self._pack(base, [], filters, limit, max_bytes)
        cadence = 5 if row["mode"] == "detail" else 15
        age = (at_ns - row["sampled_at_ns"]) / NSEC
        if position is None and age > 2 * cadence:
            base["coverage"] = {"availability": "not_collected", "gap_seconds": round(age, 3),
                                "latest_before_at": _utc(row["sampled_at_ns"])}
            base["errors"] = [{"code": "not_collected", "message": "gap exceeds twice process cadence"}]
            return self._pack(base, [], filters, limit, max_bytes)
        processes = _decode_process_blob(row["process_blob"])
        if not processes and row["processes_permission_denied"]:
            base["coverage"] = {"availability": "permission_denied",
                                "sampled_at": _utc(row["sampled_at_ns"]),
                                "processes_permission_denied": row["processes_permission_denied"]}
            base["errors"] = [{"code": "permission_denied", "message": "process scan was denied"}]
            return self._pack(base, [], filters, limit, max_bytes)
        if (user is not None and not any(isinstance(item, dict) and ("user" in item or "uid" in item) for item in processes)) or (
            service is not None and not any(isinstance(item, dict) and "service" in item for item in processes)
        ):
            base["coverage"] = {"availability": "unsupported", "sampled_at": _utc(row["sampled_at_ns"])}
            base["errors"] = [{"code": "unsupported", "message": "requested process filter is not stored"}]
            return self._pack(base, [], filters, limit, max_bytes)

        def observed_ns(process: dict[str, Any], sample_ns: int) -> int:
            value = process.get("observed_at_ns")
            return value if type(value) is int and 0 <= value <= sample_ns else sample_ns

        def observed_mono_ns(process: dict[str, Any]) -> int | None:
            value = process.get("observed_monotonic_ns")
            return value if type(value) is int and value >= 0 else None

        latest_observed = max((observed_ns(item, row["sampled_at_ns"]) for item in processes
                               if isinstance(item, dict)), default=row["sampled_at_ns"])
        observation_age = (at_ns - latest_observed) / NSEC
        if position is None and observation_age > 2 * cadence:
            base["coverage"] = {"availability": "not_collected", "gap_seconds": round(observation_age, 3),
                                "latest_before_at": _utc(latest_observed)}
            base["errors"] = [{"code": "not_collected", "message": "process observation gap exceeds twice cadence"}]
            return self._pack(base, [], filters, limit, max_bytes)

        prior_by_identity: dict[tuple[int, int], list[tuple[int, dict[str, Any]]]] = {}
        for old_sample in previous:
            for item in _decode_process_blob(old_sample["process_blob"]):
                if isinstance(item, dict) and type(item.get("pid")) is int and type(item.get("start_ticks")) is int:
                    identity = (item["pid"], item["start_ticks"])
                    prior_by_identity.setdefault(identity, []).append(
                        (observed_ns(item, old_sample["sampled_at_ns"]), item))
        numeric_user = user is not None and user.isascii() and user.isdecimal()

        def user_matches(process: dict[str, Any]) -> bool:
            if user is None or process.get("user") == user:
                return True
            uid = process.get("uid")
            return bool(numeric_user and type(uid) is int and uid >= 0 and uid == int(user))

        username_unknown = sum(1 for item in processes if isinstance(item, dict)
                               and not isinstance(item.get("user"), str))
        uid_unknown = sum(1 for item in processes if isinstance(item, dict)
                          and type(item.get("uid")) is not int)
        partial_attribution = (uid_unknown if numeric_user else username_unknown) > 0
        selected = [process for process in processes if isinstance(process, dict)
                    and (name is None or name.casefold() in str(process.get("name", "")).casefold())
                    and user_matches(process)
                    and (service is None or process.get("service") == service)]
        def score(process: dict[str, Any]) -> int | float | None:
            if sort == "rss":
                value = process.get("rss_bytes")
                return value if isinstance(value, (int, float)) and not isinstance(value, bool) and value >= 0 else None
            current_observed = observed_ns(process, row["sampled_at_ns"])
            pid = process.get("pid")
            start_ticks = process.get("start_ticks")
            if not isinstance(pid, int) or isinstance(pid, bool) or not isinstance(start_ticks, int) or isinstance(start_ticks, bool):
                return None
            prior = next(((when, item) for when, item in prior_by_identity.get(
                (pid, start_ticks), []) if when < current_observed), None)
            if prior is None:
                return None
            keys = ("cpu_user_ns", "cpu_system_ns") if sort == "cpu" else ("read_bytes", "write_bytes")
            current_values = [process.get(key) for key in keys]
            prior_values = [prior[1].get(key) for key in keys]
            if not all(type(value) in (int, float) for value in [*current_values, *prior_values]):
                return None
            delta = sum(current_values) - sum(prior_values)
            current_mono = observed_mono_ns(process)
            prior_mono = observed_mono_ns(prior[1])
            if delta < 0 or current_mono is None or prior_mono is None:
                return None
            elapsed_ns = current_mono - prior_mono
            if elapsed_ns <= 0:
                return None
            return delta * (100 if sort == "cpu" else NSEC) / elapsed_ns
        if view == "tree":
            # Rate scores depend on a prior sample that retention may evict while
            # the current sample remains. Cursor pages must keep their order.
            selected.sort(key=lambda process: (
                process["pid"] if type(process.get("pid")) is int else -1,
                process["start_ticks"] if type(process.get("start_ticks")) is int else -1,
            ))
        else:
            selected.sort(key=lambda process: (score(process) is None,
                                             -(score(process) or 0),
                                             process.get("pid", 0), process.get("start_ticks", 0)))
        tree_metadata: dict[int, dict[str, Any]] = {}
        if view == "tree":
            # The entire stored observation establishes ancestry before page budgeting.
            # A PID can be reused, so only a unique parent from this boot, observed
            # at the same instant and started before its child can be linked.
            by_pid: dict[int, list[dict[str, Any]]] = {}
            for process in processes:
                if not isinstance(process, dict):
                    continue
                pid = process.get("pid")
                if type(pid) is int and pid > 0:
                    by_pid.setdefault(pid, []).append(process)
            selected_ids = {id(process) for process in selected}
            parent_of: dict[int, int] = {}
            children: dict[int, list[int]] = {id(process): [] for process in selected}
            for process in selected:
                identity = id(process)
                pid, ppid, start = (process.get(key) for key in ("pid", "ppid", "start_ticks"))
                link = "root"
                parent_identity = None
                if type(ppid) is int and ppid > 0 and ppid != pid:
                    matches = by_pid.get(ppid, [])
                    link = "unavailable_in_capture"
                    if len(matches) > 1:
                        link = "ambiguous_pid"
                    elif matches:
                        parent = matches[0]
                        parent_start = parent.get("start_ticks")
                        if (type(start) is int and type(parent_start) is int
                                and parent_start <= start
                                and observed_ns(parent, row["sampled_at_ns"]) == observed_ns(process, row["sampled_at_ns"])):
                            parent_identity = {"boot_id": row["boot_id"], "pid": ppid,
                                               "start_ticks": parent_start}
                            if id(parent) in selected_ids:
                                link = "linked"
                                parent_of[identity] = id(parent)
                                children[id(parent)].append(identity)
                            else:
                                link = "filtered_out"
                        else:
                            link = "identity_or_observation_mismatch"
                tree_metadata[identity] = {"depth": 0, "children": 0,
                                           "parent_link": link, "parent_identity": parent_identity}
            by_id = {id(process): process for process in selected}
            ordered: list[dict[str, Any]] = []
            visited: set[int] = set()

            def visit(identity: int) -> None:
                pending = [(identity, 0)]
                while pending:
                    current, depth = pending.pop()
                    if current in visited:
                        continue
                    visited.add(current)
                    tree_metadata[current]["depth"] = depth
                    tree_metadata[current]["children"] = len(children[current])
                    ordered.append(by_id[current])
                    pending.extend((child, depth + 1) for child in reversed(children[current]))

            for process in selected:
                if id(process) not in parent_of:
                    visit(id(process))
            # Defensive cycle handling: malformed source data must not hide rows.
            for process in selected:
                if id(process) not in visited:
                    tree_metadata[id(process)]["parent_link"] = "invalid_cycle"
                    visit(id(process))
            selected = ordered
        base["coverage"] = {"availability": "leaders_only" if row["mode"] == "baseline" else "ok",
                            "sampled_at": _utc(row["sampled_at_ns"]), "sample_age_seconds": round(age, 3),
                            "observation_cursor": _cursor(filters, (row["id"], 0,
                                                                    row["sampled_at_ns"], row["boot_id"]))
                            if view == "tree" else _cursor(filters, (row["id"], 0)),
                            "observed_at": _utc(latest_observed),
                            "observation_age_seconds": round(observation_age, 3),
                            "processes_seen": row["processes_seen"],
                            "processes_permission_denied": row["processes_permission_denied"],
                            "matched": len(selected), "leaders_only": row["mode"] == "baseline",
                            "user_attribution": {"username_unknown": username_unknown,
                                                 "uid_unknown": uid_unknown,
                                                 "partial": partial_attribution}}
        if view == "tree":
            missing = sum(meta["parent_link"] == "unavailable_in_capture"
                          for meta in tree_metadata.values())
            base["coverage"]["tree"] = {
                "scope": "stored_observation", "sample_id": row["id"],
                "order": "parent_before_child_pid_siblings",
                "value_metric": sort,
                "captured_rows": len(processes),
                "observed_processes": row["processes_seen"],
                "unavailable_parent_links": missing,
                "permission_denied": row["processes_permission_denied"],
                "filtered": any(value is not None for value in (name, user, service)),
            }
        if user is not None and partial_attribution:
            base["errors"].append({"code": "partial_attribution",
                                   "message": "some process owners could not be attributed for this filter"})
        candidates = []
        for index, process in enumerate(selected[offset:offset + limit + 1], offset + 1):
            process_observed = observed_ns(process, row["sampled_at_ns"])
            item = {"sampled_at": _utc(row["sampled_at_ns"]), "observed_at": _utc(process_observed),
                    "observation_age_seconds": round(max(0, at_ns - process_observed) / NSEC, 3),
                    "freshness": "ok" if now_ns - process_observed <= 2 * cadence * NSEC else "stale",
                    "source": "sqlite", "provider": "collector", "mode": row["mode"],
                    "unit": {"cpu": "%", "rss": "bytes", "io": "bytes/s"}[sort],
                    "availability": "leaders_only" if row["mode"] == "baseline" else "ok",
                    "sort_value": score(process),
                    "sort_availability": "ok" if score(process) is not None else "not_collected",
                    "identity": {"boot_id": row["boot_id"], "pid": process.get("pid"),
                                 "start_ticks": process.get("start_ticks")},
                    "process": process}
            if view == "tree":
                item["tree"] = tree_metadata[id(process)]
            candidate_position = ((row["id"], index, row["sampled_at_ns"], row["boot_id"])
                                  if view == "tree" else (row["id"], index))
            candidates.append((item, candidate_position))
        return self._pack(base, candidates, filters, limit, max_bytes)

    def events(self, *, since: str | int | datetime | None = None,
               until: str | int | datetime | None = None,
               kind: str | None = None, severity: str | None = None,
               entity: str | None = None, limit: int = 10,
               cursor: str | None = None, max_bytes: int = DEFAULT_BYTES,
               now: str | int | datetime | None = None) -> dict[str, Any]:
        max_bytes, limit = _budget(max_bytes), _limit(limit)
        now_ns = _time_ns(now, int(datetime.now(UTC).timestamp() * NSEC))
        end = _time_ns(until, now_ns)
        start = _time_ns(since, end - 15 * 60 * NSEC)
        if start >= end or end - start > 14 * MAX_WINDOW_NS:
            raise MonitorQueryError("events window must be positive and at most 14 days")
        kind, severity, entity = (_text_filter(kind, "kind"), _text_filter(severity, "severity"),
                                  _text_filter(entity, "entity"))
        filters = {"kind": "events", "since": start, "until": end,
                   "event_kind": kind, "severity": severity, "entity": entity, "sort": "time_desc"}
        before = _cursor_position(cursor, filters, tuple)
        conditions = ["sampled_at_ns>=?", "sampled_at_ns<?"]
        params: list[Any] = [start, end]
        for field, value in (("kind", kind), ("severity", severity), ("entity", entity)):
            if value is not None:
                conditions.append(f"{field}=?")
                params.append(value)
        if before is not None:
            conditions.append("(sampled_at_ns,id)<(?,?)")
            params.extend(before)
        params.append(limit + 1)
        with self._connect() as conn:
            rows = conn.execute("SELECT id,sampled_at_ns,kind,severity,entity,details_json "
                                "FROM events WHERE " + " AND ".join(conditions) +
                                " ORDER BY sampled_at_ns DESC,id DESC LIMIT ?", params).fetchall()
        base = self._base(filters, now_ns)
        base["coverage"] = {"returned_event_candidates": len(rows), "from": _utc(start), "until": _utc(end)}
        candidates = []
        for row in rows:
            item = {"id": row["id"], "sampled_at": _utc(row["sampled_at_ns"]), "freshness": "ok" if now_ns - row["sampled_at_ns"] <= 10 * NSEC else "stale",
                    "source": "sqlite", "provider": "collector", "mode": None, "unit": None,
                    "availability": "ok", "kind": row["kind"], "severity": row["severity"],
                    "entity": row["entity"], "details": _decode_json(row["details_json"], dict)}
            candidates.append((item, (row["sampled_at_ns"], row["id"])))
        return self._pack(base, candidates, filters, limit, max_bytes)
