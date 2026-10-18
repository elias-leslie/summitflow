"""Which local Unix user is on the other end of a loopback connection.

A loopback caller's address says nothing about who it is: the owner, the agent
user and the app user all connect from 127.0.0.1. The kernel does know the
owning uid of each TCP socket (``/proc/net/tcp[6]``), and a process cannot
choose another user's uid, so the uid is a credential where the address is not.
"""

from __future__ import annotations

import pwd
import socket
from ipaddress import IPv6Address, ip_address
from pathlib import Path

from starlette.requests import Request

_TABLES = (Path("/proc/net/tcp"), Path("/proc/net/tcp6"))


def _proc_address(host: str, port: int) -> tuple[Path, str] | None:
    """The /proc/net table and ``ADDR:PORT`` text the kernel prints for this endpoint."""
    try:
        address = ip_address(host)
    except ValueError:
        return None
    if isinstance(address, IPv6Address):
        mapped = address.ipv4_mapped
        if mapped is None:
            raw = socket.inet_pton(socket.AF_INET6, host)
            words = b"".join(raw[i : i + 4][::-1] for i in range(0, 16, 4))
            return _TABLES[1], f"{words.hex().upper()}:{port:04X}"
        address = mapped
    return _TABLES[0], f"{address.packed[::-1].hex().upper()}:{port:04X}"


def peer_uid(request: Request) -> int | None:
    """Owning uid of the client socket of this connection, or None when it cannot be told."""
    client, server = request.scope.get("client"), request.scope.get("server")
    if not client or not server or client[1] is None or server[1] is None:
        return None
    local, remote = _proc_address(client[0], client[1]), _proc_address(server[0], server[1])
    if local is None or remote is None or local[0] != remote[0]:
        return None
    try:
        lines = local[0].read_text().splitlines()[1:]
    except OSError:
        return None
    for line in lines:
        fields = line.split()
        if len(fields) > 7 and fields[1] == local[1] and fields[2] == remote[1]:
            return int(fields[7])
    return None


def uids_for_users(names: str) -> frozenset[int]:
    """Uids of a comma-separated list of user names (numbers pass through); unknown names are skipped."""
    uids: set[int] = set()
    for name in (part.strip() for part in names.split(",")):
        if not name:
            continue
        if name.isdigit():
            uids.add(int(name))
            continue
        try:
            uids.add(pwd.getpwnam(name).pw_uid)
        except KeyError:
            continue
    return frozenset(uids)
