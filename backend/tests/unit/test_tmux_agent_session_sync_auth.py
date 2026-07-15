from __future__ import annotations

import importlib.util
from pathlib import Path

SCRIPT_PATH = Path(__file__).resolve().parents[3] / "scripts" / "tmux-agent-session-sync.py"


class _Response:
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, *_args) -> None:
        return None

    def read(self) -> bytes:
        return b"{}"


def _load_module():
    spec = importlib.util.spec_from_file_location("tmux_agent_session_sync", SCRIPT_PATH)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_tmux_sync_uses_registered_client_id_without_secret(monkeypatch) -> None:
    module = _load_module()
    captured = {}

    def fake_urlopen(req, timeout):
        captured["request"] = req
        captured["timeout"] = timeout
        return _Response()

    monkeypatch.setattr(module.request, "urlopen", fake_urlopen)

    status, _ = module._api_request(
        "http://agent-hub.test/api/sessions",
        method="POST",
        body={"ok": True},
        client_id="summitflow",
        request_source="tmux-agent-session-sync",
    )

    headers = {key.lower(): value for key, value in captured["request"].header_items()}
    assert status == 200
    assert headers["x-client-id"] == "summitflow"
    assert "x-client-secret" not in headers
