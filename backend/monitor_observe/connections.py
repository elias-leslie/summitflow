"""On-demand Linux socket summary from fixed procfs tables."""
from __future__ import annotations

import base64
import binascii
import json
import socket
import time
from collections import Counter
from pathlib import Path
from typing import Any

from .common import ObserveQueryError, availability, base, error, item, limits, pack

PROC_NET = Path("/proc/net")
TABLES = ("tcp", "tcp6", "udp", "udp6")
MAX_LINES = 4096
MAX_FDS_SCANNED = 100_000
OWNER_SCAN_SECONDS = 2.0
STATES = {"01": "established", "02": "syn_sent", "03": "syn_recv", "04": "fin_wait1",
          "05": "fin_wait2", "06": "time_wait", "07": "closed", "08": "close_wait",
          "09": "last_ack", "0A": "listen", "0B": "closing"}


def _endpoint(raw: str, family: str) -> str | None:
    try:
        address, port = raw.split(":", 1)
        octets = bytes.fromhex(address)
        if family == "ipv4" and len(octets) == 4:
            host = socket.inet_ntop(socket.AF_INET, octets[::-1])
        elif family == "ipv6" and len(octets) == 16:
            host = socket.inet_ntop(socket.AF_INET6,
                                    b"".join(octets[i:i + 4][::-1] for i in range(0, 16, 4)))
        else:
            return None
        return f"[{host}]:{int(port, 16)}" if family == "ipv6" else f"{host}:{int(port, 16)}"
    except (ValueError, OSError):
        return None


def _owner_map(inodes: set[str]) -> tuple[dict[str, list[tuple[int, str | None]]], str, dict[str, int | bool]]:
    """Best effort host PID map, bounded by elapsed time and total FD work."""
    owners: dict[str, list[tuple[int, str | None]]] = {}
    coverage: dict[str, int | bool] = {"pids_seen": 0, "pids_scanned": 0,
                                      "fds_scanned": 0, "scan_capped": False}
    try:
        processes = sorted((p for p in Path("/proc").iterdir() if p.name.isdecimal()),
                           key=lambda p: int(p.name))
        coverage["pids_seen"] = len(processes)
        denied = False
        deadline = time.monotonic() + OWNER_SCAN_SECONDS
        for process in processes:
            if time.monotonic() >= deadline or coverage["fds_scanned"] >= MAX_FDS_SCANNED:
                coverage["scan_capped"] = True
                break
            coverage["pids_scanned"] += 1
            try:
                name = (process / "comm").read_text(encoding="utf-8").strip()[:128]
                for fd in (process / "fd").iterdir():
                    if time.monotonic() >= deadline or coverage["fds_scanned"] >= MAX_FDS_SCANNED:
                        coverage["scan_capped"] = True
                        break
                    coverage["fds_scanned"] += 1
                    try:
                        target = fd.readlink().as_posix()
                    except OSError:
                        continue
                    if target.startswith("socket:[") and target.endswith("]"):
                        inode = target[8:-1]
                        if inode in inodes:
                            owners.setdefault(inode, []).append((int(process.name), name or None))
            except PermissionError:
                denied = True
            except (FileNotFoundError, NotADirectoryError):
                continue
        status = ("partial" if coverage["scan_capped"] else
                  "permission_denied" if denied else "ok")
        return owners, status, coverage
    except OSError as exc:
        return owners, availability(exc), coverage


def _offset(cursor: str | None) -> int:
    if cursor is None:
        return 0
    try:
        if len(cursor) > 32:
            raise ValueError("cursor too long")
        value = json.loads(base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4)))
        offset = value["offset"]
        if type(offset) is not int or not 0 <= offset <= MAX_LINES:
            raise ValueError("invalid offset")
        return offset
    except (ValueError, KeyError, TypeError, binascii.Error) as exc:
        raise ObserveQueryError("invalid connection cursor") from exc


def _cursor(offset: int) -> str:
    return base64.urlsafe_b64encode(json.dumps({"offset": offset}, separators=(",", ":")).encode()).decode().rstrip("=")


