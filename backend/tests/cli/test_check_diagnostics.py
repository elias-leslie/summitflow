"""Silent test processes retain same-invocation diagnostic evidence."""

import subprocess
from pathlib import Path
from unittest.mock import Mock

import pytest

from app.utils.heavy_work import HeavyWork
from cli.commands import check


@pytest.mark.parametrize("returncode", [0, 1])
def test_silent_pytest_retains_report_without_running_again(tmp_path, monkeypatch, capsys, returncode):
    reports: list[Path] = []

    def run(command, **kwargs):
        report = Path(next(arg.split("=", 1)[1] for arg in command if arg.startswith("--junitxml=")))
        reports.append(report)
        report.write_text('<testsuite><testcase name="failure"><failure>real diagnostic</failure></testcase></testsuite>')
        return subprocess.CompletedProcess(command, returncode, "", "")

    runner = Mock(side_effect=run)
    monkeypatch.setattr(check, "_resolve_repo_root", lambda: tmp_path)
    monkeypatch.setattr(check, "_workdir", lambda *_: tmp_path)
    monkeypatch.setattr(check, "_resolve_command", lambda *_: ["pytest"])
    monkeypatch.setattr(HeavyWork, "run", runner)
    assert check._run_tool("pytest", {"label": "TEST"}, []) == returncode
    output = capsys.readouterr().out
    assert "report:" in output
    assert "no console output" in output
    assert "real diagnostic" not in output
    assert len(reports) == 1 and reports[0].is_file()
    assert reports[0].parent == tmp_path / ".dev-tools"
    runner.assert_called_once()


@pytest.mark.parametrize("argument", ["--junitxml=explicit.xml", "--junit-xml=explicit.xml"])
def test_explicit_pytest_report_is_not_overridden(tmp_path, monkeypatch, argument):
    runner = Mock(return_value=subprocess.CompletedProcess([], 1, "existing failure", ""))
    monkeypatch.setattr(check, "_resolve_repo_root", lambda: tmp_path)
    monkeypatch.setattr(check, "_workdir", lambda *_: tmp_path)
    monkeypatch.setattr(check, "_resolve_command", lambda *_: ["pytest"])
    monkeypatch.setattr(HeavyWork, "run", runner)
    assert check._run_tool("pytest", {"label": "TEST"}, [argument]) == 1
    arguments = runner.call_args.args[0]
    assert sum(arg.startswith(("--junitxml", "--junit-xml")) for arg in arguments) == 1
    assert argument in arguments
