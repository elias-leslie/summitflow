"""Local security adapters scan candidate inputs and state coverage limits."""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import Mock

import pytest

from cli.commands import check_dispatch, check_security


def test_gitleaks_materializes_only_changed_candidate_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "backend" / "app.py"
    ignored = tmp_path / "node_modules" / "secret.js"
    source.parent.mkdir(parents=True)
    ignored.parent.mkdir()
    source.write_text("safe = True\n")
    ignored.write_text("should not be scanned\n")

    def run(command, **_kwargs):
        candidate = Path(command[-1])
        assert (candidate / "backend" / "app.py").read_text() == "safe = True\n"
        assert not (candidate / "node_modules").exists()
        return subprocess.CompletedProcess(command, 0, "[]", "")

    monkeypatch.setattr(check_security.subprocess, "run", run)
    assert check_security.run_local_security_check(
        "gitleaks", tmp_path, ["backend/app.py", "node_modules/secret.js"], True, []
    ) == 0


def test_gitleaks_is_required_and_redacts_findings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    candidate = tmp_path / "secret.txt"
    candidate.write_text("placeholder\n")

    def missing(command, **_kwargs):
        assert "--redact" in command
        raise FileNotFoundError("gitleaks")

    monkeypatch.setattr(check_security.subprocess, "run", missing)
    assert check_security.run_local_security_check(
        "gitleaks", tmp_path, ["secret.txt"], True, []
    ) == 127
    assert "GITLEAKS:FAIL:127" in capsys.readouterr().out


def test_semgrep_without_local_rules_is_explicit_skip(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    source = tmp_path / "app.py"
    source.write_text("pass\n")
    run = Mock()
    monkeypatch.delenv("SEMGREP_RULES", raising=False)
    monkeypatch.setattr(check_security.subprocess, "run", run)

    assert check_security.run_local_security_check(
        "semgrep", tmp_path, ["app.py"], True, []
    ) == 0

    run.assert_not_called()
    output = capsys.readouterr().out
    assert "no_local_rules" in output
    assert "codeql_equivalence_not_claimed" in output


def test_semgrep_uses_only_local_rules_without_metrics_or_version_network(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "app.py").write_text("pass\n")
    (tmp_path / ".semgrep.yml").write_text("rules: []\n")
    run = Mock(return_value=subprocess.CompletedProcess([], 0, "{}", ""))
    monkeypatch.setattr(check_security.subprocess, "run", run)

    assert check_security.run_local_security_check(
        "semgrep", tmp_path, ["app.py"], True, []
    ) == 0

    command = run.call_args.args[0]
    assert command[:4] == ["semgrep", "scan", "--config", str(tmp_path / ".semgrep.yml")]
    assert command[4:6] == ["--metrics", "off"]
    assert "--disable-version-check" in command


def test_osv_scans_only_candidate_lockfiles(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    lockfile = tmp_path / "backend" / "uv.lock"
    lockfile.parent.mkdir()
    lockfile.write_text("version = 1\n")
    (tmp_path / "pnpm-lock.yaml").write_text("lockfileVersion: '9'\n")
    run = Mock(return_value=subprocess.CompletedProcess([], 0, "{}", ""))
    monkeypatch.setattr(check_security.subprocess, "run", run)

    assert check_security.run_local_security_check(
        "osv", tmp_path, ["backend/uv.lock"], True, []
    ) == 0

    command = run.call_args.args[0]
    assert command.count("--lockfile") == 1
    assert str(lockfile) in command
    assert str(tmp_path / "pnpm-lock.yaml") not in command


def test_security_aggregate_states_codeql_limitation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(check_security, "_candidate_paths", lambda *_args: [])
    assert check_security.run_local_security_check(
        "security", tmp_path, [], False, []
    ) == 0
    assert "codeql_equivalence=not_claimed" in capsys.readouterr().out


def test_dispatch_exposes_security_without_tool_registry_config(tmp_path: Path) -> None:
    runtime = Mock(spec=list(check_dispatch.CheckRuntime.__dataclass_fields__))
    runtime.resolve_repo_root.return_value = tmp_path
    runtime.changed_files.return_value = ["app.py"]
    runtime.run_local_security_check.return_value = 0

    assert check_dispatch.run_named_tool(
        "gitleaks", ["gitleaks"], {}, changed_only=True, fix=False, runtime=runtime
    ) == 0

    runtime.run_local_security_check.assert_called_once_with(
        "gitleaks", tmp_path, ["app.py"], True, []
    )
