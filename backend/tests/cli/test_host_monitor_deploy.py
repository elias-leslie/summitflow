"""Privileged deployment boundaries tested without touching host services."""
from __future__ import annotations

import json
import os
import sqlite3
import subprocess
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest

from cli.commands import service
from cli.lib import host_monitor_deploy as deploy
from cli.lib import service_ops


def test_helper_runs_isolated_without_backend_environment():
    import tempfile

    source = Path(__file__).resolve().parents[2]
    with tempfile.TemporaryDirectory() as temporary:
        staging = Path(temporary)
        (staging / "backend").symlink_to(source)
        helper = deploy.build_helper(staging)
        result = subprocess.run([str(helper)], input='{"schema":99}\n', text=True,
                                capture_output=True, check=False, timeout=3)
    assert result.returncode == 2
    assert not result.stdout
    assert "ImportError" not in result.stderr
    assert "ModuleNotFoundError" not in result.stderr


def test_history_copy_retains_wal_records(tmp_path):
    source, target = tmp_path / "source.sqlite", tmp_path / "target.sqlite"
    with sqlite3.connect(source) as db:
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("CREATE TABLE samples (id INTEGER PRIMARY KEY, value TEXT)")
        db.execute("INSERT INTO samples VALUES (1, 'retained')")
        db.commit()
        deploy._backup(source, target)
    with sqlite3.connect(target) as copied:
        assert copied.execute("SELECT * FROM samples").fetchall() == [(1, "retained")]
    with pytest.raises(RuntimeError, match="backup paths"):
        deploy._backup(source, target)


def test_monitor_lifecycle_uses_system_manager(monkeypatch):
    calls = []
    monkeypatch.setattr(service_ops, "capture", lambda command, **kwargs:
                        calls.append(command) or SimpleNamespace(returncode=0, stdout="active", stderr=""))
    assert service_ops.service_state(deploy.UNIT) == "active"
    assert service_ops.service_exists(deploy.UNIT)
    assert calls == [["systemctl", "is-active", deploy.UNIT], ["systemctl", "cat", deploy.UNIT]]
    assert service_ops._service_command(deploy.UNIT, "start") == ["sudo", "-n", "/usr/bin/systemctl", "start", deploy.UNIT]
    assert service_ops._service_command("application.service", "start") == ["systemctl", "--user", "start", "application.service"]


def test_first_rollback_preserves_candidate_history_and_resumes_legacy(tmp_path, monkeypatch):
    state, receipts, unit = tmp_path / "state", tmp_path / "receipts", tmp_path / "unit"
    state.mkdir()
    receipts.mkdir()
    (state / "monitor.sqlite3").write_text("candidate history")
    unit.write_text("candidate unit")
    monkeypatch.setattr(deploy, "STATE", state)
    monkeypatch.setattr(deploy, "RECEIPTS", receipts)
    monkeypatch.setattr(deploy, "UNIT_PATH", unit)
    calls = []
    monkeypatch.setattr(deploy, "_system", lambda *args, **kwargs:
                        calls.append(("system", args)) or SimpleNamespace(returncode=1 if args[0] == "is-active" else 0))
    monkeypatch.setattr(deploy, "_user", lambda uid, gid, *args, **kwargs:
                        calls.append(("user", args)) or SimpleNamespace(returncode=0))
    record = {"status": "activated", "previous_unit": None, "state_created": True,
              "legacy_enabled": True, "legacy_active": True, "uid": 1000, "gid": 1000}
    (receipts / "test.json").write_text(json.dumps(record))
    (receipts / "test.pending").touch()
    deploy.rollback("test")
    assert (receipts / "test.state/monitor.sqlite3").read_text() == "candidate history"
    assert not state.exists() and not unit.exists()
    assert ("user", ("start", deploy.UNIT)) in calls
    assert json.loads((receipts / "test.json").read_text())["status"] == "rolled_back"
    assert not (receipts / "test.pending").exists()


def test_unsafe_state_directory_and_symlink_backup_are_rejected(tmp_path):
    real = tmp_path / "real"
    real.mkdir()
    link = tmp_path / "link"
    link.symlink_to(real, target_is_directory=True)
    with pytest.raises(RuntimeError, match="symlink"):
        deploy._directory(link)
    source = tmp_path / "db"
    source.symlink_to(real / "db")
    with pytest.raises(RuntimeError):
        deploy._backup(source, tmp_path / "copy")


def test_unit_uses_protected_install_and_explicit_owner():
    unit = Path(__file__).resolve().parents[3] / "scripts/systemd" / deploy.UNIT
    text = unit.read_text()
    assert "User=root" in text
    assert "--owner-uid __MONITOR_OWNER_UID__" in text
    assert "--owner-gid __MONITOR_OWNER_GID__" in text
    assert "WantedBy=multi-user.target" in text
    assert "target/release" not in text
    assert os.path.isabs(str(deploy.STATE))


