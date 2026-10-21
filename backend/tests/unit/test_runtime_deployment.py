"""Remote placement is catalog data; observing or controlling it stays off the workstation."""

import json
import shlex
from subprocess import CompletedProcess
from unittest.mock import Mock

import pytest

from app import runtime_deployment as rd

TARGET = {"kind": "proxmox", "ssh_host": "example-pve", "vmid": 456, "user": "example", "uid": 1234}


def test_remote_observation_uses_exact_catalog_guest_and_user(monkeypatch):
    monkeypatch.setattr(rd, "_guest_status", lambda _: "running")
    run = Mock(return_value=CompletedProcess([], 0, json.dumps({"exited": 1, "exitcode": 0,
        "out-data": "Id=api.service\nActiveState=active\nLoadState=loaded\n\nId=jobs.timer\nActiveState=inactive\n"}), ""))
    monkeypatch.setattr(rd.safe_subprocess, "run", run)
    target = rd.parse_deployment(TARGET)
    assert target is not None
    states = rd.unit_states(target, ["api.service", "jobs.timer"])
    assert states["api.service"]["ActiveState"] == "active"
    assert states["jobs.timer"]["ActiveState"] == "inactive"
    args = run.call_args.args[0]
    assert args[-2] == "example-pve"
    guest = shlex.split(args[-1])
    assert guest[:4] == ["qm", "guest", "exec", "456"]
    assert guest[guest.index("runuser") + 1:guest.index("runuser") + 4] == ["-u", "example", "--"]
    assert "XDG_RUNTIME_DIR=/run/user/1234" in guest
    assert guest[-3:] == ["--", "api.service", "jobs.timer"]


@pytest.mark.parametrize("payload", [{}, [], {"exited": 0}, {"exited": 1, "exitcode": 1}])
def test_incomplete_or_failed_guest_observation_is_not_a_local_fallback(monkeypatch, payload):
    monkeypatch.setattr(rd, "_guest_status", lambda _: "running")
    run = Mock(return_value=CompletedProcess([], 0, json.dumps(payload), ""))
    monkeypatch.setattr(rd.safe_subprocess, "run", run)
    with pytest.raises(rd.DeploymentError):
        target = rd.parse_deployment(TARGET)
        assert target is not None
        rd.unit_states(target, ["api.service"])
    assert run.call_count == 1


@pytest.mark.parametrize("change", [{"kind": "other"}, {"vmid": True}, {"uid": 0},
                                    {"guest_type": []}, {"manager": {}},
                                    {"ssh_host": "-oProxyCommand=bad"}, {"user": "bad;command"}])
def test_invalid_explicit_placement_never_becomes_local(change):
    with pytest.raises(rd.DeploymentError):
        rd.parse_deployment({**TARGET, **change})
    assert rd.parse_deployment(None) is None


def test_stopped_guest_reports_stopped_without_executing_guest_command(monkeypatch):
    monkeypatch.setattr(rd, "_guest_status", lambda _: "stopped")
    command = Mock(side_effect=AssertionError("stopped guest must not execute"))
    monkeypatch.setattr(rd, "_guest_command", command)
    target = rd.parse_deployment(TARGET)
    assert target is not None
    row = rd.unit_states(target, ["api.service"])["api.service"]
    assert row["ActiveState"] == "inactive"
    assert row["SubState"] == "guest-stopped"
    assert "LoadState" not in row


def test_lxc_system_units_use_pct_and_system_manager(monkeypatch):
    run = Mock(return_value=CompletedProcess([], 0, "Id=hub.service\nActiveState=active\n", ""))
    monkeypatch.setattr(rd.safe_subprocess, "run", run)
    monkeypatch.setattr(rd, "_guest_status", lambda _: "running")
    target = rd.parse_deployment({"kind": "proxmox", "ssh_host": "example-pve", "vmid": 450,
                                  "guest_type": "lxc", "manager": "system"})
    assert target is not None
    assert rd.unit_states(target, ["hub.service"])["hub.service"]["ActiveState"] == "active"
    command = shlex.split(run.call_args.args[0][-1])
    assert command[:4] == ["pct", "exec", "450", "--"]
    assert "--user" not in command
    assert "runuser" not in command


def test_remote_stop_runs_only_the_declared_guest_units(monkeypatch):
    run = Mock(return_value=CompletedProcess([], 0, json.dumps({"exited": 1, "exitcode": 0}), ""))
    monkeypatch.setattr(rd.safe_subprocess, "run", run)
    target = rd.parse_deployment(TARGET)
    assert target is not None
    rd.control_units(target, "stop", ["api.service", "jobs.timer", "jobs.service"])
    command = shlex.split(run.call_args.args[0][-1])
    assert command[-5:] == ["stop", "--", "api.service", "jobs.timer", "jobs.service"]
    assert "--no-ask-password" in command


def test_remote_recent_logs_use_the_guest_journal(monkeypatch):
    run = Mock(return_value=CompletedProcess([], 0, json.dumps({"exited": 1, "exitcode": 0, "out-data": "test log"}), ""))
    monkeypatch.setattr(rd.safe_subprocess, "run", run)
    target = rd.parse_deployment(TARGET)
    assert target is not None
    assert rd.recent_logs(target, "api.service", 7) == "test log"
    command = shlex.split(run.call_args.args[0][-1])
    assert command[command.index("journalctl"):] == ["journalctl", "--user", "-u", "api.service", "-n", "7", "--output=short-iso", "--no-pager"]
