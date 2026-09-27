"""Bounded, on-demand reads from journals and container logs."""
from __future__ import annotations

import hashlib
import json
import os
import pwd
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
_CONTAINER_ID = re.compile(r"[0-9a-f]{64}\Z")
_CONTAINER_NAME = re.compile(r"[a-zA-Z0-9][a-zA-Z0-9_.-]{0,127}\Z")
_SECRET = re.compile(r"(?i)(\b(?:password|passwd|pwd|secret|token|api[_-]?key|access[_-]?key|private[_-]?key|authorization)\b\s*[:=]\s*)(?:\"[^\"]*\"|'[^']*'|[^\s,;]+)")
_BEARER = re.compile(r"(?i)\bBearer\s+\S+")
_URL_AUTH = re.compile(r"(://[^:/\s]+:)[^@/\s]+(@)")
_PRIVATE_BLOCK = re.compile(r"-----BEGIN (?:[A-Z0-9 ]+ )?PRIVATE KEY-----.*?(?:-----END (?:[A-Z0-9 ]+ )?PRIVATE KEY-----|\Z)", re.S)
_SCOPES = {"user", "system", "container"}
_SERVICE_CURSOR = re.compile(r"ls1\.([0-9a-f]{16})\.(0|[1-9][0-9]{0,5})\Z")


def _services(identity_path: Path | None = None) -> dict[str, str]:
    data = json.loads((identity_path or IDENTITY_PATH).read_text(encoding="utf-8"))
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
        return bytes(output[:MAX_CAPTURE_BYTES]), bytes(stderr[:MAX_CAPTURE_BYTES]), proc.returncode, exceeded
    finally:
        selector.close()
        if proc.poll() is None:
            proc.kill()
            proc.wait()
        proc.stdout.close()
        proc.stderr.close()


def _redact(message: str, cap: int) -> str:
    message = _PRIVATE_BLOCK.sub("[REDACTED PRIVATE KEY]", message)
    message = _BEARER.sub("Bearer [REDACTED]", message)
    message = _SECRET.sub(r"\1[REDACTED]", message)
    message = _URL_AUTH.sub(r"\1[REDACTED]\2", message)
    return bounded_text(message, cap)


def _scope(scope: str) -> str:
    if not isinstance(scope, str) or scope not in _SCOPES:
        raise ObserveQueryError("scope must be user, system, or container")
    return scope


def _owner_uid(scope: str) -> int | None:
    if scope != "user":
        return None
    value = os.environ.get("SUMMITFLOW_MONITOR_OWNER_UID")
    if value is None:
        return None
    if not re.fullmatch(r"[1-9][0-9]{0,9}", value) or int(value) > 2_147_483_647:
        raise ObserveQueryError("invalid monitor owner UID")
    return int(value)


def _command_error(stderr: bytes) -> str:
    message = stderr.decode("utf-8", "replace").lower()
    return "permission_denied" if "permission denied" in message or "insufficient permissions" in message else "error"


def _discover_units(scope: str, owner_uid: int | None = None) -> tuple[set[str], str, bool]:
    """Collect loaded and installed units; stdout is capped by _run."""
    units: set[str] = set()
    status = "ok"
    clipped = False
    if owner_uid is not None:
        try:
            username = pwd.getpwuid(owner_uid).pw_name
        except KeyError:
            return units, "unsupported", False
        prefix = ["runuser", "-u", username, "--", "env",
                  f"XDG_RUNTIME_DIR=/run/user/{owner_uid}",
                  f"DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/{owner_uid}/bus",
                  "systemctl", "--user"]
    else:
        prefix = ["systemctl", "--" + scope]
    for listing in ("list-units", "list-unit-files"):
        argv = [*prefix, listing, "--all", "--type=service",
                "--plain", "--no-legend", "--no-pager"]
        try:
            stdout, stderr, returncode, truncated = _run(argv)
        except (OSError, TimeoutError) as exc:
            status = availability(exc) if not units else "partial"
            continue
        if returncode and not truncated:
            status = _command_error(stderr) if not units else "partial"
            continue
        clipped |= truncated
        for line in stdout.decode("utf-8", "replace").splitlines():
            parts = line.split()
            name = parts[1] if parts and parts[0] == "●" and len(parts) > 1 else parts[0] if parts else ""
            if _UNIT.fullmatch(name):
                units.add(name)
    if units and status != "ok":
        status = "partial"
    return units, status, clipped


