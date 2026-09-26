"""Installed monitor entry point dispatches on-demand app providers."""

from __future__ import annotations

import json

import pytest

import monitor_standalone
from monitor_observe import inventory


def test_standalone_apps_provider_and_cursor(monkeypatch: pytest.MonkeyPatch,
                                             capsys: pytest.CaptureFixture[str]) -> None:
    seen: list[list[str]] = []

    def run(argv: list[str]):
        seen.append(argv)
        return b"Name Version\nfirst 1.0\nsecond 2.0\n", b"", 0, False

    monkeypatch.setattr(inventory, "_run", run)
    assert monitor_standalone.main(["apps", "--provider", "snap", "--name", "s", "--limit", "1"]) == 0
    first = json.loads(capsys.readouterr().out)
    assert first["items"][0]["value"]["name"] == "first"
    assert first["next_cursor"].startswith("a1.")
    assert monitor_standalone.main(["apps", "--provider", "snap", "--name", "s",
                                    "--cursor", first["next_cursor"]]) == 0
    second = json.loads(capsys.readouterr().out)
    assert second["items"][0]["value"]["name"] == "second"
    assert seen == [["snap", "list", "--color=never", "--unicode=never"]] * 2


def test_standalone_apps_invalid_cursor_is_structured(capsys: pytest.CaptureFixture[str]) -> None:
    assert monitor_standalone.main(["apps", "--cursor", "bad"]) == 1
    result = json.loads(capsys.readouterr().out)
    assert result["errors"][0]["message"] == "invalid apps cursor for provider and name"
