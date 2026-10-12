"""Heavy checks leave a busy workstation for the Proxmox CI runner and fall back locally."""

import subprocess
from pathlib import Path
from unittest.mock import Mock

import pytest

from app.utils.heavy_work import Admission, HeavyWork
from cli.commands import check
from cli.lib import cleanroom, remote_runner


@pytest.fixture
def key(tmp_path):
    path = tmp_path / "key"
    path.write_text("")
    return path


def test_configured_honours_off_and_requires_key(key, tmp_path):
    assert remote_runner.configured({"ST_CI_RUNNER": "off"}) is None
    assert remote_runner.configured({"ST_CI_RUNNER_KEY": str(tmp_path / "missing")}) is None
    runner = remote_runner.configured({"ST_CI_RUNNER": "ci@host", "ST_CI_RUNNER_KEY": str(key),
                                       "ST_CI_RUNNER_PROJECTS": "a, b"})
    assert runner == remote_runner.Runner("ci@host", key, ("a", "b"))


@pytest.mark.parametrize(("admit", "busy", "expected"), [
    (True, [], None),
    (False, [], "workstation admission closed (memory pressure)"),
    (True, [{"label": "check pytest"}], "heavy lane busy (check pytest)"),
])
def test_offload_reason_follows_admission_and_heavy_lane(monkeypatch, key, admit, busy, expected):
    env = {"ST_CI_RUNNER_KEY": str(key)}
    monkeypatch.setattr(remote_runner, "admission_state",
                        lambda: Admission(admit, "memory pressure"))
    monkeypatch.setattr(remote_runner, "lane_activity", lambda _lane: busy)
    monkeypatch.setattr(remote_runner, "reachable", lambda _runner: True)
    result = remote_runner.offload_reason(Path("/srv/workspaces/projects/summitflow"), env)
    assert (result[1] if result else None) == expected
    assert remote_runner.offload_reason(Path("/srv/workspaces/projects/other"), env) is None


def test_unreachable_runner_keeps_work_local(monkeypatch, key):
    monkeypatch.setattr(remote_runner, "admission_state", lambda: Admission(False, "x"))
    monkeypatch.setattr(remote_runner, "reachable", lambda _runner: False)
    assert remote_runner.offload_reason(Path("/p/summitflow"), {"ST_CI_RUNNER_KEY": str(key)}) is None


def _patch_tool(monkeypatch, tmp_path):
    monkeypatch.setattr(check, "_resolve_repo_root", lambda: tmp_path)
    monkeypatch.setattr(check, "_workdir", lambda *_: tmp_path)
    monkeypatch.setattr(check, "_resolve_command", lambda *_: ["pytest"])
    monkeypatch.setattr(check, "_measured_light", lambda *_: False)


def test_full_pytest_runs_on_runner_when_offloaded(tmp_path, monkeypatch, capsys):
    _patch_tool(monkeypatch, tmp_path)
    runner = remote_runner.Runner("ci@host", tmp_path, ("x",))
    monkeypatch.setattr(remote_runner, "offload_reason", lambda _root: (runner, "heavy lane busy"))
    remote = Mock(return_value=subprocess.CompletedProcess([], 0, "1 passed", ""))
    monkeypatch.setattr(remote_runner, "run", remote)
    local = Mock()
    monkeypatch.setattr(HeavyWork, "run", local)
    assert check._run_tool("pytest", {"label": "TEST"}, []) == 0
    local.assert_not_called()
    assert remote.call_args.kwargs["fetch"][0].suffix == ".xml"
    assert "|runner:proxmox|" in capsys.readouterr().out


def test_scoped_pytest_and_runner_failures_stay_local(tmp_path, monkeypatch):
    _patch_tool(monkeypatch, tmp_path)
    runner = remote_runner.Runner("ci@host", tmp_path, ("x",))
    monkeypatch.setattr(remote_runner, "offload_reason", lambda _root: (runner, "busy"))
    remote = Mock(side_effect=remote_runner.RunnerUnavailable("down"))
    monkeypatch.setattr(remote_runner, "run", remote)
    local = Mock(return_value=subprocess.CompletedProcess([], 0, "ok", ""))
    monkeypatch.setattr(HeavyWork, "run", local)
    assert check._run_tool("pytest", {"label": "TEST"}, []) == 0
    assert check._run_tool("pytest", {"label": "TEST"}, ["tests/test_one.py"]) == 0
    assert local.call_count == 2
    remote.assert_called_once()


def test_cleanroom_routes_plain_runs_to_runner(tmp_path, monkeypatch, capsys):
    runner = remote_runner.Runner("ci@host", tmp_path, ("x",))
    monkeypatch.setattr(remote_runner, "offload_reason", lambda _root: (runner, "busy"))
    remote = Mock(return_value=subprocess.CompletedProcess([], 3, "out", ""))
    monkeypatch.setattr(remote_runner, "run", remote)
    assert cleanroom.run_cleanroom(tmp_path, ["make", "test"]) == 3
    assert remote.call_args.args[2] == ["make", "test"]
    assert "out" in capsys.readouterr().out
