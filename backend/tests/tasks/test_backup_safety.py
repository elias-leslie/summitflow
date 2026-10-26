"""Deletion circuit breaker, safety status contract and write window."""

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


def test_trip_is_recorded_alerted_once_and_kept_until_retention_is_normal(notifications):
    assert safety.guard_deletion("restic-retention", "local", delete=5, total=100) is True
    assert safety.read_status()["status"] == "ok"
    assert safety.guard_deletion("restic-retention", "local", delete=80, total=100) is False
    assert safety.guard_deletion("restic-retention", "local", delete=80, total=100) is False
    status = safety.read_status()
    assert status["status"] == "alert" and status["version"] == 1
    assert status["alerts"][0]["kind"] == "deletion-breaker"
    assert "Refused restic-retention deletion on local" in status["alerts"][0]["message"]
    assert len(notifications) == 1 and notifications[0]["severity"] == "error"
    # The breaker message names the target, never a kind-wide approval, and tells the agent to ask the owner in chat first.
    assert "approve-deletion restic-retention --target local --owner-approved" in notifications[0]["message"]
    assert "ask them in chat" in notifications[0]["message"] and "passkey" not in notifications[0]["message"]
    # A normal run clears the breaker.
    assert safety.guard_deletion("restic-retention", "local", delete=5, total=100) is True
    assert safety.read_status()["status"] == "ok"


def test_owner_approval_lifts_the_breaker_for_exactly_one_run(notifications):
    assert safety.guard_deletion("restic-retention", "local", delete=80, total=100) is False
    approval = safety.approve_deletion("restic-retention", target="local", owner_approved="owner said go, 2026-10-24")
    assert approval["planned_delete"] == 80 and approval["owner_approved"] == "owner said go, 2026-10-24"
    assert notifications[-1]["title"] == "Backup deletion approved by the owner"
    assert "owner said go" in notifications[-1]["message"] and notifications[-1]["severity"] == "warning"
    assert safety.read_status()["approvals"]["restic-retention:local"]["owner_approved"] == "owner said go, 2026-10-24"
    # Approving changes nothing by itself: the breaker stays tripped until the run comes round.
    assert safety.read_status()["status"] == "alert"
    # The next run goes ahead, is recorded and announced, and spends the approval.
    assert safety.guard_deletion("restic-retention", "local", delete=80, total=100) is True
    status = safety.read_status()
    assert status["status"] == "ok" and status["approvals"] == {}
    assert status["approval_log"][-1]["owner_approved"] == "owner said go, 2026-10-24" and status["approval_log"][-1]["used_planned_delete"] == 80
    assert notifications[-1]["title"] == "Backup deletion allowed once"
    # The run after that is refused again, and alerts again.
    assert safety.guard_deletion("restic-retention", "local", delete=80, total=100) is False
    assert safety.read_status()["status"] == "alert"
    assert notifications[-1]["title"] == "Backup deletion refused"


def test_owner_approval_does_not_cover_a_bigger_plan_or_other_targets(notifications):
    assert safety.guard_deletion("restic-retention", "local", delete=80, total=100) is False
    assert safety.guard_deletion("restic-retention", "offsite", delete=80, total=100) is False
    safety.approve_deletion("restic-retention", target="local", owner_approved="owner said go, 2026-10-24")
    assert safety.guard_deletion("restic-retention", "offsite", delete=80, total=100) is False  # Other target.
    assert safety.guard_deletion("restic-retention", "local", delete=90, total=100) is False  # Plan grew.
    assert safety.read_status()["approvals"] == {}  # The stale approval is dropped, not kept for later.
    assert safety.guard_deletion("restic-retention", "local", delete=80, total=100) is False


def test_owner_approval_expires_and_is_cleared_when_retention_is_normal_again(notifications, monkeypatch):
    assert safety.guard_deletion("restic-retention", "local", delete=80, total=100) is False
    safety.approve_deletion("restic-retention", target="local", owner_approved="owner said go, 2026-10-24")
    assert safety.guard_deletion("restic-retention", "local", delete=5, total=100) is True
    assert safety.read_status()["approvals"] == {}
    assert safety.guard_deletion("restic-retention", "local", delete=80, total=100) is False
    safety.approve_deletion("restic-retention", target="local", owner_approved="owner said go, 2026-10-24")
    later = datetime.now(UTC) + safety.APPROVAL_TTL + timedelta(minutes=1)
    monkeypatch.setattr(safety, "_now", lambda: later)
    assert safety.guard_deletion("restic-retention", "local", delete=80, total=100) is False


def test_approve_deletion_needs_a_refused_run_on_that_target_and_the_owner_words(notifications):
    with pytest.raises(ValueError, match="No refused restic-retention deletion on local"):
        safety.approve_deletion("restic-retention", target="local", owner_approved="pre-approved by me")
    assert safety.guard_deletion("restic-retention", "offsite", delete=80, total=100) is False
    with pytest.raises(ValueError):
        safety.approve_deletion("restic-retention", target="local", owner_approved="wrong target entirely")
    with pytest.raises(ValueError, match="quote the owner's approval"):
        safety.approve_deletion("restic-retention", target="offsite", owner_approved="  ok ")
    assert safety.read_status()["approvals"] == {}


