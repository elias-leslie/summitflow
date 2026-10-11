"""Session sync sees Tether's sessions and never closes what it cannot see."""

from __future__ import annotations

import importlib.util
import json
import socket
import socketserver
import threading
from http.server import BaseHTTPRequestHandler
from pathlib import Path

import pytest

SCRIPT_PATH = Path(__file__).resolve().parents[3] / "scripts" / "tmux-agent-session-sync.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("tmux_agent_session_sync_tether", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def sync(monkeypatch, tmp_path):
    module = _load_module()
    calls: list[tuple[str, str]] = []
    monkeypatch.setattr(module, "STATE_PATH", tmp_path / "state.json")
    monkeypatch.setattr(module, "_load_client_id", lambda: "summitflow")
    monkeypatch.setattr(module, "_discover_agent_tmux_sessions", lambda: [])
    monkeypatch.setattr(module, "_git_value", lambda *_: None)
    monkeypatch.setattr(module, "_resolve_project_root", lambda _project: None)
    monkeypatch.setattr(module, "_api_request", lambda url, **kw: calls.append((kw.get("method", "GET"), url)) or (200, "{}"))
    monkeypatch.setenv("TETHER_SOCKET", str(tmp_path / "absent.sock"))
    module.calls = calls
    return module


def _closed(module) -> list[str]:
    return [url.split("/sessions/")[1].removesuffix("/close") for method, url in module.calls if url.endswith("/close")]


def _upserted(module) -> list[str]:
    return [url for _method, url in module.calls if "/upsert" in url]


def test_without_tether_stale_sessions_close_as_before(sync):
    sync._save_state({"session_ids": ["tmux:claude-gone"]})
    assert sync.main() == 0
    assert _closed(sync) == ["tmux:claude-gone"]
    assert json.loads(sync.STATE_PATH.read_text())["session_ids"] == []


def test_tether_listed_agent_session_is_kept_and_heartbeated(sync, monkeypatch):
    sync._save_state({"session_ids": ["tmux:codex-portfolio", "tmux:claude-gone"]})
    monkeypatch.setattr(sync, "_tether_catalog", lambda: [
        {"id": "0123abcd", "name": "codex-portfolio", "projectRoot": "/srv/p",
         "tmux": {"sessionName": "aico-0123abcd", "paneId": "%4"}},
        {"id": "89abcdef", "name": None, "tmux": {"sessionName": "aico-89abcdef"}},
    ])
    assert sync.main() == 0
    assert _closed(sync) == ["tmux:claude-gone"]
    assert len(_upserted(sync)) == 1
    assert json.loads(sync.STATE_PATH.read_text())["session_ids"] == ["tmux:codex-portfolio"]


def test_unreadable_tether_closes_nothing(sync, monkeypatch, tmp_path):
    # A bound socket that never listens: present, but the catalog cannot be read.
    path = tmp_path / "t.sock"
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(str(path))
    monkeypatch.setenv("TETHER_SOCKET", str(path))
    sync._save_state({"session_ids": ["tmux:claude-maybe"]})
    try:
        assert sync.main() == 0
    finally:
        server.close()
    assert _closed(sync) == []
    assert json.loads(sync.STATE_PATH.read_text())["session_ids"] == ["tmux:claude-maybe"]


def test_catalog_reads_v1_sessions_over_the_socket(sync, monkeypatch, tmp_path):
    seen: list[str] = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            seen.append(self.path)
            body = json.dumps({"items": [{"id": "0123abcd", "name": "claude-a"}]}).encode()
            self.send_response(200)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format, *args):
            pass

    class Server(socketserver.UnixStreamServer):
        def get_request(self):
            request, _ = super().get_request()
            return request, ("local", 0)

    path = tmp_path / "c.sock"
    server = Server(str(path), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    monkeypatch.setenv("TETHER_SOCKET", str(path))
    try:
        assert sync._tether_catalog() == [{"id": "0123abcd", "name": "claude-a"}]
    finally:
        server.shutdown()
        server.server_close()
    assert seen == ["/v1/sessions"]


def test_absent_socket_means_no_tether(sync):
    assert sync._tether_catalog() is None
