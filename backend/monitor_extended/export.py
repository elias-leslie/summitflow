"""Paginated Flight Recorder replay from committed monitor history.

This intentionally reads the v1 SQLite tables through the reader's read-only,
schema-checked connection. Public series/events/process queries cannot join
individual samples, events and process snapshots into one ordered cursor.
Update this module when the collector schema changes.
"""
from __future__ import annotations

import base64
import hashlib
import json
import sqlite3
import time
from datetime import datetime
from typing import Any

from monitor_observe.common import ObserveQueryError, base, error, limits, pack
from monitor_observe.logs import _redact
from monitor_reader.reader import MonitorReader, _decode_process_blob, _time_ns, _utc

NSEC = 1_000_000_000
MAX_WINDOW = 24 * 3600 * NSEC
MAX_EXPORT_LIMIT = 20
HOST_FIELDS = ("cpu_busy_pct", "memory_total_bytes", "memory_available_bytes",
               "disk_total_bytes", "disk_free_bytes", "cpu_some_avg10_pct",
               "memory_some_avg10_pct", "io_some_avg10_pct", "net_rx_bytes",
               "net_tx_bytes", "disk_read_bytes", "disk_write_bytes")
SECRET_KEYS = ("password", "passwd", "secret", "token", "api_key", "access_key", "private_key", "authorization")


def _cursor(filters: str, position: tuple[int, int, int], newer_sample: int | None) -> str:
    data = {"v": 1, "f": filters, "p": position}
    if newer_sample is not None:
        data["s"] = newer_sample
    raw = json.dumps(data, separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _position(cursor: str | None, filters: str) -> tuple[tuple[int, int, int], int | None] | None:
    if cursor is None:
        return None
    if not isinstance(cursor, str) or len(cursor) > 256:
        raise ObserveQueryError("invalid export cursor")
    try:
        raw = base64.b64decode(cursor + "=" * (-len(cursor) % 4), altchars=b"-_", validate=True)
        data = json.loads(raw)
        position = data["p"]
        if (data.get("v") != 1 or data.get("f") != filters or
            not isinstance(position, list) or len(position) != 3 or
            any(type(value) is not int or value < 0 for value in position) or
            position[1] not in (0, 1) or
            (data.get("s") is not None and (type(data["s"]) is not int or data["s"] < 0))):
            raise ValueError("cursor mismatch")
        return tuple(position), data.get("s")
    except (ValueError, KeyError, TypeError, UnicodeDecodeError) as exc:
        raise ObserveQueryError("invalid export cursor") from exc


def _public_number(value: Any) -> int | float | None:
    return value if type(value) in (int, float) and 0 <= value < 1e30 else None


def _sample(row: sqlite3.Row) -> dict[str, Any]:
    host = json.loads(row["host_json"])
    if not isinstance(host, dict):
        host = {}
    counters = {key: _public_number(host.get(key)) for key in HOST_FIELDS}
    try:
        processes = _decode_process_blob(row["process_blob"])
    except ValueError:
        processes = []
    snapshot = []
    for process in processes:
        if not isinstance(process, dict) or type(process.get("pid")) is not int:
            continue
        snapshot.append({"pid": process["pid"],
                         "start_ticks": _public_number(process.get("start_ticks")),
                         "rss_bytes": _public_number(process.get("rss_bytes")),
                         "cpu_user_ns": _public_number(process.get("cpu_user_ns")),
                         "cpu_system_ns": _public_number(process.get("cpu_system_ns"))})
    snapshot.sort(key=lambda process: (-(process["rss_bytes"] or 0), process["pid"]))
    snapshot = snapshot[:3]
    return {"sampled_at": _utc(row["sampled_at_ns"]), "freshness": "historical",
            "source": "sqlite", "provider": "collector", "mode": row["mode"],
            "unit": None, "availability": "ok", "type": "sample",
            "host": counters, "processes": snapshot,
            "boot_ref": hashlib.sha256(row["boot_id"].encode()).hexdigest()[:16],
            "process_query": {"at": _utc(row["sampled_at_ns"]),
                              "sort": "rss"},
            "process_coverage": {"availability": "leaders_only" if row["mode"] == "baseline" else "ok",
                                 "leaders_only": row["mode"] == "baseline",
                                 "seen": row["processes_seen"],
                                 "permission_denied": row["processes_permission_denied"],
                                 "snapshot_returned": len(snapshot)},
            "capture_active": row["mode"] == "detail", "source_error_count": len(json.loads(row["errors_json"]))}


def _safe_detail(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key)[:128]: ("[REDACTED CREDENTIAL]" if any(secret in str(key).lower() for secret in SECRET_KEYS)
                                 else _safe_detail(entry)) for key, entry in value.items()}
    if isinstance(value, list):
        return [_safe_detail(entry) for entry in value[:32]]
    if isinstance(value, str):
        return _redact(value, 2048)
    return value if value is None or type(value) in (bool, int, float) else str(value)[:160]


