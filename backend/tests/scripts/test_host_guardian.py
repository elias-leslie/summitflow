from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest


def _load_module():
    path = Path(__file__).resolve().parents[3] / "scripts" / "host-guardian.py"
    spec = importlib.util.spec_from_file_location("host_guardian", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_disk_thresholds_distinguish_warning_and_critical() -> None:
    module = _load_module()
    state = module.CheckState()

    module.evaluate_disk(state, {"percent_used": 82.0, "free_gib": 40.0}, label="root")
    assert state.status == "healthy"

    module.evaluate_disk(state, {"percent_used": 86.0, "free_gib": 20.0}, label="root")
    assert state.status == "warning"
    assert state.issues[0]["code"] == "root_disk_warning"

    module.evaluate_disk(state, {"percent_used": 93.0, "free_gib": 8.0}, label="backup")
    assert state.status == "critical"
    assert state.issues[-1]["code"] == "backup_disk_critical"


def test_event_fingerprint_ignores_non_health_details() -> None:
    module = _load_module()
    payload = {
        "status": "healthy",
        "issues": [],
        "checked_at": "2026-07-11T12:00:00+00:00",
        "details": {"root_disk": {"free_gib": 100}},
    }
    changed_measurement = json.loads(json.dumps(payload))
    changed_measurement["details"]["root_disk"]["free_gib"] = 99

    assert module.event_fingerprint(payload) == module.event_fingerprint(changed_measurement)


def test_event_fingerprint_ignores_numeric_message_fluctuations() -> None:
    module = _load_module()
    payload1 = {
        "status": "warning",
        "issues": [{"severity": "warning", "code": "root_disk_warning", "message": "root disk is 86.1% used with 20.2 GiB free"}],
    }
    payload2 = {
        "status": "warning",
        "issues": [{"severity": "warning", "code": "root_disk_warning", "message": "root disk is 86.3% used with 19.8 GiB free"}],
    }
    assert module.event_fingerprint(payload1) == module.event_fingerprint(payload2)


def test_event_fingerprint_changes_when_intervention_changes() -> None:
    module = _load_module()
    healthy = {"status": "healthy", "issues": []}
    critical = {
        "status": "critical",
        "issues": [{"severity": "critical", "code": "postgres_not_ready", "message": "down"}],
    }

    assert module.event_fingerprint(healthy) != module.event_fingerprint(critical)


@pytest.mark.parametrize("fault,expected", [(None, "healthy"), ("exhausted", "critical"), ("recovery-target", "warning"), ("unreadable", "warning")])
def test_guardian_reports_same_guard_allocation_pressure(monkeypatch, fault, expected):
    module = _load_module()
    gib = 1024**3
    reports = []
    for path in ("/", "/srv/workspaces"):
        usage = {"size": 100 * gib, "free": 30 * gib, "missing": 0, "unallocated": 20 * gib, "metadata_size": 2 * gib, "metadata_used": gib}
        if path == "/" and fault in {"exhausted", "recovery-target"}:
            usage.update(unallocated=1024**2 if fault == "exhausted" else 10 * gib, metadata_used=int(2 * gib * 0.9146))
        report = {"path": path, "uuid": "qualified", "after": usage, "policy": {"trigger_bytes": 8 * gib, "target_bytes": 12 * gib}}
        if path == "/" and fault == "unreadable":
            report = {"path": path, "error": "cannot measure usage"}
        reports.append(report)
    def run(args, **kwargs):
        assert args == [module.SPACE_GUARD, "--check-only"]
        return subprocess.CompletedProcess(args, int(fault is not None), "\n".join(json.dumps(report) for report in reports), "")
    monkeypatch.setattr(module, "run", run)
    state = module.CheckState()
    module.check_allocation_headroom(state)
    assert state.status == expected
    assert state.details["btrfs_allocation"][1]["after"]["unallocated"] == 20 * gib
    if fault in {"exhausted", "recovery-target"}:
        assert state.details["btrfs_allocation"][0]["metadata_used_percent"] == 91.46


@pytest.mark.parametrize("fault,expected", [(None, "healthy"), ("partial", "warning"), ("database-gap", "warning"), ("expired", "critical"), ("failed", "critical"), ("stale", "critical"), ("unreadable", "warning")])
def test_native_config_switches_guardian_without_veeam_restart(monkeypatch, tmp_path, fault, expected):
    module = _load_module()
    config = tmp_path / "btrbk.conf"
    config.write_text("root-owned fixture")
    monkeypatch.setattr(module, "NATIVE_CONFIG", config)
    original_lstat = Path.lstat
    def trusted(path):
        if path == config or path in config.parents:
            return SimpleNamespace(st_uid=0, st_mode=0o100644 if path == config else 0o40755)
        return original_lstat(path)
    monkeypatch.setattr(Path, "lstat", trusted)
    monkeypatch.setattr(module.pwd, "getpwnam", lambda _: SimpleNamespace(pw_dir="/home/operator", pw_uid=1000))
    now = datetime(2026, 10, 7, 20, tzinfo=UTC)
    monkeypatch.setattr(module, "now_utc", lambda: now)
    good = {"run_id": "20261007T190000Z-abcd1234", "status": "completed", "capture_complete": True, "artifacts_complete": True,
            "finished_at": (now - timedelta(hours=1)).isoformat(), "points": [{"source": "/"}], "database_recovery": {"status": "qualified", "missing": []}}
    latest = {**good, "database_recovery": dict(good["database_recovery"])}
    if fault == "partial":
        latest.update(status="partial", reason="database-recovery-incomplete")
    elif fault == "database-gap":
        latest["database_recovery"] = {"status": "partial", "missing": [{"project_id": "private-project"}]}
    elif fault == "expired":
        good["point_availability"] = "expired"
    elif fault == "failed":
        latest["status"] = "failed"
    elif fault == "stale":
        good["finished_at"] = (now - timedelta(hours=61)).isoformat()
    def read(path, uid):
        if fault == "unreadable":
            raise ValueError("unsafe receipt")
        return latest if path.name == "latest.json" else good
    monkeypatch.setattr(module, "_read_native_receipt", read)
    monkeypatch.setattr(module, "run", lambda *_args, **_kwargs: pytest.fail("Native health checks must never restart Veeam or capture backups"))
    state = module.CheckState()
    module.check_backup(state)
    assert state.status == expected
    assert state.details["linux_backup_engine"] == "btrbk"
    assert "private-project" not in json.dumps(state.details)
    if fault is None:
        assert state.details["native_backup"]["restore_verified"] is False


def test_native_receipt_read_requires_private_owned_regular_file(monkeypatch, tmp_path):
    module = _load_module()
    uid = module.os.getuid()
    path = tmp_path / "latest.json"
    path.write_text(json.dumps({"adapter": "summitflow-btrbk-v1", "run_id": "20261007T190000Z-abcd1234", "status": "completed"}))
    path.chmod(0o600)
    original_lstat = Path.lstat
    group_parent = {"mode": 0o40775, "gid": module.pwd.getpwuid(uid).pw_gid}
    def trusted_parent(item):
        if item == path.parent.parent:
            return SimpleNamespace(st_uid=uid, st_gid=group_parent["gid"], st_mode=group_parent["mode"])
        if item in path.parents:
            return SimpleNamespace(st_uid=uid if item == path.parent else 0, st_mode=0o40700 if item == path.parent else 0o40755)
        return original_lstat(item)
    monkeypatch.setattr(Path, "lstat", trusted_parent)
    assert module._read_native_receipt(path, uid)["status"] == "completed"
    group_parent["gid"] += 1
    with pytest.raises(ValueError, match="Unsafe"):
        module._read_native_receipt(path, uid)
    group_parent["gid"] -= 1
    group_parent["mode"] = 0o40777
    with pytest.raises(ValueError, match="Unsafe"):
        module._read_native_receipt(path, uid)
    group_parent["mode"] = 0o40775
    path.chmod(0o644)
    with pytest.raises(ValueError, match="private"):
        module._read_native_receipt(path, uid)
    path.chmod(0o600)
    link = tmp_path / "linked.json"
    link.symlink_to(path)
    with pytest.raises(OSError):
        module._read_native_receipt(link, uid)
