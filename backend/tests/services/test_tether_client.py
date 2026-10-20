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


def _fake_stat(monkeypatch, *, uid, gid, mode, agent_uid=986, groups=(1000,)):
    info = type("S", (), {"st_mode": stat.S_IFSOCK | mode, "st_uid": uid, "st_gid": gid})()
    monkeypatch.setattr(tether.os, "lstat", lambda _p: info)
    monkeypatch.setattr(tether.os, "getuid", lambda: 1000)
    monkeypatch.setattr(tether.os, "getgid", lambda: 1000)
    monkeypatch.setattr(tether.os, "getgroups", lambda: list(groups))
    monkeypatch.setattr(tether, "_agent_uid", lambda: agent_uid)


def test_agent_socket_shared_to_caller_group_is_present(monkeypatch) -> None:
    _fake_stat(monkeypatch, uid=986, gid=1000, mode=0o660)
    assert tether.socket_present("/run/tether/agent/default/control.sock")
    _fake_stat(monkeypatch, uid=986, gid=1000, mode=0o666)
    assert not tether.socket_present("/x")  # wider than the shared mode
    _fake_stat(monkeypatch, uid=986, gid=977, mode=0o660)
    assert not tether.socket_present("/x")  # not the caller's group
    _fake_stat(monkeypatch, uid=1234, gid=1000, mode=0o660)
    assert not tether.socket_present("/x")  # a stranger's socket
    _fake_stat(monkeypatch, uid=986, gid=1000, mode=0o660, agent_uid=None)
    assert not tether.socket_present("/x")  # no agent user on this host


def test_instances_are_active_first_and_pinned_path_is_exclusive(monkeypatch) -> None:
    monkeypatch.setenv("XDG_RUNTIME_DIR", "/run/user/7")
    monkeypatch.setenv("TETHER_AGENT_SOCKET", "/run/tether/agent/default/control.sock")
    monkeypatch.delenv("TETHER_SOCKET", raising=False)
    owner, agent = "/run/user/7/tether/default/control.sock", "/run/tether/agent/default/control.sock"
    assert tether.sockets() == [owner, agent]
    monkeypatch.setenv("TETHER_SOCKET", agent)
    assert tether.sockets() == [agent, owner]
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
