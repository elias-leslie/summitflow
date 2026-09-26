"""Bounded journal reads for checked-in managed user services."""
from __future__ import annotations

import json
import os
import re
import selectors
import subprocess
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from .common import ObserveQueryError, availability, base, bounded_text, error, item, limits, pack

IDENTITY_PATH = Path(__file__).resolve().parents[2] / "project.identity.json"
MAX_CAPTURE_BYTES = 512 * 1024
MAX_CURSOR = 1024
TIMEOUT_SECONDS = 5.0
_UNIT = re.compile(r"[a-zA-Z0-9][a-zA-Z0-9_.@-]{0,127}\.service\Z")
_SECRET = re.compile(r"(?i)(\b(?:password|passwd|pwd|secret|token|api[_-]?key|access[_-]?key|authorization)\b\s*[:=]\s*[\"']?)([^\s,;\"']+)")
_BEARER = re.compile(r"(?i)\bBearer\s+\S+")
_URL_AUTH = re.compile(r"(://[^:/\s]+:)[^@/\s]+(@)")


def _services() -> dict[str, str]:
    data = json.loads(IDENTITY_PATH.read_text(encoding="utf-8"))
    services = data["services"]
    names = [services.get("backend"), services.get("frontend"),
             *services.get("default_workers", []), *services.get("optional_workers", [])]
    allowed = {unit: unit for unit in names if isinstance(unit, str) and _UNIT.fullmatch(unit)}
    for alias in ("backend", "frontend"):
        unit = services.get(alias)
        if isinstance(unit, str) and _UNIT.fullmatch(unit):
            allowed[alias] = unit
    return allowed


def _time(value: str | datetime | None, default: datetime) -> str:
    if value is None:
        parsed = default
    elif isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str) and len(value) <= 40:
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ObserveQueryError("invalid UTC time") from exc
    else:
        raise ObserveQueryError("invalid UTC time")
    if parsed.tzinfo is None:
        raise ObserveQueryError("time needs a UTC offset")
    return parsed.astimezone(UTC).isoformat(timespec="seconds")


def _run(argv: list[str]) -> tuple[bytes, bytes, int, bool]:
    """Drain both pipes with a deadline and a combined byte cap."""
    proc = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    selector = selectors.DefaultSelector()
    assert proc.stdout and proc.stderr
    selector.register(proc.stdout, selectors.EVENT_READ, "out")
    selector.register(proc.stderr, selectors.EVENT_READ, "err")
    output, stderr = bytearray(), bytearray()
    deadline = time.monotonic() + TIMEOUT_SECONDS
    exceeded = False
    try:
        while selector.get_map():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("journalctl timed out")
            for key, _ in selector.select(remaining):
                chunk = os.read(key.fd, 8192)
                if not chunk:
                    selector.unregister(key.fileobj)
                    continue
                target = output if key.data == "out" else stderr
                target.extend(chunk)
                if len(output) + len(stderr) > MAX_CAPTURE_BYTES:
                    exceeded = True
                    break
            if exceeded:
                break
        if exceeded:
            proc.kill()
        try:
            proc.wait(timeout=max(0.01, deadline - time.monotonic()))
        except subprocess.TimeoutExpired as exc:
            raise TimeoutError("journalctl timed out") from exc
        return bytes(output[:MAX_CAPTURE_BYTES]), bytes(stderr[:512]), proc.returncode, exceeded
    finally:
        selector.close()
        if proc.poll() is None:
            proc.kill()
            proc.wait()
        proc.stdout.close()
        proc.stderr.close()


def _redact(message: str) -> str:
    message = _BEARER.sub("Bearer [REDACTED]", message)
    message = _SECRET.sub(r"\1[REDACTED]", message)
    message = _URL_AUTH.sub(r"\1[REDACTED]\2", message)
    return bounded_text(message, 1024)