def test_cli_approve_deletion_requires_target_and_owner_approval(notifications):
    from typer.testing import CliRunner

    from cli.main import app

    runner = CliRunner()
    missing_target = runner.invoke(app, ["backup", "approve-deletion", "restic-retention", "--owner-approved", "owner said go, 2026-10-24"])
    assert missing_target.exit_code != 0 and "--target" in missing_target.output
    missing_approval = runner.invoke(app, ["backup", "approve-deletion", "restic-retention", "--target", "local"])
    assert missing_approval.exit_code != 0 and "--owner-approved" in missing_approval.output
    args = ["backup", "approve-deletion", "restic-retention", "--target", "local", "--owner-approved", "owner said go, 2026-10-24"]
    no_breaker = runner.invoke(app, args)
    assert no_breaker.exit_code == 1 and "No refused restic-retention deletion on local" in no_breaker.output
    assert safety.guard_deletion("restic-retention", "local", delete=80, total=100) is False
    recorded = runner.invoke(app, args)
    assert recorded.exit_code == 0 and '"owner_approved": "owner said go, 2026-10-24"' in recorded.output
    assert safety.guard_deletion("restic-retention", "local", delete=80, total=100) is True
    assert safety.guard_deletion("restic-retention", "local", delete=80, total=100) is False


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
    assert maintain.breaker(mistake)[0].startswith("plan removes 149 of 247 snapshots")
    assert maintain.unexplained_loss(1000, 990) is None
    assert maintain.unexplained_loss(1000, 500).startswith("snapshot count fell")


def test_pve_side_maintenance_clears_stale_locks_before_anything_else(monkeypatch, tmp_path):
    # Regression: two pushers killed on 10-13 left locks that failed every run until 10-16.
    maintain = _maintain_module()
    calls: list[tuple[str, ...]] = []

    def fake(*args: str, capture: bool = True):
        calls.append(args)
        raise subprocess.CalledProcessError(1, "restic", stderr="stop here")

    monkeypatch.setattr(maintain, "_restic", fake)
    monkeypatch.setattr(maintain, "STATUS_PATH", tmp_path / "status.json")
    monkeypatch.setattr(maintain, "REPO", str(tmp_path / "repo"))
    assert maintain.main() == 1
    assert calls == [("unlock",)]


def test_pve_side_weekly_expiry_of_floor_and_retired_sources_does_not_trip():
    # Regression: the weekly run removes about half of every 7-day source and
    # most of a retired one; that is normal retention, not a breaker trip.
    maintain = _maintain_module()
    now = datetime(2026, 10, 18, 5, 31, tzinfo=UTC)

    def points(source: str, newest: int, oldest: int) -> list[dict[str, Any]]:
        return [{"id": f"{source}-{hour}", "tags": [f"source:{source}"], "time": (now - timedelta(hours=hour)).isoformat()} for hour in range(newest * 24, oldest * 24, 5)]

    snapshots = points("week", 0, 14) + points("retired", 5, 12) + points("month", 0, 37) + points("month2", 0, 37)
    policy = {"default_days": 30, "sources": {"week": 7, "retired": 7, "month": 30, "month2": 30}}
    plan = maintain.plan_retention(snapshots, policy, now)
    assert plan["per_source"]["week"]["delete"] * 2 >= plan["per_source"]["week"]["total"]
    assert plan["per_source"]["retired"]["delete"] == plan["per_source"]["retired"]["total"] - 10
    assert maintain.breaker(plan) == []
    # A clock jump of a few weeks still trips the whole plan.
    assert maintain.breaker(maintain.plan_retention(snapshots, policy, now + timedelta(days=21)))


def test_pve_side_retention_keeps_newest_full_history_capture():
    maintain = _maintain_module()
    now = datetime(2026, 10, 16, tzinfo=UTC)

    def point(name: str, age: int, *tags: str) -> dict[str, Any]:
        return {"id": name, "tags": ["source:a", *tags], "time": (now - timedelta(days=age)).isoformat()}

    snapshots = [point("new1", 0), point("new2", 1), point("new3", 2), point("full-newest", 10, maintain.FULL_HISTORY_TAG), point("full-older", 17, maintain.FULL_HISTORY_TAG), point("old", 20)]
    plan = maintain.plan_retention(snapshots, {"default_days": 30, "sources": {"a": 7}}, now)
    assert plan["delete"] == ["full-older", "old"]


def test_pve_serve_wrapper_only_serves_or_reports_status():
    wrapper = (REPO_ROOT / "scripts" / "pve-restic-append" / "restic-append-serve").read_text()
    stdio = (REPO_ROOT / "scripts" / "pve-restic-append" / "restic-append-stdio").read_text()
    assert "--append-only" in stdio and "runuser -u restic" in stdio
    assert 'status) exec /usr/sbin/pct exec "$CT" -- /bin/cat /var/lib/restic-append/status.json' in wrapper
    assert json.dumps("SSH_ORIGINAL_COMMAND")[1:-1] in wrapper


