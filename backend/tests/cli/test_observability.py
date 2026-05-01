"""Tests for best-effort CLI observability sync."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

from cli import _observability


def test_refresh_agent_observability_uses_small_default_timeout(monkeypatch) -> None:
    script_path = Path("/tmp/agent-observability-sync.py")
    calls: list[dict[str, object]] = []

    def fake_run(args, **kwargs):
        calls.append({"args": args, **kwargs})
        return subprocess.CompletedProcess(args, 0)

    monkeypatch.delenv("ST_OBSERVABILITY_SYNC_TIMEOUT", raising=False)
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.setattr(_observability, "_SYNC_DONE", False)
    monkeypatch.setattr(_observability, "_sync_script", lambda: script_path)
    monkeypatch.setattr(Path, "is_file", lambda _self: True)

    with patch.object(_observability.subprocess, "run", side_effect=fake_run):
        _observability.refresh_agent_observability()

    assert calls[0]["args"] == [
        sys.executable,
        str(script_path),
        "--best-effort",
        "--timeout",
        "1.0",
    ]
    assert calls[0]["check"] is False
    assert calls[0]["stdout"] == subprocess.DEVNULL
    assert calls[0]["stderr"] == subprocess.DEVNULL
    assert calls[0]["timeout"] == 1.0
    assert isinstance(calls[0]["env"], dict)


def test_refresh_agent_observability_honors_timeout_override(monkeypatch) -> None:
    script_path = Path("/tmp/agent-observability-sync.py")

    monkeypatch.setenv("ST_OBSERVABILITY_SYNC_TIMEOUT", "2.5")
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.setattr(_observability, "_SYNC_DONE", False)
    monkeypatch.setattr(_observability, "_sync_script", lambda: script_path)
    monkeypatch.setattr(Path, "is_file", lambda _self: True)

    with patch.object(_observability.subprocess, "run") as mock_run:
        _observability.refresh_agent_observability()

    assert mock_run.call_args.args[0][-2:] == ["--timeout", "2.5"]
    assert mock_run.call_args.kwargs["timeout"] == 2.5