def _event(row: sqlite3.Row) -> dict[str, Any]:
    kind = _redact(str(row["kind"]), 128)
    severity = row["severity"] if row["severity"] in {"info", "warning", "error", "critical"} else "unknown"
    try:
        details = _safe_detail(json.loads(row["details_json"]))
    except (ValueError, TypeError):
        details = None
    return {"sampled_at": _utc(row["sampled_at_ns"]), "freshness": "historical",
            "source": "sqlite", "provider": "collector", "mode": None, "unit": None,
            "availability": "ok", "type": "event", "kind": kind, "severity": severity,
            "entity": _redact(str(row["entity"]), 256) if row["entity"] else None,
            "details": details}


def export_capture(reader: MonitorReader, since: str | int | datetime,
                   until: str | int | datetime, *, limit: int = 10,
                   max_bytes: int = 4096, cursor: str | None = None) -> dict[str, Any]:
    """Return a replay page; no file is written and no raw log/argv is read.

    Sample and event rows share one descending cursor. At most `limit+1` rows
    of each type are read, with a 24-hour window and 64 KiB wire ceiling.
    """
    limits(limit, max_bytes)
    if limit > MAX_EXPORT_LIMIT:
        raise ObserveQueryError(f"export limit must be 1..{MAX_EXPORT_LIMIT}")
    now = time.time_ns()
    start = _time_ns(since, now)
    end = _time_ns(until, now)
    if start >= end or end - start > MAX_WINDOW:
        raise ObserveQueryError("export window must be positive and at most 24 hours")
    digest = hashlib.sha256(f"export:1:{start}:{end}".encode()).hexdigest()[:24]
    before = _position(cursor, digest)
    payload = base("capture_export", {"since": _utc(start), "until": _utc(end)})

    def rows(table: str, fields: str, category: int) -> list[sqlite3.Row]:
        condition = "sampled_at_ns>=? AND sampled_at_ns<?"
        args: list[int] = [start, end]
        if before:
            condition += " AND (sampled_at_ns<? OR (sampled_at_ns=? AND id<?))"
            # Events sort before samples at identical timestamps.
            last = before[0]
            same_time_id = last[2] if category == last[1] else (2**63 - 1 if category < last[1] else -1)
            args.extend((last[0], last[0], same_time_id))
        args.append(limit + 1)
        return conn.execute(f"SELECT id,sampled_at_ns,{fields} FROM {table} WHERE {condition} "
                            "ORDER BY sampled_at_ns DESC,id DESC LIMIT ?", args).fetchall()

    with reader._connect() as conn:
        samples = rows("samples", "mode,boot_id,host_json,process_blob,processes_seen,processes_permission_denied,errors_json", 0)
        events = rows("events", "kind,severity,entity,details_json", 1)
    combined = [(row["sampled_at_ns"], 0, row["id"], row) for row in samples]
    combined += [(row["sampled_at_ns"], 1, row["id"], row) for row in events]
    combined.sort(key=lambda entry: entry[:3], reverse=True)
    candidates: list[dict[str, Any]] = []
    cursors: list[str | None] = []
    newer_sample: int | None = before[1] if before else None
    gaps = 0
    for stamp, category, row_id, row in combined[:limit + 1]:
        public = _sample(row) if category == 0 else _event(row)
        if category == 0:
            if newer_sample is not None and newer_sample - stamp > 10 * NSEC:
                public["gap_to_next_seconds"] = round((newer_sample - stamp) / NSEC, 3)
                gaps += 1
            newer_sample = stamp
        candidates.append(public)
        cursors.append(_cursor(digest, (stamp, category, row_id), newer_sample))
    payload["coverage"] = {"availability": "ok" if candidates else "not_collected",
                           "from": _utc(start), "until": _utc(end),
                           "samples_in_page": sum(entry[1] == 0 for entry in combined[:limit]),
                           "events_in_page": sum(entry[1] == 1 for entry in combined[:limit]),
                           "gaps_in_page": gaps,
                           "processes": "top_three_rss_per_sample"}
    if not candidates:
        payload["errors"].append(error("not_collected", "sqlite"))
    return pack(payload, candidates, limit=limit, max_bytes=max_bytes,
                next_cursors=cursors, more=len(combined) > limit)