def query_connections(*, limit: int = 10, max_bytes: int = 4096,
                      include_addresses: bool = True, include_process: bool = True,
                      cursor: str | None = None) -> dict[str, Any]:
    """Return a page of live host-network sockets with technical endpoints."""
    limits(limit, max_bytes)
    if type(include_addresses) is not bool or type(include_process) is not bool:
        raise ValueError("address and process flags must be boolean")
    offset = _offset(cursor)
    payload = base("connections", {"include_addresses": include_addresses,
                                   "include_process": include_process, "cursor": cursor})
    sockets: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    table_status: dict[str, str] = {}
    counts: Counter[str] = Counter()
    scanned = 0
    for table in TABLES:
        try:
            with (PROC_NET / table).open("r", encoding="ascii") as stream:
                next(stream, None)
                for line in stream:
                    scanned += 1
                    if scanned > MAX_LINES:
                        errors.append(error("source_truncated", str(PROC_NET), "socket row scan cap reached"))
                        break
                    fields = line.split()
                    if len(fields) < 10:
                        continue
                    protocol = "tcp" if table.startswith("tcp") else "udp"
                    family = "ipv6" if table.endswith("6") else "ipv4"
                    state = STATES.get(fields[3], fields[3]) if protocol == "tcp" else "unconnected"
                    counts[f"{table}:{state}"] += 1
                    sockets.append({"protocol": protocol, "family": family, "state": state,
                                    "local": _endpoint(fields[1], family) if include_addresses else "[REDACTED]",
                                    "remote": _endpoint(fields[2], family) if include_addresses else "[REDACTED]",
                                    "inode": fields[9]})
            table_status[table] = "ok"
        except OSError as exc:
            table_status[table] = availability(exc)
            errors.append(error(availability(exc), str(PROC_NET / table)))
        if scanned > MAX_LINES:
            break
    page = sockets[offset:offset + limit + 1]
    owners: dict[str, list[tuple[int, str | None]]] = {}
    owner_status = "not_collected"
    owner_coverage: dict[str, int | bool] = {}
    if include_process and page:
        owners, owner_status, owner_coverage = _owner_map({entry["inode"] for entry in page if entry["inode"] != "0"})
    entries: list[dict[str, Any]] = []
    cursors: list[str | None] = []
    for index, connection in enumerate(page):
        inode = connection["inode"]
        matches = owners.get(inode, [])
        value = {key: value for key, value in connection.items() if key != "inode"}
        value["pid"] = matches[0][0] if matches else None
        value["process_name"] = matches[0][1] if matches else None
        value["pids"] = [pid for pid, _ in matches[:8]]
        value["process_availability"] = ("ok" if matches else
                                         "not_collected" if inode == "0" or not include_process else owner_status)
        entries.append(item(str(PROC_NET), "procfs", "ok", value))
        cursors.append(_cursor(offset + index + 1))
    payload["coverage"] = {"availability": "ok" if any(v == "ok" for v in table_status.values()) else
                           ("permission_denied" if "permission_denied" in table_status.values() else "unsupported"),
                           "tables": table_status, "socket_count_scanned": len(sockets),
                           "summary": dict(sorted(counts.items())), "process_ownership": owner_status,
                           "process_scan": owner_coverage,
                           "addresses_redacted": not include_addresses,
                           "live_pages_may_shift": True, "page_offset": offset,
                           "network_namespace": "collector"}
    payload["errors"] = errors[:8]
    if owner_coverage.get("scan_capped"):
        payload["errors"].append(error("source_truncated", "/proc/*/fd",
                                       "process owner scan cap reached"))
    has_more_sockets = scanned > MAX_LINES or len(sockets) > offset + limit
    result = pack(payload, entries, limit=limit, max_bytes=max_bytes,
                  next_cursors=cursors,
                  more=has_more_sockets or bool(owner_coverage.get("scan_capped")))
    if owner_coverage.get("scan_capped") and not has_more_sockets:
        result["next_cursor"] = None
    return result
