"""Minimal local client for Tether, the per-user session daemon.

Tether owns the tmux sessions of Aico and A-Term and serves a versioned API on a
private 0600 Unix socket. Callers prefer it when it is running and otherwise use
the pre-Tether paths, so every consumer works before and after the cutover.
"""

from __future__ import annotations

import http.client
import json
import os
import socket
import stat
from typing import Any

from ..config import TETHER_DEFAULT_INSTANCE

# Lifecycle states in which Tether serves sessions and roots ("disabled" does not).
_SERVING = {"ready", "reconciling"}
MAX_RESPONSE_BYTES = 1024 * 1024


def socket_path() -> str:
    """The instance control socket: TETHER_SOCKET, else the XDG runtime layout."""
    if override := os.environ.get("TETHER_SOCKET"):
        return override
    runtime = os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}"
    instance = os.environ.get("TETHER_INSTANCE") or TETHER_DEFAULT_INSTANCE
    return f"{runtime}/tether/{instance}/control.sock"


def socket_present(path: str | None = None) -> bool:
    """True when a socket owned by this user exists; never connects."""
    try:
        info = os.lstat(path or socket_path())
    except (OSError, ValueError):
        return False
    return stat.S_ISSOCK(info.st_mode) and info.st_uid == os.getuid()


class _Connection(http.client.HTTPConnection):
    def __init__(self, path: str, timeout: float) -> None:
        super().__init__("tether", timeout=timeout)
        self._socket_path = path

    def connect(self) -> None:
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.settimeout(self.timeout)
        self.sock.connect(self._socket_path)


def request(method: str, path: str, body: dict[str, Any] | None = None, *,
            timeout: float = 2.0, max_bytes: int = MAX_RESPONSE_BYTES) -> tuple[int, Any]:
    """One JSON request; raises OSError/ValueError/HTTPException on transport failure."""
    connection = _Connection(socket_path(), timeout)
    try:
        payload = json.dumps(body).encode() if body is not None else None
        headers = {"content-type": "application/json"} if payload is not None else {}
        connection.request(method, path, body=payload, headers=headers)
        response = connection.getresponse()
        raw = response.read(max_bytes + 1)
        if len(raw) > max_bytes:
            raise ValueError("Tether response exceeds bound")
        return response.status, json.loads(raw) if raw else None
    finally:
        connection.close()


def health(timeout: float = 1.0) -> dict[str, Any] | None:
    """`GET /v1/health`, or None when Tether is absent or unhealthy."""
    if not socket_present():
        return None
    try:
        status, data = request("GET", "/v1/health", timeout=timeout, max_bytes=16 * 1024)
    except (OSError, ValueError, http.client.HTTPException):
        return None
    if status != 200 or not isinstance(data, dict) or data.get("status") != "ok":
        return None
    return data


def available(timeout: float = 1.0) -> bool:
    """Tether answers health and its lifecycle engine serves sessions."""
    data = health(timeout)
    return data is not None and data.get("lifecycle") in _SERVING
