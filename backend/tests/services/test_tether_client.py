"""Tether client: socket resolution and fail-closed availability."""

from __future__ import annotations

import socket

from app.services import tether


def test_socket_path_follows_override_then_xdg_instance(monkeypatch) -> None:
    monkeypatch.setenv("TETHER_SOCKET", "/fixture/t.sock")
    assert tether.socket_path() == "/fixture/t.sock"
    monkeypatch.delenv("TETHER_SOCKET")
    monkeypatch.setenv("XDG_RUNTIME_DIR", "/run/user/7")
    monkeypatch.delenv("TETHER_INSTANCE", raising=False)
    assert tether.socket_path() == "/run/user/7/tether/default/control.sock"
    monkeypatch.setenv("TETHER_INSTANCE", "dev")
    assert tether.socket_path() == "/run/user/7/tether/dev/control.sock"


def test_absent_or_silent_socket_is_unavailable(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("TETHER_SOCKET", str(tmp_path / "absent.sock"))
    assert not tether.socket_present()
    assert tether.health() is None and not tether.available()
    path = tmp_path / "silent.sock"
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(str(path))
    monkeypatch.setenv("TETHER_SOCKET", str(path))
    try:
        assert tether.socket_present()
        assert tether.health(timeout=0.2) is None
    finally:
        server.close()


def test_available_requires_ok_health_and_serving_lifecycle(monkeypatch) -> None:
    monkeypatch.setattr(tether, "socket_present", lambda *_: True)
    for body, expected in [
        ({"status": "ok", "lifecycle": "ready"}, True),
        ({"status": "ok", "lifecycle": "reconciling"}, True),
        ({"status": "ok", "lifecycle": "disabled"}, False),
        ({"status": "degraded", "lifecycle": "ready"}, False),
    ]:
        monkeypatch.setattr(tether, "request", lambda *a, _b=body, **k: (200, _b))
        assert tether.available() is expected
