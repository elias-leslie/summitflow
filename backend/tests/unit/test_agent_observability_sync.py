from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

SCRIPT_PATH = Path(__file__).resolve().parents[3] / "scripts" / "agent-observability-sync.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("agent_observability_sync", SCRIPT_PATH)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def agent_hub_root(tmp_path, monkeypatch) -> Path:
    script = tmp_path / "scripts" / "codex-session-sync.py"
    script.parent.mkdir(parents=True)
    script.write_text("", encoding="utf-8")
    monkeypatch.setenv("ST_AGENT_HUB_ROOT", str(tmp_path))
    return tmp_path


def test_codex_observability_sync_runs_agent_hubs_collector(agent_hub_root) -> None:
    module = _load_module()

    commands = module._commands(include_codex=True, verbose=False)

    assert len(commands) == 1
    assert commands[0][1] == str(agent_hub_root / "scripts" / "codex-session-sync.py")
    assert "--close-inactive" in commands[0]
    # The scan window comes from Agent Hub's session close settings unless overridden.
    assert "--recent-hours" not in commands[0]


def test_codex_observability_sync_can_disable_inactive_close(agent_hub_root, monkeypatch) -> None:
    module = _load_module()
    monkeypatch.setenv("AGENT_OBSERVABILITY_CODEX_CLOSE_INACTIVE", "0")

    commands = module._commands(include_codex=True, verbose=False)

    assert "--close-inactive" not in commands[0]


def test_codex_observability_sync_skips_without_agent_hub(monkeypatch) -> None:
    module = _load_module()
    monkeypatch.delenv("ST_AGENT_HUB_ROOT", raising=False)

    assert module._commands(include_codex=True, verbose=False) == []