def _discover_containers() -> tuple[dict[str, str], str, bool]:
    """Map exact Docker names to full IDs from a bounded local listing."""
    argv = ["docker", "ps", "-a", "--no-trunc", "--format", "{{.ID}}\t{{.Names}}"]
    try:
        stdout, stderr, returncode, clipped = _run(argv)
    except (OSError, TimeoutError) as exc:
        return {}, availability(exc), False
    if returncode and not clipped:
        return {}, _command_error(stderr), False
    lines = stdout.decode("utf-8", "replace").splitlines()
    if clipped and lines:
        lines = lines[:-1]
    containers: dict[str, str] = {}
    for line in lines:
        parts = line.split("\t", 1)
        if len(parts) == 2 and _CONTAINER_ID.fullmatch(parts[0]) and _CONTAINER_NAME.fullmatch(parts[1]):
            containers[parts[1]] = parts[0]
    return containers, "ok", clipped


def query_log_services(*, scope: str = "user", cursor: str | None = None, limit: int = 100,
                       max_bytes: int = 4096) -> dict[str, Any]:
    """Page through a fresh sorted unit catalog; units may move between reads."""
    limits(limit, max_bytes)
    _scope(scope)
    owner_uid = _owner_uid(scope)
    context = hashlib.sha256(f"{scope}\0{owner_uid}".encode()).hexdigest()[:16]
    match = _SERVICE_CURSOR.fullmatch(cursor) if isinstance(cursor, str) else None
    if cursor is not None and (match is None or match.group(1) != context
                               or int(match.group(2)) > 100_000):
        raise ObserveQueryError("invalid log services cursor for scope")
    offset = int(match.group(2)) if match else 0
    payload = base("log_services", {"scope": scope, "cursor": cursor})
    if scope == "container":
        containers, status, clipped = _discover_containers()
        names = sorted(containers)
        source = "docker"
    else:
        units, status, clipped = _discover_units(scope, owner_uid)
        names = sorted(units)
        source = "systemctl"
    payload["coverage"] = {"availability": status, "source": source, "scope": scope,
                           "units_seen": len(names)}
    if status != "ok":
        payload["errors"].append(error(status, source, "service discovery incomplete"))
    if clipped:
        payload["errors"].append(error("source_truncated", source, "service listing reached capture cap"))
    selected = names[offset:]
    entries = [item(source, "docker" if scope == "container" else "systemd", "ok",
                    {"service": name, "scope": scope,
                     **({"container_id": containers[name]} if scope == "container" else {})})
               for name in selected[:limit]]
    cursors = [f"ls1.{context}.{offset + index + 1}" if offset + index + 1 < len(names) else None
               for index in range(len(entries))]
    return pack(payload, entries, limit=limit, max_bytes=max_bytes,
                next_cursors=cursors, more=clipped or len(selected) > limit)


