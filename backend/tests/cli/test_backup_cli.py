"""`st backup`: health first, Drive snapshots, run, restore and the old-backup readers."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from typer.testing import CliRunner

from app.tasks import backup_offsite, backup_offsite_restore, backup_overview, backup_run
from cli.commands import backup
from cli.commands.backup_formatters import ago, format_size, render_status

runner = CliRunner()
NOW = datetime(2026, 10, 26, 12, 0, tzinfo=UTC)


def _overview(problems: list[dict[str, str]] | None = None) -> dict:
    hours_ago = (NOW - timedelta(hours=3)).isoformat()
    return {
        "generated_at": NOW.isoformat(), "ok": not problems, "problems": problems or [],
        "local": {
            "engine": "btrbk", "enabled": True, "schedule": "every 4 hours", "keeps": "7 days", "last_run": {"status": "completed"},
            "last_good_at": hours_ago, "next_run_at": None, "points": {"home": 8, "workspaces": 8},
            "target": {"path": "/mnt/t7", "free_bytes": 600 * 1024**3, "used_bytes": 400 * 1024**3, "total_bytes": 1000 * 1024**3},
        },
        "offsite": {
            "engine": "restic", "schedule": "daily", "running": None, "last_success_at": hours_ago, "status": "ok", "error": None,
            "jobs": {"workspaces": {"time": hours_ago, "snapshot_id": "abcdef123456", "bytes": 5 * 1024**3, "stored_bytes": 1024**3}},
            "check": {"status": "ok", "sample": "500M", "checked_at": hours_ago},
            "spot_restore": {"status": "ok", "at": hours_ago}, "maintenance": {},
        },
        "legacy": {
            "local_repository": {"path": "/mnt/t7/restic", "bytes": 200 * 1024**3},
            "drive_snapshots": {"count": 40, "ages_out_after_days": 30},
        },
    }


def test_status_says_current_then_local_then_drive(monkeypatch) -> None:
    monkeypatch.setattr(backup_overview, "overview", lambda **_: _overview())
    result = runner.invoke(backup.app, ["status"])
    assert result.exit_code == 0
    lines = result.output.splitlines()
    assert lines[0] == "All backups current."
    assert result.output.index("Local: btrbk") < result.output.index("Google Drive: restic")
    assert "home 8, workspaces 8" in result.output
    assert "600.0 GB free of 1000.0 GB" in result.output
    assert "Test restore: ok" in result.output
    assert "You can delete it." in result.output


def test_status_says_when_the_old_t7_repository_is_gone(monkeypatch) -> None:
    data = _overview()
    data["legacy"]["local_repository"] = {"path": "/mnt/t7/restic", "bytes": None, "missing": True}
    monkeypatch.setattr(backup_overview, "overview", lambda **_: data)
    result = runner.invoke(backup.app, ["status"])
    assert "T7 restic repository: not found at /mnt/t7/restic." in result.output
    assert "You can delete it." not in result.output


def test_status_says_the_old_drive_snapshots_are_kept_while_the_age_out_is_paused(monkeypatch) -> None:
    data = _overview()
    data["legacy"]["drive_snapshots"] = {"count": 40, "ages_out_after_days": 36500, "paused": True}
    monkeypatch.setattr(backup_overview, "overview", lambda **_: data)
    result = runner.invoke(backup.app, ["status"])
    assert "Google Drive: 40 per-project snapshots, kept (the age-out is paused)" in result.output
    assert "36500" not in result.output


def test_status_lists_real_problems_and_fails(monkeypatch) -> None:
    problem = {"key": "offsite-missing", "title": "No recent Google Drive backup", "message": "The last good one was 3 days ago."}
    monkeypatch.setattr(backup_overview, "overview", lambda **_: _overview([problem]))
    result = runner.invoke(backup.app, ["status"])
    assert result.exit_code == 1
    assert result.output.startswith("1 backup problem:")
    assert "No recent Google Drive backup: The last good one was 3 days ago." in result.output


def test_status_json_is_the_overview(monkeypatch) -> None:
    monkeypatch.setattr(backup_overview, "overview", lambda **_: _overview())
    result = runner.invoke(backup.app, ["status", "--json"])
    assert json.loads(result.output)["ok"] is True


def test_status_renders_without_drive_data() -> None:
    overview = _overview()
    overview["offsite"].update(jobs={}, check=None, spot_restore=None, last_success_at=None)
    overview["legacy"] = {}
    text = render_status(overview, NOW)
    assert "Last good run: never" in text
    assert "Old backups" not in text


def test_ago_uses_singular_for_one_unit() -> None:
    assert ago((NOW - timedelta(hours=1)).isoformat(), NOW) == "1 hour ago"
    assert ago((NOW - timedelta(hours=21)).isoformat(), NOW) == "21 hours ago"
    assert ago((NOW - timedelta(minutes=1)).isoformat(), NOW) == "1 minute ago"
    assert ago((NOW - timedelta(days=3)).isoformat(), NOW) == "3 days ago"


def test_format_size() -> None:
    assert format_size(None) == "-"
    assert format_size(512) == "512 B"
    assert format_size(3 * 1024**2) == "3.0 MB"


def test_list_without_selector_keeps_latest_snapshot_per_job(monkeypatch) -> None:
    rows = [
        {"id": "a1", "full_id": "a1x", "time": "2026-10-26T02:00:00+00:00", "job": "workspaces", "btrbk_run": "r2", "paths": ["/srv/workspaces"]},
        {"id": "b1", "full_id": "b1x", "time": "2026-10-26T02:05:00+00:00", "job": "postgres", "btrbk_run": "r2", "paths": ["/postgres.sql"]},
        {"id": "a0", "full_id": "a0x", "time": "2026-10-25T02:00:00+00:00", "job": "workspaces", "btrbk_run": "r1", "paths": ["/srv/workspaces"]},
    ]
    seen: list[str | None] = []
    monkeypatch.setattr(backup_offsite_restore, "snapshots", lambda selector=None, **_: seen.append(selector) or rows)
    result = runner.invoke(backup.app, ["list", "--json"])
    assert [row["id"] for row in json.loads(result.output)] == ["b1", "a1"]
    assert seen == [None]


def test_list_with_project_passes_selector_and_limit(monkeypatch) -> None:
    calls: list[tuple] = []
    monkeypatch.setattr(backup_offsite_restore, "snapshots", lambda selector=None, limit=20, **_: calls.append((selector, limit)) or [])
    result = runner.invoke(backup.app, ["list", "aico", "--limit", "3"])
    assert result.exit_code == 0
    assert calls == [("aico", 3)]
    assert "No snapshots found." in result.output


def test_drive_errors_are_one_plain_line(monkeypatch) -> None:
    def fail(*_args, **_kwargs):
        raise backup_offsite.OffsiteError("the Google Drive repository is not reachable")

    monkeypatch.setattr(backup_offsite_restore, "snapshots", fail)
    result = runner.invoke(backup.app, ["list", "aico"])
    assert result.exit_code == 1
    assert "the Google Drive repository is not reachable" in result.output
    assert "Traceback" not in result.output


def test_show_without_selector_prints_each_jobs_last_good_snapshot(monkeypatch) -> None:
    monkeypatch.setattr(backup_offsite, "read_state", lambda: {"jobs": {"home": {"snapshot_id": "ffeedd001122", "tags": ["offsite", "job:home"],
                                                                                 "files": 10, "bytes": 2048, "time": NOW.isoformat()}}})
    result = runner.invoke(backup.app, ["show"])
    assert result.exit_code == 0
    assert "home: snapshot ffeedd00" in result.output
    assert "Tags: offsite, job:home" in result.output


@pytest.mark.parametrize("flags,expected_dry", [([], False), (["--dry-run"], True)])
def test_restore_passes_project_target_and_dry_run(monkeypatch, tmp_path, flags, expected_dry) -> None:
    calls: list[dict] = []

    def fake(selector, target, **kwargs):
        calls.append({"selector": selector, "target": target, **kwargs})
        return {"selector": selector, "snapshot": "a1b2c3", "snapshot_time": NOW.isoformat(), "path": "/srv/workspaces/projects/aico",
                "target": str(target), "dry_run": kwargs["dry_run"], "restored": str(target / "srv")}

    monkeypatch.setattr(backup_offsite_restore, "restore", fake)
    result = runner.invoke(backup.app, ["restore", "aico", "--to", str(tmp_path / "back"), "--at", "2026-10-25", *flags])
    assert result.exit_code == 0, result.output
    assert calls[0]["selector"] == "aico" and calls[0]["dry_run"] is expected_dry
    assert calls[0]["snapshot"] is None and calls[0]["at"].tzinfo is not None
    assert ("Nothing written" in result.output) is expected_dry


def test_restore_rejects_snapshot_with_at_and_bad_time(tmp_path) -> None:
    both = runner.invoke(backup.app, ["restore", "aico", "--to", str(tmp_path), "--snapshot", "a1", "--at", "2026-10-25"])
    assert both.exit_code == 1 and "not both" in both.output
    bad = runner.invoke(backup.app, ["restore", "aico", "--to", str(tmp_path), "--at", "yesterday-ish"])
    assert bad.exit_code == 1 and "--at needs a date" in bad.output


def test_restore_requires_a_target() -> None:
    assert runner.invoke(backup.app, ["restore", "aico"]).exit_code != 0


def test_run_starts_the_unit_and_reports_failure(monkeypatch) -> None:
    requested: list[bool] = []
    monkeypatch.setattr(backup_run, "request_run", lambda *, with_offsite=False: requested.append(with_offsite) or {"started": True, "unit": backup_run.UNIT})
    ok = runner.invoke(backup.app, ["run", "--offsite"])
    assert ok.exit_code == 0 and "Started summitflow-host-backup.service with the Google Drive copy" in ok.output
    assert requested == [True]
    monkeypatch.setattr(backup_run, "request_run", lambda **_: {"started": False, "error": "unit not found"})
    failed = runner.invoke(backup.app, ["run"])
    assert failed.exit_code == 1 and "unit not found" in failed.output


def test_old_list_names_the_t7_repository_as_deletable(monkeypatch) -> None:
    monkeypatch.setattr(backup_offsite_restore, "legacy_snapshots", lambda source=None, **kw: [
        {"id": "o1", "full_id": "o1x", "time": "2026-09-01T02:00:00+00:00", "source": "aico"}] if kw["where"] == "local" else [])
    monkeypatch.setattr(backup_offsite, "read_state", lambda: {"legacy": {"local_repository_path": "/mnt/t7/restic", "local_repository_bytes": 2 * 1024**3}})
    result = runner.invoke(backup.app, ["old", "list", "--where", "local"])
    assert result.exit_code == 0
    assert "/mnt/t7/restic, 2.0 GB" in result.output and "the owner can delete it" in result.output
    assert "o1" in result.output and "aico" in result.output


def test_old_restore_passes_where_and_include(monkeypatch, tmp_path: Path) -> None:
    calls: list[tuple] = []

    def fake(snapshot, target, *, where, include):
        calls.append((snapshot, target, where, include))
        return {"snapshot": snapshot, "where": where, "target": str(target), "include": include}

    monkeypatch.setattr(backup_offsite_restore, "restore_legacy", fake)
    result = runner.invoke(backup.app, ["old", "restore", "o1", "--to", str(tmp_path / "x"), "--where", "local", "--include", "/etc"])
    assert result.exit_code == 0, result.output
    assert calls == [("o1", tmp_path / "x", "local", "/etc")]


def test_approve_deletion_passes_the_owner_words_and_reports_bad_input(monkeypatch) -> None:
    from app.tasks import backup_safety

    seen: list[tuple] = []
    monkeypatch.setattr(backup_safety, "approve_deletion", lambda kind, *, target, owner_approved: seen.append((kind, target, owner_approved)) or {"ok": True})
    args = ["approve-deletion", "btrbk-target", "--target", "/mnt/t7", "--owner-approved", "owner said yes in chat 2026-10-26"]
    assert runner.invoke(backup.app, args).exit_code == 0
    assert seen == [("btrbk-target", "/mnt/t7", "owner said yes in chat 2026-10-26")]

    def refuse(*_args, **_kwargs):
        raise ValueError("--owner-approved must quote the owner's approval from chat, with the date")

    monkeypatch.setattr(backup_safety, "approve_deletion", refuse)
    bad = runner.invoke(backup.app, [*args[:-1], "ok"])
    assert bad.exit_code == 1 and "must quote the owner's approval" in bad.output


def test_restic_errors_show_only_their_sentence() -> None:
    raw = 'restic snapshots failed (exit 1): {"message_type":"exit_error","code":1,"message":"open /x/version: permission denied\\nreadVersion"}'
    assert backup._plain(raw) == "restic snapshots failed (exit 1): open /x/version: permission denied"
    assert backup._plain("plain text") == "plain text"


@pytest.mark.parametrize("gone", ["create", "sources", "schedule", "storage", "infra", "testbed", "cleanup-local", "sync-offsite", "all", "source"])
def test_retired_commands_are_gone(gone: str) -> None:
    assert gone not in {command.name for command in backup.app.registered_commands} | {group.name for group in backup.app.registered_groups}