@pytest.mark.parametrize("activation_fails", [False, True])
def test_first_install_and_failed_activation_preserve_owner_store(tmp_path, monkeypatch, activation_fails):
    source, home = tmp_path / "source", tmp_path / "owner"
    artifacts = source / "host-monitor/target/release"
    artifacts.mkdir(parents=True)
    for name in ("summitflow-host-monitor", "monitor-observe.pyz", "policy.json"):
        (artifacts / name).write_text("accepted artifact")
    (source / "project.identity.json").write_text("{}")
    units = source / "scripts/systemd"
    units.mkdir(parents=True)
    (units / deploy.UNIT).write_text("ExecStart=__MONITOR_RELEASE__/summitflow-host-monitor --owner-uid __MONITOR_OWNER_UID__ --owner-gid __MONITOR_OWNER_GID__\n")
    legacy = home / ".local/state/summitflow/monitor"
    legacy.mkdir(parents=True)
    (legacy / "maintenance.lock").touch()
    with sqlite3.connect(legacy / "monitor.sqlite3") as db:
        db.execute("CREATE TABLE samples (id INTEGER)")
        db.execute("INSERT INTO samples VALUES (123)")
    install, state, receipts = tmp_path / "installed", tmp_path / "state", tmp_path / "receipts"
    unit = tmp_path / "system.service"
    for name, path in (("INSTALL", install), ("STATE", state), ("RECEIPTS", receipts), ("UNIT_PATH", unit)):
        monkeypatch.setattr(deploy, name, path)
    monkeypatch.setattr(deploy.pwd, "getpwuid", lambda uid: SimpleNamespace(pw_gid=1000, pw_dir=str(home)))
    monkeypatch.setattr(deploy, "_directory", lambda path, mode=0o755: path.mkdir(parents=True, exist_ok=True))
    monkeypatch.setattr(deploy, "_state_permissions", lambda gid: None)
    active = {"user": True, "system": False}

    def system(*args, **kwargs):
        if args[:2] == ("enable", "--now"):
            if activation_fails:
                raise subprocess.CalledProcessError(1, args)
            active["system"] = True
        if args[0] == "stop":
            active["system"] = False
        code = int(not active["system"]) if args[0] in {"is-active", "is-enabled"} else 0
        return SimpleNamespace(returncode=code)

    def user(uid, gid, *args, **kwargs):
        if args[0] == "disable":
            active["user"] = False
        if args[0] == "start":
            active["user"] = True
        code = int(not active["user"]) if args[0] in {"is-active", "is-enabled"} else 0
        return SimpleNamespace(returncode=code)

    monkeypatch.setattr(deploy, "_system", system)
    monkeypatch.setattr(deploy, "_user", user)
    if activation_fails:
        with pytest.raises(subprocess.CalledProcessError):
            deploy.install(source, 1000, 1000, "candidate")
        assert active == {"user": True, "system": False}
        assert not unit.exists() and not state.exists()
        assert (receipts / "candidate.state/monitor.sqlite3").exists()
    else:
        deploy.install(source, 1000, 1000, "candidate")
        assert active == {"user": False, "system": True}
        with sqlite3.connect(state / "monitor.sqlite3") as db:
            assert db.execute("SELECT id FROM samples").fetchone() == (123,)
        assert "__MONITOR" not in unit.read_text()
    with sqlite3.connect(legacy / "monitor.sqlite3") as db:
        assert db.execute("SELECT id FROM samples").fetchone() == (123,)


@pytest.mark.parametrize("reader_restarts", [True, False])
def test_rollback_restores_reader_before_retiring_system_collector(monkeypatch, reader_restarts):
    calls = []
    project = SimpleNamespace(backend_service="backend.service", backend_port=8001)
    release = SimpleNamespace(build_id="candidate")
    monkeypatch.setattr(service, "_restore_previous_units", lambda *args: calls.append("restore units") or True)
    monkeypatch.setattr(service_ops, "restart_service", lambda *args, **kwargs:
                        calls.append("restart backend") or (0 if reader_restarts else 1))
    monkeypatch.setattr(service_ops, "sync_systemd_units", lambda *args: calls.append("restore candidate units") or 0)
    monkeypatch.setattr(service_ops, "host_monitor_deployment", lambda *args:
                        calls.append("rollback collector") or 0)
    monkeypatch.setattr(service.service_release, "mark_phase", lambda *args, **kwargs: None)
    assert service._rollback_monitor_and_reader(
        cast(service_ops.ProjectServices, project), cast(service_ops.ProjectServices, project),
        cast(service.service_release.PreparedRelease, release), True,
    ) is reader_restarts
    if reader_restarts:
        assert calls == ["restore units", "restart backend", "rollback collector"]
    else:
        assert calls == ["restore units", "restart backend", "restore candidate units", "restart backend"]