def _query_container_logs(service: str | None, *, since: str | datetime | None,
                          until: str | datetime | None, cursor: str | None,
                          priority: int | None, limit: int, max_bytes: int) -> dict[str, Any]:
    if not isinstance(service, str) or not (_CONTAINER_NAME.fullmatch(service) or _CONTAINER_ID.fullmatch(service)):
        raise ObserveQueryError("container service must be a discovered name or ID")
    if cursor is not None or priority is not None:
        raise ObserveQueryError("container logs do not support cursor or priority")
    containers, status, clipped = _discover_containers()
    selected = next(((name, identifier) for name, identifier in containers.items()
                     if service in (name, identifier)), None)
    if selected is None:
        if status != "ok" or clipped:
            payload = base("logs", {"service": service, "scope": "container"})
            code = status if status != "ok" else "partial"
            payload["coverage"] = {"availability": code, "source": "docker", "scope": "container"}
            payload["errors"].append(error(code, "docker", "container could not be validated"))
            return pack(payload, [], limit=limit, max_bytes=max_bytes)
        raise ObserveQueryError("container is not available")
    name, identifier = selected
    now = datetime.now(UTC)
    start = _time(since, now - timedelta(minutes=15))
    end = _time(until, now)
    if start >= end or datetime.fromisoformat(end) - datetime.fromisoformat(start) > timedelta(days=1):
        raise ObserveQueryError("log window must be positive and at most 24 hours")
    payload = base("logs", {"service": service, "unit": name, "container_id": identifier,
                            "scope": "container", "since": start, "until": end,
                            "priority": None, "cursor": None, "redacted": True})
    argv = ["docker", "logs", "--timestamps", "--since=" + start, "--until=" + end,
            "--tail=" + str(limit + 1), identifier]
    try:
        stdout, stderr, returncode, capture_truncated = _run(argv)
    except (OSError, TimeoutError) as exc:
        code = availability(exc)
        payload["coverage"] = {"availability": code, "source": "docker", "scope": "container",
                               "unit": name, "priority_filter": "unsupported", "pagination": "unsupported"}
        payload["errors"].append(error(code, "docker"))
        return pack(payload, [], limit=limit, max_bytes=max_bytes)
    if returncode and not capture_truncated:
        code = _command_error(stderr)
        payload["coverage"] = {"availability": code, "source": "docker", "scope": "container",
                               "unit": name, "priority_filter": "unsupported", "pagination": "unsupported"}
        payload["errors"].append(error(code, "docker", "docker logs exited with an error"))
        return pack(payload, [], limit=limit, max_bytes=max_bytes)
    if capture_truncated:
        payload["errors"].append(error("source_truncated", "docker", "container logs reached capture cap"))
    entries: list[dict[str, Any]] = []
    malformed = 0
    for stream, raw in (("stdout", stdout), ("stderr", stderr)):
        # Mask PEM blocks before splitting timestamped lines so multiline keys cannot leak.
        lines = _PRIVATE_BLOCK.sub("[REDACTED PRIVATE KEY]", raw.decode("utf-8", "replace")).splitlines()
        if capture_truncated and lines:
            lines = lines[:-1]
        for line in lines:
            stamp_text, separator, message = line.partition(" ")
            if not separator:
                malformed += 1
                continue
            try:
                stamp_dt = datetime.fromisoformat(stamp_text.replace("Z", "+00:00"))
            except ValueError:
                malformed += 1
                continue
            if stamp_dt.tzinfo is None:
                malformed += 1
                continue
            stamp_dt = stamp_dt.astimezone(UTC)
            if not datetime.fromisoformat(start) <= stamp_dt <= datetime.fromisoformat(end):
                continue
            entries.append(item("docker", "docker-logs", "ok",
                                {"service": name, "unit": name, "container_id": identifier,
                                 "scope": "container", "stream": stream,
                                 "message": _redact(message, max(160, max_bytes - 1024))},
                                measured_at=stamp_dt.isoformat()))
    entries.sort(key=lambda row: row["sampled_at"], reverse=True)
    if malformed:
        payload["errors"].append(error("error", "docker", f"{malformed} malformed entries skipped"))
    payload["coverage"] = {"availability": "ok", "source": "docker", "scope": "container",
                           "unit": name, "rows_seen": len(entries), "redacted": True,
                           "priority_filter": "unsupported", "pagination": "unsupported"}
    return pack(payload, entries, limit=limit, max_bytes=max_bytes, more=capture_truncated)


