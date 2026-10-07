from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest


def _load_module():
    path = Path(__file__).resolve().parents[3] / "scripts" / "btrfs-space-guard.py"
    spec = importlib.util.spec_from_file_location("btrfs_space_guard", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _usage(module, unallocated=20):
    return {"size": 100 * module.GIB, "free": 30 * module.GIB, "missing": 0,
            "unallocated": unallocated * module.GIB, "metadata_size": 2 * module.GIB, "metadata_used": module.GIB}


def test_custom_check_resolves_automount_and_never_balances(monkeypatch, tmp_path, capsys):
    module = _load_module()
    monkeypatch.setattr(sys, "argv", ["guard", "--check-only", "--path", "/mnt/native/points", "--uuid", "plain-target"])
    monkeypatch.setattr(module.os, "geteuid", lambda: 0)
    monkeypatch.setattr(module.fcntl, "flock", lambda *_: None)
    monkeypatch.setattr("builtins.open", lambda *_: (tmp_path / "lock").open("a"))
    monkeypatch.setattr(module, "usage", lambda _: _usage(module))
    calls = []
    def command(args, timeout=60):
        calls.append(args)
        rows = [{"target": "/mnt/native", "fstype": "autofs"},
                {"target": "/mnt/native", "fstype": "btrfs", "uuid": "plain-target", "options": "rw,compress=zstd:1"}]
        return subprocess.CompletedProcess(args, 0, json.dumps({"filesystems": rows}), "")
    monkeypatch.setattr(module, "command", command)
    assert module.main() == 0
    report = json.loads(capsys.readouterr().out)
    assert report["path"] == "/mnt/native/points" and report["uuid"] == "plain-target"
    assert report["policy"] == {"trigger_bytes": 8 * module.GIB, "target_bytes": 12 * module.GIB}
    assert report["after"]["metadata_size"] == 2 * module.GIB and report["actions"] == []
    assert len(calls) == 1 and calls[0][0] == "findmnt" and "-T" in calls[0]


@pytest.mark.parametrize("fault", ["uuid", "overmount"])
def test_mount_identity_does_not_accept_btrfs_ancestor(monkeypatch, fault):
    module = _load_module()
    rows = [{"target": "/", "fstype": "btrfs", "uuid": "source", "options": "rw"},
            {"target": "/mnt/native", "fstype": "ext4" if fault == "overmount" else "btrfs", "uuid": "other", "options": "rw"}]
    monkeypatch.setattr(module, "command", lambda args: subprocess.CompletedProcess(args, 0, json.dumps({"filesystems": rows}), ""))
    with pytest.raises(RuntimeError, match="unexpected filesystem"):
        module.inspect_mount("/mnt/native/points", "source", check_only=True)


def test_active_balance_deferral_keeps_pressure_warning(monkeypatch):
    module = _load_module()
    monkeypatch.setattr(module, "inspect_mount", lambda *_: None)
    monkeypatch.setattr(module, "usage", lambda _: _usage(module, 1))
    calls = []
    def command(args, timeout=60):
        calls.append(args)
        return subprocess.CompletedProcess(args, 0, "Total devices 1" if "show" in args else "Balance on '/' is running", "")
    monkeypatch.setattr(module, "command", command)
    report = module.maintain("/", module.FILESYSTEMS[0][1])
    assert report["deferred"] and report["warning"] and report["after"]["unallocated"] == module.GIB
    assert not any("start" in args for args in calls)


def test_default_reclamation_remains_bounded_and_stops_at_target(monkeypatch):
    module = _load_module()
    monkeypatch.setattr(module, "inspect_mount", lambda *_: None)
    measurements = iter([_usage(module, 5), _usage(module, 5), _usage(module, 13), _usage(module, 13)])
    monkeypatch.setattr(module, "usage", lambda _: next(measurements))
    calls = []
    def command(args, timeout=60):
        calls.append(args)
        output = "Total devices 1" if "show" in args else "No balance found" if "status" in args else ""
        return subprocess.CompletedProcess(args, 0, output, "")
    monkeypatch.setattr(module, "command", command)
    report = module.maintain("/", module.FILESYSTEMS[0][1])
    assert report["after"]["unallocated"] == 13 * module.GIB
    assert [args for args in calls if "start" in args] == [["btrfs", "balance", "start", "-dusage=0,limit=16", "/"]]


def test_custom_path_cannot_enter_maintenance(monkeypatch):
    module = _load_module()
    monkeypatch.setattr(sys, "argv", ["guard", "--path", "/mnt/native", "--uuid", "plain-target"])
    monkeypatch.setattr(module, "command", lambda *_: pytest.fail("custom maintenance must not execute commands"))
    with pytest.raises(SystemExit) as error:
        module.main()
    assert error.value.code == 2
