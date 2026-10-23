"""Tether client: socket resolution and fail-closed availability."""

from __future__ import annotations

import socket
import stat

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


def _fake_stat(monkeypatch, *, uid, mode=0o600):
    info = type("S", (), {"st_mode": stat.S_IFSOCK | mode, "st_uid": uid, "st_gid": 1000})()
    monkeypatch.setattr(tether.os, "lstat", lambda _p: info)
    monkeypatch.setattr(tether.os, "getuid", lambda: 1000)


def test_only_sockets_the_caller_owns_are_present(monkeypatch) -> None:
    _fake_stat(monkeypatch, uid=1000)
    assert tether.socket_present("/x")
    _fake_stat(monkeypatch, uid=986, mode=0o660)
    assert not tether.socket_present("/x")  # the retired agent user's shared socket


def test_active_instance_only(monkeypatch) -> None:
    monkeypatch.setenv("XDG_RUNTIME_DIR", "/run/user/7")
    monkeypatch.delenv("TETHER_SOCKET", raising=False)
    assert tether.sockets() == ["/run/user/7/tether/default/control.sock"]
    monkeypatch.setenv("TETHER_SOCKET", "/fixture/t.sock")
    assert tether.sockets() == ["/fixture/t.sock"]


def test_request_all_and_first_span_instances(monkeypatch) -> None:
    monkeypatch.setattr(tether, "present_sockets", lambda: ["/a", "/b", "/c"])

    def fake(method, path, body=None, *, socket_file=None, **_):
        if socket_file == "/a":
            raise OSError("down")
        return (404, None) if socket_file == "/b" else (200, {"from": socket_file})

    monkeypatch.setattr(tether, "request", fake)
    assert tether.request_all("/v1/sessions") == [(404, None), (200, {"from": "/c"})]
    assert tether.request_first("GET", "/v1/sessions/x") == (200, {"from": "/c"})
    monkeypatch.setattr(tether, "request", lambda *a, socket_file=None, **k: (404, None))
    assert tether.request_first("GET", "/v1/sessions/x") == (404, None)
