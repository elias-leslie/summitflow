"""Minimal local client for Tether, the per-user session daemon.

Tether owns the tmux sessions of Aico and A-Term and serves a versioned API on a
private 0600 Unix socket. Callers prefer it when it is running and otherwise use
the pre-Tether paths, so every consumer works before and after the cutover.
"""

from __future__ import annotations

import contextlib
import contextvars
import http.client
import json
import os
import pwd
import socket
import stat
import threading
from collections.abc import Callable
from typing import Any

from ..tether_config import (
    TETHER_AGENT_SOCKET_DEFAULT,
    TETHER_AGENT_USER_DEFAULT,
    TETHER_DEFAULT_INSTANCE,
)

# Lifecycle states in which Tether serves sessions and roots ("disabled" does not).
_SERVING = {"ready", "reconciling"}
MAX_RESPONSE_BYTES = 1024 * 1024


def socket_path() -> str:
    """The instance control socket: TETHER_SOCKET, else the XDG runtime layout."""
    if override := os.environ.get("TETHER_SOCKET"):
        return override
    return owner_socket_path()


def owner_socket_path() -> str:
    """The caller's own XDG-layout instance (the rollback instance once agents run as another user)."""
    runtime = os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}"
    instance = os.environ.get("TETHER_INSTANCE") or TETHER_DEFAULT_INSTANCE
    return f"{runtime}/tether/{instance}/control.sock"


def agent_socket_path() -> str:
    """The agent user's instance: TETHER_AGENT_SOCKET, else the configured default."""
    return os.environ.get("TETHER_AGENT_SOCKET") or TETHER_AGENT_SOCKET_DEFAULT


def _agent_uid() -> int | None:
    try:
        return pwd.getpwnam(os.environ.get("TETHER_AGENT_USER") or TETHER_AGENT_USER_DEFAULT).pw_uid
    except KeyError:
        return None


def socket_present(path: str | None = None) -> bool:
    """True when a socket this user may use exists; never connects.

    Either the caller owns it, or it is the agent user's instance socket shared
    to the caller's group (mode 0660, owner = the agent user).
    """
    try:
        info = os.lstat(path or socket_path())
    except (OSError, ValueError):
        return False
    if not stat.S_ISSOCK(info.st_mode):
        return False
    if info.st_uid == os.getuid():
        return True
    return (info.st_uid == _agent_uid() and stat.S_IMODE(info.st_mode) == 0o660
            and info.st_gid in {os.getgid(), *os.getgroups()})


def sockets() -> list[str]:
    """Instances to consult: the active one first, then the other known owner/agent instance.

    A TETHER_SOCKET pinned to some other path means exactly that socket.
    """
    active = socket_path()
    known = [owner_socket_path(), agent_socket_path()]
    if active not in known:
        return [active]
    return [active, *(path for path in dict.fromkeys(known) if path != active)]


def present_sockets() -> list[str]:
    return [path for path in sockets() if socket_present(path)]


class _Connection(http.client.HTTPConnection):
    def __init__(self, path: str, timeout: float) -> None:
        super().__init__("tether", timeout=timeout)
        self._socket_path = path

    def connect(self) -> None:
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.settimeout(self.timeout)
        self.sock.connect(self._socket_path)


def request(method: str, path: str, body: dict[str, Any] | None = None, *,
            timeout: float = 2.0, max_bytes: int = MAX_RESPONSE_BYTES,
            socket_file: str | None = None,
            cancel_check: Callable[[], None] | None = None) -> tuple[int, Any]:
    """One JSON request (active instance unless socket_file); raises OSError/ValueError/HTTPException on transport failure."""
    connection = _Connection(socket_file or socket_path(), timeout)
    stopped = threading.Event()
    cancelled: list[BaseException] = []
    monitor: threading.Thread | None = None

    def watch_cancellation() -> None:
        while not stopped.is_set():
            try:
                assert cancel_check is not None
                cancel_check()
            except BaseException as exc:
                cancelled.append(exc)
                if connection.sock is not None:
                    with contextlib.suppress(OSError):
                        connection.sock.shutdown(socket.SHUT_RDWR)
                return
            stopped.wait(0.2)

    try:
        if cancel_check is not None:
            cancel_check()
            connection.connect()
            context = contextvars.copy_context()
            monitor = threading.Thread(target=context.run, args=(watch_cancellation,), daemon=True, name="tether-cancel")
            monitor.start()
        payload = json.dumps(body).encode() if body is not None else None
        headers = {"content-type": "application/json"} if payload is not None else {}
        connection.request(method, path, body=payload, headers=headers)
        response = connection.getresponse()
        raw = response.read(max_bytes + 1)
        if len(raw) > max_bytes:
            raise ValueError("Tether response exceeds bound")
        if cancelled:
            raise cancelled[0]
        return response.status, json.loads(raw) if raw else None
    except BaseException:
        if cancelled:
            raise cancelled[0] from None
        raise
    finally:
        stopped.set()
        if monitor is not None:
            monitor.join()
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


def request_all(path: str, *, timeout: float = 2.0, max_bytes: int = MAX_RESPONSE_BYTES) -> list[tuple[int, Any]]:
    """GET `path` on every present instance (active first); unreachable instances are skipped."""
    results: list[tuple[int, Any]] = []
    for sock in present_sockets():
        try:
            results.append(request("GET", path, timeout=timeout, max_bytes=max_bytes, socket_file=sock))
        except (OSError, ValueError, http.client.HTTPException):
            continue
    return results


def request_first(method: str, path: str, body: dict[str, Any] | None = None, *,
                  timeout: float = 2.0, max_bytes: int = MAX_RESPONSE_BYTES) -> tuple[int, Any]:
    """Ask each present instance (active first) about one object; the first that has it answers.

    Anything but a 404 (found, or a real error) ends the search. When no
    instance knows it, the active instance's answer (or error) is returned.
    """
    first: tuple[int, Any] | None = None
    error: Exception | None = None
    for sock in present_sockets() or [socket_path()]:
        try:
            status, data = request(method, path, body, timeout=timeout, max_bytes=max_bytes, socket_file=sock)
        except (OSError, ValueError, http.client.HTTPException) as exc:
            error = error or exc
            continue
        if status != 404:
            return status, data
        first = first or (status, data)
    if first is not None:
        return first
    raise error or OSError("no Tether instance reachable")
