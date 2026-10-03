"""Tests for the CodeQL alert state check wrapper."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any
from unittest.mock import Mock

from cli.commands import check as check_command
from cli.commands import check_codeql


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
            endpoint = command[2]
            if endpoint == "repos/elias-leslie/a-term":
                return _completed(command, json.dumps({"default_branch": "main", "private": False}))
            if "/git/ref/heads/main" in endpoint:
                return _completed(command, json.dumps({"object": {"sha": "c" * 40}}))
            if endpoint.endswith("/code-scanning/default-setup"):
                return _completed(command, json.dumps({"state": "configured", "languages": ["python"],
                    "query_suite": "default", "updated_at": "2026-10-01T12:00:00Z"}))
            assert "ref=refs%2Fheads%2Fmain" in endpoint
            if "/analyses?" in endpoint:
                return _completed(command, json.dumps([{"id": 1, "ref": "refs/heads/main", "commit_sha": "c" * 40,
                    "category": "/language:python", "analysis_key": "dynamic/github-code-scanning/codeql:analyze", "environment": "{}",
                    "created_at": "2026-10-02T12:00:00Z",
                    "rules_count": 10, "error": "", "tool": {"name": "CodeQL"}}]))
            return _completed(command, json.dumps(api_payload))
        raise AssertionError(f"unexpected command: {command}")

    monkeypatch.setattr(check_command, "_resolve_repo_root", lambda: tmp_path)
    monkeypatch.setattr(check_command.shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(check_command.subprocess, "run", fake_run)
    monkeypatch.setattr(check_codeql, "record_codeql_observation", lambda *args, **kwargs: None)


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


def test_failed_initial_alert_read_never_resolves_from_later_green(monkeypatch, tmp_path):
    record = Mock()
    monkeypatch.setattr(check_codeql, "observe_codeql", lambda *_args, **_kw: {"state": "success"})
    monkeypatch.setattr(check_codeql, "record_codeql_observation", record)
    assert check_codeql._emit_codeql_result(tmp_path, "fixture/project", None, [], "API failed", 1) == 1
    assert record.call_args.args[1]["state"] == "pending"


def test_missing_cli_retains_unknown_coverage_not_project_defect(monkeypatch, tmp_path):
    record = Mock()
    monkeypatch.setattr(check_codeql.shutil, "which", lambda *_: None)
    monkeypatch.setattr(check_codeql, "record_codeql_observation", record)
    assert check_codeql._fetch_codeql_repo(tmp_path) is None
    assert record.call_args.args[1]["reason"] == "codeql_cli_unavailable"
    assert record.call_args.args[1]["state"] == "pending"


def test_api_timeout_is_captured_for_ingestion(monkeypatch, tmp_path):
    monkeypatch.setattr(check_codeql.subprocess, "run", Mock(side_effect=subprocess.TimeoutExpired("gh", 60)))
    alerts, error, code = check_codeql._fetch_codeql_alerts(tmp_path, "fixture/project", None)
    assert alerts == [] and code == 1 and "TimeoutExpired" in error
