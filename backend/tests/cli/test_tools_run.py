"""The public external-tool adapter reuses shared admission and owned cleanup."""

from __future__ import annotations

import fcntl
import os
import sys
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from typer.testing import CliRunner

from app.utils import heavy_work as guard
from cli.commands import tools, tools_run

runner = CliRunner()


def test_runner_preserves_argv_output_and_exit(monkeypatch):
    execute = Mock(return_value=SimpleNamespace(returncode=23))
    admission = Mock()

    @contextmanager
    def admitted(*args, **kwargs):
        admission(*args, **kwargs)
        yield SimpleNamespace(run=execute)

    monkeypatch.setattr(tools_run, "heavy_work", admitted)
    command = ["tool", "--label", "child label", "--help", "$(literal)", "space here"]
    result = runner.invoke(tools.app, ["run", "--label", "model download", "--", *command])
    assert result.exit_code == 23, result.output
    assert result.output == ""
    admission.assert_called_once_with("model download", work_class="heavy")
    execute.assert_called_once_with(command, check=False)


@pytest.fixture
def lane(tmp_path, monkeypatch):
    directory = tmp_path / "lane"
    monkeypatch.setattr(guard, "_LOCK_DIRECTORY", directory)
    monkeypatch.delenv("ST_HEAVY_LEASE", raising=False)
    monkeypatch.setattr(guard, "_spare_capacity", lambda: False)
    monkeypatch.setattr(guard, "admission_state", lambda: guard.Admission(True, "fixture"))
    monkeypatch.setattr(guard.HeavyWork, "command", lambda self, command: list(command))
    return directory


def assert_released(lane):
    descriptor = os.open(lane / "activity.lock", os.O_RDWR)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
    finally:
        os.close(descriptor)
    assert not list(lane.glob("wait-*.json"))


def test_child_inherits_verified_lease_environment_and_streams(lane, monkeypatch, capfd):
    monkeypatch.setenv("TOOL_RUN_FIXTURE", "preserved")
    code = f"""
import os, sys
from pathlib import Path
sys.path.insert(0, {str(Path(__file__).resolve().parents[2])!r})
from app.utils import heavy_work as guard
guard._LOCK_DIRECTORY = Path({str(lane)!r})
guard.admission_state = lambda: guard.Admission(True, 'fixture')
token = os.environ['ST_HEAVY_LEASE'].split(':')
os.fstat(int(token[3]))
os.fstat(int(token[5]))
assert os.environ['TOOL_RUN_FIXTURE'] == 'preserved'
with guard.heavy_work('nested fixture') as work:
    assert work.token.split(':')[:3] == token[:3]
    assert work.token.split(':')[4] == '1'
print('child stdout', flush=True)
print('child stderr', file=sys.stderr, flush=True)
sys.exit(19)
"""
    result = runner.invoke(tools.app, ["run", "--label", "fixture", "--", sys.executable, "-c", code])
    assert result.exit_code == 19, result.output
    captured = capfd.readouterr()
    assert captured.out == "child stdout\n"
    assert captured.err == "child stderr\n"
    assert_released(lane)


@pytest.mark.parametrize("failure, status", [(FileNotFoundError("private argv"), 127), (PermissionError("private argv"), 126)])
def test_spawn_failure_does_not_expose_arguments_and_releases(lane, monkeypatch, failure, status):
    monkeypatch.setattr(guard.HeavyWork, "run", Mock(side_effect=failure))
    result = runner.invoke(tools.app, ["run", "--label", "fixture", "--", "private argv"])
    assert result.exit_code == status
    assert "private argv" not in result.output
    assert "Tool could not be started" in result.output
    assert_released(lane)


def test_interrupt_releases_admission(lane, monkeypatch):
    monkeypatch.setattr(guard.HeavyWork, "run", Mock(side_effect=KeyboardInterrupt))
    result = runner.invoke(tools.app, ["run", "--label", "fixture", "--", "tool"])
    assert result.exit_code != 0
    assert_released(lane)


def test_required_arguments_do_not_start_work(monkeypatch):
    admission = Mock(side_effect=AssertionError("must not admit"))
    monkeypatch.setattr(tools_run, "heavy_work", admission)
    for args in (["run", "--label", "fixture"], ["run", "--", "tool"]):
        result = runner.invoke(tools.app, args)
        assert result.exit_code == 2
    admission.assert_not_called()
