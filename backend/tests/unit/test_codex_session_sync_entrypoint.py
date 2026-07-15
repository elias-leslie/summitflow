from __future__ import annotations

import importlib.util
from pathlib import Path

SCRIPT_PATH = Path(__file__).resolve().parents[3] / "scripts" / "codex-session-sync.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("codex_session_sync", SCRIPT_PATH)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_entrypoint_runs_with_registered_client_id_and_no_secret(monkeypatch) -> None:
    module = _load_module()
    captured = {}
    monkeypatch.setattr(module, "load_env_credentials", lambda: "summitflow")

    def fake_run_sync(args, **kwargs):
        captured["args"] = args
        captured["kwargs"] = kwargs
        return 0

    monkeypatch.setattr(module, "run_sync", fake_run_sync)

    assert module.main(["--scan"]) == 0
    assert captured["kwargs"]["client_id"] == "summitflow"
    assert "client_secret" not in captured["kwargs"]


def test_entrypoint_skips_only_when_registered_client_id_is_missing(monkeypatch) -> None:
    module = _load_module()
    messages: list[str] = []
    monkeypatch.setattr(module, "load_env_credentials", lambda: "")
    monkeypatch.setattr(module, "log", messages.append)

    assert module.main(["--scan"]) == 0
    assert messages == ["[WARN] Missing SUMMITFLOW_CLIENT_ID; skipping Codex sync"]
