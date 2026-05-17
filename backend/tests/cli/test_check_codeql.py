"""Tests for the CodeQL alert state check wrapper."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

from cli.commands import check as check_command


def _completed(command: list[str], stdout: str, returncode: int = 0, stderr: str = ""):
    return subprocess.CompletedProcess(command, returncode, stdout, stderr)


def _patch_codeql_subprocess(
    monkeypatch,
    *,
    tmp_path: Path,
    api_payload: list[dict[str, Any]],
) -> None:
    def fake_run(command, **kwargs):
        if command[:3] == ["git", "branch", "--show-current"]:
            return _completed(command, "main\n")
        if command[:3] == ["gh", "repo", "view"]:
            return _completed(command, "elias-leslie/a-term\n")
        if command[:2] == ["gh", "api"]:
            assert "ref=refs%2Fheads%2Fmain" in command[2]
            return _completed(command, json.dumps(api_payload))
        raise AssertionError(f"unexpected command: {command}")

    monkeypatch.setattr(check_command, "_resolve_repo_root", lambda: tmp_path)
    monkeypatch.setattr(check_command.shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(check_command.subprocess, "run", fake_run)


def test_codeql_alert_check_passes_with_no_open_codeql_alerts(
    monkeypatch, tmp_path, capsys
) -> None:
    _patch_codeql_subprocess(monkeypatch, tmp_path=tmp_path, api_payload=[])

    assert check_command._run_codeql_alert_check([]) == 0

    output = capsys.readouterr().out
    assert "CODEQL:OK:0" in output
    assert "0 open CodeQL alerts" in output


def test_codeql_alert_check_fails_with_open_codeql_alert(
    monkeypatch, tmp_path, capsys
) -> None:
    alert = {
        "number": 22,
        "tool": {"name": "CodeQL"},
        "rule": {"id": "py/path-injection"},
        "most_recent_instance": {
            "location": {"path": "a_term/branding.py", "start_line": 113}
        },
    }
    _patch_codeql_subprocess(monkeypatch, tmp_path=tmp_path, api_payload=[alert])

    assert check_command._run_codeql_alert_check([]) == 1

    output = capsys.readouterr().out
    assert "CODEQL:FAIL:1" in output
    assert "#22 py/path-injection a_term/branding.py:113" in output
    details = tmp_path / ".dev-tools" / "codeql-details.txt"
    assert json.loads(details.read_text())["alerts"] == [alert]
