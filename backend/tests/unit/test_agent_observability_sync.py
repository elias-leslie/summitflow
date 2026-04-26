from __future__ import annotations

import importlib.util
from pathlib import Path

SCRIPT_PATH = Path(__file__).resolve().parents[3] / "scripts" / "agent-observability-sync.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("agent_observability_sync", SCRIPT_PATH)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_codex_observability_sync_closes_inactive_sessions_by_default() -> None:
    module = _load_module()

    commands = module._commands(include_tmux=False, include_codex=True, verbose=False)

    assert len(commands) == 1
    assert "--close-inactive" in commands[0]


def test_codex_observability_sync_can_disable_inactive_close(monkeypatch) -> None:
    module = _load_module()
    monkeypatch.setenv("AGENT_OBSERVABILITY_CODEX_CLOSE_INACTIVE", "0")

    commands = module._commands(include_tmux=False, include_codex=True, verbose=False)

    assert "--close-inactive" not in commands[0]