def query_logs(service: str | None = None, *, scope: str = "user",
               since: str | datetime | None = None,
               until: str | datetime | None = None, cursor: str | None = None,
               priority: int | None = None, limit: int = 10,
               max_bytes: int = 4096, identity_path: str | Path | None = None) -> dict[str, Any]:
    """Read a selected unit or search the selected journal within strict bounds."""
    limits(limit, max_bytes)
    _scope(scope)
    if scope == "container":
        return _query_container_logs(service, since=since, until=until, cursor=cursor,
                                     priority=priority, limit=limit, max_bytes=max_bytes)
    owner_uid = _owner_uid(scope)
    unit = None
    if service is not None:
        if not isinstance(service, str) or (not _UNIT.fullmatch(service) and service not in ("backend", "frontend")):
            raise ObserveQueryError("invalid service unit")
        if scope == "user":
            try:
                allowed = _services(Path(identity_path)) if identity_path is not None else _services()
            except (OSError, ValueError, KeyError, TypeError) as exc:
                if service in ("backend", "frontend"):
                    payload = base("logs", {"service": service, "scope": scope})
                    code = availability(exc)
                    payload["coverage"] = {"availability": code, "source": "project.identity.json", "scope": scope}
                    payload["errors"].append(error(code, "project.identity.json"))
                    return pack(payload, [], limit=limit, max_bytes=max_bytes)
                allowed = {}
            unit = allowed.get(service)
        if unit is None:
            discovered, status, clipped = _discover_units(scope, owner_uid)
            if service not in discovered:
                if status != "ok" or clipped:
                    payload = base("logs", {"service": service, "scope": scope})
                    code = status if status != "ok" else "partial"
                    payload["coverage"] = {"availability": code, "source": "systemctl", "scope": scope}
                    payload["errors"].append(error(code, "systemctl", "unit could not be validated"))
                    return pack(payload, [], limit=limit, max_bytes=max_bytes)
                raise ObserveQueryError("service is not an available unit")
            unit = service
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
    requested = {"service": service, "unit": unit, "scope": scope, "since": start, "until": end,
                 "priority": priority, "cursor": cursor, "redacted": True}
    payload = base("logs", requested)
    argv = ["journalctl", *(["--" + scope] if owner_uid is None else [f"_UID={owner_uid}"]),
            "--no-pager", "--output=json", "--quiet",
            "--until=" + end,
            "--reverse", "--lines=" + str(limit + 2 if cursor else limit + 1)]
    if unit:
        argv.append(("_SYSTEMD_USER_UNIT=" if owner_uid is not None else "--unit=") + unit)
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
        payload["coverage"] = {"availability": code, "source": "journalctl", "scope": scope, "unit": unit}
        payload["errors"].append(error(code, "journalctl", str(exc) if isinstance(exc, TimeoutError) else None))
        return pack(payload, [], limit=limit, max_bytes=max_bytes)
    if returncode and not capture_truncated:
        code = _command_error(stderr)
        payload["coverage"] = {"availability": code, "source": "journalctl", "scope": scope, "unit": unit}
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
            row_unit = unit or record.get("_SYSTEMD_USER_UNIT" if scope == "user" else "_SYSTEMD_UNIT")
            if not isinstance(row_unit, str) or not _UNIT.fullmatch(row_unit):
                row_unit = None
            entries.append(item("journalctl", "systemd-journal", "ok",
                                {"service": service, "unit": row_unit, "scope": scope,
                                 "priority": record.get("PRIORITY"),
                                 "message": _redact(message, max(160, max_bytes - 1024))}, measured_at=stamp))
            cursors.append(position)
        except (ValueError, TypeError, KeyError, OverflowError):
            malformed += 1
    if malformed:
        payload["errors"].append(error("error", "journalctl", f"{malformed} malformed entries skipped"))
    payload["coverage"] = {"availability": "ok", "source": "journalctl", "scope": scope, "unit": unit,
                           "rows_seen": len(entries),
                           "redacted": True}
    return pack(payload, entries, limit=limit, max_bytes=max_bytes,
                next_cursors=cursors, more=capture_truncated)
