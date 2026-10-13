"""Deletion circuit breaker, safety status contract, write window, PVE copy and weekly health."""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from app.tasks import backup_safety as safety

REPO_ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture
def notifications(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    from app.storage import notifications as store

    sent: list[dict[str, Any]] = []
    monkeypatch.setattr(store, "create_notification", lambda **kwargs: sent.append(kwargs) or {"id": "n"})
    return sent


def test_normal_retention_passes_and_oversized_plans_trip():
    assert safety.evaluate_deletion(delete=6, total=200) == []
    assert safety.evaluate_deletion(delete=10, total=12) == []  # Small absolute counts never trip on total.
    assert safety.evaluate_deletion(delete=60, total=200)[0].startswith("would remove 60 of 200")
    reasons = safety.evaluate_deletion(delete=20, total=400, groups={"neri": (20, 30), "aico": (6, 42)})
    assert reasons == ["would remove 20 of 30 points of neri (> 50%)"]


def test_trip_is_recorded_alerted_once_and_kept_until_approved(notifications):
    assert safety.guard_deletion("restic-retention", "local", delete=5, total=100) is True
    assert safety.read_status()["status"] == "ok"
    assert safety.guard_deletion("restic-retention", "local", delete=80, total=100) is False
    assert safety.guard_deletion("restic-retention", "local", delete=80, total=100) is False
    status = safety.read_status()
    assert status["status"] == "alert" and status["version"] == 1
    assert status["alerts"][0]["kind"] == "deletion-breaker"
    assert "Refused restic-retention deletion on local" in status["alerts"][0]["message"]
    assert len(notifications) == 1 and notifications[0]["severity"] == "error"
    safety.approve_deletion("restic-retention", reason="retention lowered on purpose")
    assert safety.guard_deletion("restic-retention", "local", delete=80, total=100) is True
    assert safety.read_status()["status"] == "ok"
    # The approval is single-use.
    assert safety.guard_deletion("restic-retention", "local", delete=80, total=100) is False


def test_expired_approval_does_not_apply(notifications):
    with safety._locked_status() as status:
        status["approvals"]["btrbk-target"] = {"reason": "x", "expires_at": (datetime.now(UTC) - timedelta(hours=1)).isoformat()}
    assert safety.guard_deletion("btrbk-target", "/t", delete=30, total=36) is False


def test_section_alerts_raise_top_level_status():
    safety.record_section("pve_copy", {"alerts": [{"kind": "stale", "message": "old"}]})
    status = safety.read_status()
    assert status["status"] == "alert"
    assert status["alerts"] == [{"key": "pve_copy:stale", "kind": "stale", "message": "old", "since": status["sections"]["pve_copy"]["updated_at"]}]
    safety.record_section("pve_copy", {"alerts": []})
    assert safety.read_status()["status"] == "ok"


def test_status_file_is_world_readable_for_nightshift():
    safety.record_section("health", {"alerts": []})
    assert safety.status_path().stat().st_mode & 0o044 == 0o044


def test_restic_retention_refuses_oversized_forget(tmp_path, notifications, monkeypatch):
    from app.tasks import backup_restic as engine
    from app.utils import transient_scratch
    from tests.tasks.test_backup_restic import FakeProcess

    scratch = tmp_path / "scratch"  # CI runners have no /srv/scratch.
    scratch.mkdir(mode=0o700)
    monkeypatch.setattr(transient_scratch, "SCRATCH_ROOT", scratch)
    real_is_mount = Path.is_mount
    monkeypatch.setattr(Path, "is_mount", lambda path: path == scratch or real_is_mount(path))

    keys = tmp_path / "keys"
    keys.mkdir(mode=0o700)
    (keys / "local-password").write_bytes(b"fixture")
    (keys / "local-password").chmod(0o600)
    config = engine.ResticConfig(local_repository=tmp_path / "repo", local_password_file=keys / "local-password",
                                 key_directory=keys, lock_directory=tmp_path / "locks", hostname="fixture-host")
    process = FakeProcess(tmp_path)
    now = datetime.now(UTC)
    # A one-day window on a source with 30 days of 4-hourly points: almost all would go.
    process.local_snapshots = [{"id": f"{number:064x}", "tags": ["source:fixture"], "time": (now - timedelta(hours=4 * number)).isoformat()} for number in range(1, 181)]
    adapter = engine.ResticAdapter(config, runner=process)
    result = adapter.retention({"fixture": 1}, state={}, dry_run=False)
    assert result["status"] == "refused" and result["delete"] == [] and len(result["refused_delete"]) > 100
    assert not any("forget" in command for command in process.commands)
    normal = adapter.retention({"fixture": 29}, state={}, dry_run=False)
    assert normal["status"] == "completed" and len(normal["delete"]) in {6, 7}  # Window edge point.


def test_prune_guard_detects_snapshots_lost_outside_retention(notifications):
    from app.tasks.backup_repository_runtime import _snapshot_count_explained

    previous: dict[str, Any] = {}
    assert _snapshot_count_explained(previous, {"keep": ["a"] * 100, "delete": ["b"] * 4}, "local") is True
    assert previous["snapshot_count"] == 100
    assert _snapshot_count_explained(previous, {"keep": ["a"] * 98, "delete": []}, "local") is True
    assert _snapshot_count_explained(previous, {"keep": ["a"] * 40, "delete": []}, "local") is False
    assert previous["snapshot_count"] == 98  # Baseline kept so the condition stays visible.


def test_btrbk_expiry_beyond_daily_retention_preserves_backups(monkeypatch, notifications):
    from app.tasks import backup_btrbk as host

    target = Path("/mnt/native/native")
    names = [f"{subvolume}.2026100{day}T023001-0400" for subvolume in ("root", "home") for day in range(1, 8)]
    rows = lambda deleting: "\n".join(f"format=\"transaction\" type='delete_target' status='dryrun_success' target_url='{target / name}'" for name in deleting)  # noqa: E731
    plan = {"stdout": rows(names[:1] + names[7:8])}
    monkeypatch.setattr(host, "_run", lambda args: subprocess.CompletedProcess(args, 0, plan["stdout"], ""))
    monkeypatch.setattr(host, "NATIVE_TARGET", target)
    monkeypatch.setattr(host, "_checked", lambda args, **_: "\n".join(str(target / name) for name in names) + "\n")
    assert host._target_deletions_refused(target) is False
    plan["stdout"] = rows(names[:5] + names[7:12])
    assert host._target_deletions_refused(target) is True


def test_native_archive_cleanup_refuses_mass_orphaning(tmp_path, notifications):
    from app.tasks.backup_local_cleanup import cleanup_local_backup_archives
    from tests.tasks.test_backup_local_cleanup import _touch

    now = datetime(2026, 6, 16, tzinfo=UTC)
    root = tmp_path / "project-backups"
    archives = [_touch(root / "s" / f"s-202605{day:02d}-120000.tar.gz", now=now, age_days=40 + day) for day in range(1, 21)]
    result = cleanup_local_backup_archives(dry_run=False, now=now, roots=[root], current_locations=[], sources=[{"id": "s", "retention_days": 30}])
    assert result["status"] == "refused" and result["deleted"] == 0
    assert all(path.exists() for path in archives)


def test_write_window_is_reference_counted(monkeypatch, tmp_path):
    from app.tasks import backup_write_window as window

    helper = tmp_path / "helper"
    helper.write_text("#!/bin/sh\n")
    calls: list[list[str]] = []
    monkeypatch.setenv("SUMMITFLOW_BACKUP_WINDOW_HELPER", str(helper))
    monkeypatch.setattr(window.subprocess, "run", lambda args, **_: calls.append(args))
    with window.path_window("/media/kasadis/Backups/davion-gem/restic"), window.write_window("t7"), window.path_window("/srv/workspaces/elsewhere"):
        pass
    assert [call[3:5] for call in calls] == [["open", "t7"], ["close", "t7"]]
    assert calls[0][:3] == ["sudo", "-n", str(helper)] and calls[0][5] == str(os.getpid())
    assert window.window_name("/mnt/summitflow-native/native/root.x") == "native"


def test_write_window_without_helper_is_noop(monkeypatch):
    from app.tasks import backup_write_window as window

    monkeypatch.setattr(window.subprocess, "run", lambda *a, **k: pytest.fail("helper must not run"))
    with window.write_window("t7"):
        pass


def test_pve_copy_assessment_and_append_only_command(tmp_path):
    from app.tasks import backup_pve_copy as pve
    from app.tasks.backup_restic import ResticConfig

    now = datetime(2026, 10, 11, 12, tzinfo=UTC)
    fresh = {"last_success_at": (now - timedelta(hours=2)).isoformat()}
    assert pve.assess(fresh, {}, now=now, max_age_hours=26) == []
    stale = pve.assess({"last_success_at": (now - timedelta(hours=40)).isoformat(), "error": "ssh refused"}, {}, now=now, max_age_hours=26)
    assert stale[0]["kind"] == "stale" and "ssh refused" in stale[0]["message"]
    remote = {"finished_at": (now - timedelta(days=12)).isoformat(), "alerts": [{"kind": "deletion-breaker", "message": "plan too big"}]}
    kinds = [alert["kind"] for alert in pve.assess(fresh, remote, now=now, max_age_hours=26)]
    assert kinds == ["pve-maintenance-stale", "pve-deletion-breaker"]
    config = ResticConfig(local_repository=tmp_path / "repo", local_password_file=tmp_path / "keys/pw", key_directory=tmp_path / "keys")
    command = pve.restic_command(config, {"host": "192.0.2.1", "key": "pve.key"}, "copy")
    assert command[:6] == ["nice", "-n", "15", "ionice", "-c", "3"]
    assert "rclone.program=ssh" in command and command[-1] == "copy"
    assert any(part.startswith("rclone.args=-F /dev/null -i ") and part.endswith("root@192.0.2.1") for part in command)


def test_pve_copy_is_skipped_until_configured(tmp_path):
    from app.tasks import backup_pve_copy as pve

    keys = tmp_path / "keys"
    keys.mkdir(mode=0o700)
    (keys / "pw").write_bytes(b"x")
    result = pve.sync_pve_copy({"RESTIC_LOCAL_PASSWORD_FILE": str(keys / "pw"), "RESTIC_LOCAL_REPOSITORY": str(tmp_path / "repo")})
    assert result == {"status": "skipped", "reason": "pve-copy-not-configured"}


def test_weekly_health_drop_and_check_detection():
    from app.tasks.backup_weekly_health import check_alerts, drops

    assert drops({}, 100, 10) == []
    assert drops({"snapshot_count": 1000, "repository_bytes": 100}, 980, 90) == []
    assert [alert["kind"] for alert in drops({"snapshot_count": 1000, "repository_bytes": 100}, 700, 50)] == ["snapshot-count-drop", "repository-size-drop"]
    now = datetime(2026, 10, 11, tzinfo=UTC)
    summary, alerts = check_alerts({"local": {"monthly_result": {"status": "verified", "checked_at": (now - timedelta(days=1)).isoformat()}},
                                    "remote": {"monthly_result": {"status": "failed", "verified": False, "error": "pack mismatch"}}}, now)
    assert summary["local"]["status"] == "verified"
    assert [alert["kind"] for alert in alerts] == ["remote-check-failed"]


def _maintain_module():
    path = REPO_ROOT / "scripts" / "pve-restic-append" / "restic-append-maintain.py"
    spec = importlib.util.spec_from_file_location("restic_append_maintain", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_pve_side_retention_matches_policy_and_trips_on_mistakes():
    maintain = _maintain_module()
    now = datetime(2026, 10, 11, tzinfo=UTC)

    def points(source: str, days: int) -> list[dict[str, Any]]:
        return [{"id": f"{source}-{hour}", "tags": [f"source:{source}"], "time": (now - timedelta(hours=hour)).isoformat().replace("+00:00", ".123456789Z")} for hour in range(0, days * 24, 4)]

    snapshots = points("a", 32) + points("b", 9) + [{"id": "manual", "tags": [], "time": "2020-01-01T00:00:00Z"}]
    plan = maintain.plan_retention(snapshots, {"default_days": 30, "sources": {"a": 30, "b": 2}}, now)
    # b is floored at seven days; the untagged point is never selected.
    assert plan["per_source"] == {"a": {"total": 192, "delete": 11}, "b": {"total": 54, "delete": 11}}  # Edge point kept.
    assert "manual" not in plan["delete"] and maintain.breaker(plan) == []
    mistake = maintain.plan_retention(snapshots, {"default_days": 30, "sources": {"a": 1}}, now)
    assert any("of a" in reason for reason in maintain.breaker(mistake))
    assert maintain.unexplained_loss(1000, 990) is None
    assert maintain.unexplained_loss(1000, 500).startswith("snapshot count fell")


def test_pve_serve_wrapper_only_serves_or_reports_status():
    wrapper = (REPO_ROOT / "scripts" / "pve-restic-append" / "restic-append-serve").read_text()
    stdio = (REPO_ROOT / "scripts" / "pve-restic-append" / "restic-append-stdio").read_text()
    assert "--append-only" in stdio and "runuser -u restic" in stdio
    assert 'status) exec /usr/sbin/pct exec "$CT" -- /bin/cat /var/lib/restic-append/status.json' in wrapper
    assert json.dumps("SSH_ORIGINAL_COMMAND")[1:-1] in wrapper


def test_check_status_refreshes_every_tick_and_clears(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.tasks import backup_repository_runtime, backup_weekly_health

    now = datetime.now(UTC)
    journal = {"maintenance": {"local": {"monthly_result": {"status": "failed", "verified": False, "error": "lock"}},
                               "remote": {"monthly_result": {"status": "verified", "checked_at": now.isoformat()}}}}
    monkeypatch.setattr(backup_repository_runtime, "repository_journal", lambda _env: journal)
    assert backup_weekly_health.refresh_check_status({}, now=now)["status"] == "alert"
    assert safety.read_status()["status"] == "alert"
    journal["maintenance"]["local"]["monthly_result"] = {"status": "verified", "checked_at": now.isoformat()}
    assert backup_weekly_health.refresh_check_status({}, now=now)["status"] == "ok"
    assert safety.read_status()["sections"]["restic_checks"]["alerts"] == []