def query_logs(service: str, *, since: str | datetime | None = None,
               until: str | datetime | None = None, cursor: str | None = None,
               priority: int | None = None, limit: int = 10,
               max_bytes: int = 4096) -> dict[str, Any]:
    """Read one managed user unit; never accepts a unit outside project identity."""
    limits(limit, max_bytes)
    try:
        allowed = _services()
    except (OSError, ValueError, KeyError, TypeError) as exc:
        payload = base("logs", {"service": service})
        code = availability(exc)
        payload["coverage"] = {"availability": code, "source": "project.identity.json"}
        payload["errors"].append(error(code, "project.identity.json"))
        return pack(payload, [], limit=limit, max_bytes=max_bytes)
    if not isinstance(service, str) or service not in allowed:
        raise ObserveQueryError("service is not a managed unit")
    unit = allowed[service]
    if priority is not None and (type(priority) is not int or not 0 <= priority <= 7):
        raise ObserveQueryError("priority must be 0..7")
    if cursor is not None and (not isinstance(cursor, str) or not 1 <= len(cursor) <= MAX_CURSOR
                               or any(ord(ch) < 33 or ord(ch) > 126 for ch in cursor)):
        raise ObserveQueryError("invalid journal cursor")
    now = datetime.now(UTC)
    start = _time(since, now - timedelta(minutes=15))
    end = _time(until, now)
    if start >= end or datetime.fromisoformat(end) - datetime.fromisoformat(start) > timedelta(days=1):
        raise ObserveQueryError("log window must be positive and at most 24 hours")
    requested = {"service": service, "since": start, "until": end,
                 "priority": priority, "cursor": cursor, "redacted": True}
    payload = base("logs", requested)
    argv = ["journalctl", "--user", "--no-pager", "--output=json", "--quiet",
            "--unit=" + unit, "--until=" + end,
            "--reverse", "--lines=" + str(limit + 2 if cursor else limit + 1)]
    if cursor:
        argv.append("--cursor=" + cursor)
    else:
        argv.append("--since=" + start)
    if priority is not None:
        argv.append("--priority=" + str(priority))
    try:
        stdout, stderr, returncode, capture_truncated = _run(argv)
    except (OSError, TimeoutError) as exc:
        code = availability(exc)
        payload["coverage"] = {"availability": code, "source": "journalctl"}
        payload["errors"].append(error(code, "journalctl", str(exc) if isinstance(exc, TimeoutError) else None))
        return pack(payload, [], limit=limit, max_bytes=max_bytes)
    if returncode and not capture_truncated:
        message = stderr.decode("utf-8", "replace").lower()
        code = "permission_denied" if "permission denied" in message or "insufficient permissions" in message else "error"
        payload["coverage"] = {"availability": code, "source": "journalctl"}
        payload["errors"].append(error(code, "journalctl", "journalctl exited with an error"))
        return pack(payload, [], limit=limit, max_bytes=max_bytes)
    rows = stdout.split(b"\n")
    if capture_truncated:
        rows = rows[:-1]
        payload["errors"].append(error("source_truncated", "journalctl", "journal output reached capture cap"))
    entries: list[dict[str, Any]] = []
    cursors: list[str | None] = []
    malformed = 0
    for raw in rows:
        if not raw:
            continue
        try:
            record = json.loads(raw)
            stamp_dt = datetime.fromtimestamp(int(record["__REALTIME_TIMESTAMP"]) / 1_000_000, UTC)
            if stamp_dt < datetime.fromisoformat(start) or stamp_dt > datetime.fromisoformat(end):
                continue
            stamp = stamp_dt.isoformat()
            raw_message = record.get("MESSAGE", "")
            message = raw_message if isinstance(raw_message, str) else "[non-text journal message]"
            position = record.get("__CURSOR")
            if not isinstance(position, str) or len(position) > MAX_CURSOR:
                position = None
            if cursor and position == cursor:
                continue
            entries.append(item("journalctl", "systemd-journal", "ok",
                                {"service": service, "priority": record.get("PRIORITY"),
                                 "message": _redact(message)}, measured_at=stamp))
            cursors.append(position)
        except (ValueError, TypeError, KeyError, OverflowError):
            malformed += 1
    if malformed:
        payload["errors"].append(error("error", "journalctl", f"{malformed} malformed entries skipped"))
    payload["coverage"] = {"availability": "ok", "source": "journalctl", "rows_seen": len(entries),
                           "redacted": True}
    return pack(payload, entries, limit=limit, max_bytes=max_bytes,
                next_cursors=cursors, more=capture_truncated)
