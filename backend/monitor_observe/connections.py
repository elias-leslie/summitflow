"""On-demand Linux socket summary from fixed procfs tables."""
from __future__ import annotations

import socket
from collections import Counter
from pathlib import Path
from typing import Any

from .common import availability, base, error, item, limits, pack

PROC_NET = Path("/proc/net")
TABLES = ("tcp", "tcp6", "udp", "udp6")
MAX_LINES = 4096
MAX_PIDS = 256
MAX_FDS = 256
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


def _owner_map(inodes: set[str]) -> tuple[dict[str, int], str, dict[str, int | bool]]:
    """Best effort process map; only traverses numeric proc entries with bounded fd counts."""
    owners: dict[str, int] = {}
    coverage: dict[str, int | bool] = {"pids_seen": 0, "pids_scanned": 0,
                                      "fds_scanned": 0, "scan_capped": False}
    try:
        processes = sorted((p for p in Path("/proc").iterdir() if p.name.isdecimal()),
                           key=lambda p: int(p.name))
        coverage["pids_seen"] = len(processes)
        if len(processes) > MAX_PIDS:
            coverage["scan_capped"] = True
        denied = False
        for process in processes[:MAX_PIDS]:
            coverage["pids_scanned"] += 1
            try:
                fds = list((process / "fd").iterdir())
                if len(fds) > MAX_FDS:
                    coverage["scan_capped"] = True
                for fd in fds[:MAX_FDS]:
                    coverage["fds_scanned"] += 1
                    try:
                        target = fd.readlink().as_posix()
                    except OSError:
                        continue
                    if target.startswith("socket:[") and target.endswith("]"):
                        inode = target[8:-1]
                        if inode in inodes:
                            owners.setdefault(inode, int(process.name))
            except PermissionError:
                denied = True
            except (FileNotFoundError, NotADirectoryError):
                continue
        status = ("permission_denied" if denied else
                  "not_collected" if coverage["scan_capped"] else "ok")
        return owners, status, coverage
    except OSError as exc:
        return owners, availability(exc), coverage


def query_connections(*, limit: int = 10, max_bytes: int = 4096,
                      include_addresses: bool = False, include_process: bool = False) -> dict[str, Any]:
    """Return counts and a bounded socket list; addresses are masked by default."""
    limits(limit, max_bytes)
    if type(include_addresses) is not bool or type(include_process) is not bool:
        raise ValueError("address and process flags must be boolean")
    payload = base("connections", {"include_addresses": include_addresses,
                                   "include_process": include_process})
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
    owners: dict[str, int] = {}
    owner_status = "not_collected"
    owner_coverage: dict[str, int | bool] = {}
    if include_process and sockets:
        owners, owner_status, owner_coverage = _owner_map({entry["inode"] for entry in sockets})
    entries: list[dict[str, Any]] = []
    for connection in sockets[:limit + 1]:
        inode = connection.pop("inode")
        connection["pid"] = owners.get(inode) if include_process else None
        connection["process_availability"] = ("ok" if inode in owners else
                                              "not_collected" if owner_status == "ok" else owner_status)
        entries.append(item(str(PROC_NET), "procfs", "ok", connection))
    payload["coverage"] = {"availability": "ok" if any(v == "ok" for v in table_status.values()) else
                           ("permission_denied" if "permission_denied" in table_status.values() else "unsupported"),
                           "tables": table_status, "socket_count_scanned": len(sockets),
                           "summary": dict(sorted(counts.items())), "process_ownership": owner_status,
                           "process_scan": owner_coverage,
                           "addresses_redacted": not include_addresses}
    payload["errors"] = errors[:8]
    if owner_coverage.get("scan_capped"):
        payload["errors"].append(error("source_truncated", "/proc/*/fd",
                                       "process owner scan cap reached"))
    return pack(payload, entries, limit=limit, max_bytes=max_bytes,
                more=scanned > MAX_LINES or len(sockets) > limit or bool(owner_coverage.get("scan_capped")))
