"""Freshness of backups other projects run: systemd unit and artifact probes, and the receipt merge."""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

from app.tasks import backup_alerts, backup_external


def _show(values: dict[str, str]):
    def run(argv: list[str]) -> tuple[int, str]:
        if "--user" in argv:
            return 0, "LoadState=not-found\n"
        return 0, "".join(f"{k}={v}\n" for k, v in values.items())
    return run


def test_systemd_unit_success_failure_and_missing():
    ok = backup_external.probe(
        {"kind": "systemd_unit", "target": "blackbox-archive.service"},
        run=_show({"LoadState": "loaded", "Result": "success", "ExecMainStatus": "0", "ActiveState": "inactive",
                   "ExecMainExitTimestamp": "Sat 2026-10-17 10:25:45 EDT"}),
    )
    assert ok["last_status"] == "completed" and ok["last_success_at"].startswith("2026-10-17")
    failed = backup_external.probe(
        {"kind": "systemd_unit", "target": "x.service"},
        run=_show({"LoadState": "loaded", "Result": "exit-code", "ExecMainStatus": "23", "ActiveState": "failed",
                   "ExecMainExitTimestamp": "Sat 2026-10-17 10:25:45 EDT"}),
    )
    assert failed["last_status"] == "failed" and "exit 23" in failed["last_error"]
    missing = backup_external.probe({"kind": "systemd_unit", "target": "gone.service"},
                                    run=_show({"LoadState": "not-found"}))
    assert missing["last_error"] == "gone.service is not installed"


def test_systemd_unit_without_a_run_since_boot_reads_the_journal():
    def run_with(job_result: str | None):
        def run(argv: list[str]) -> tuple[int, str]:
            if argv[0] == "journalctl":
                assert "--user" in argv and "JOB_TYPE=start" in argv
                if job_result is None:
                    return 0, ""
                return 0, f'{{"JOB_RESULT": "{job_result}", "__REALTIME_TIMESTAMP": "1792912891389205"}}\n'
            if "--user" in argv:
                return 0, "LoadState=loaded\nResult=success\nActiveState=inactive\nExecMainExitTimestamp=\n"
            return 0, "LoadState=not-found\n"
        return run

    unit = {"kind": "systemd_unit", "target": "blackbox-archive.service"}
    done = backup_external.probe(unit, run=run_with("done"))
    assert done["last_status"] == "completed" and done["last_success_at"].startswith("2026-10-25T07:21")
    failed = backup_external.probe(unit, run=run_with("failed"))
    assert failed["last_status"] == "failed" and failed["last_success_at"] is None
    assert backup_external.probe(unit, run=run_with(None))["last_status"] == "never"


def test_systemd_time_in_utc_is_not_read_as_local_time():
    # A guest that runs in UTC prints "UTC"; strptime's %Z leaves that naive, which read as workstation time.
    parsed = backup_external._parse_systemd_time("Sun 2026-11-01 01:48:34 UTC")
    assert parsed == datetime(2026, 11, 1, 1, 48, 34, tzinfo=UTC)


def test_guest_unit_reads_the_unit_inside_the_owner_projects_guest(monkeypatch):
    from app import runtime_deployment as rd

    target = rd.ProxmoxDeployment(kind="proxmox", ssh_host="pve", vmid=180, user="app", uid=1000)
    calls: list[list[str]] = []

    def guest_command(placement, argv):
        assert placement is target
        calls.append(argv)
        if "--user" in argv:
            return ("LoadState=loaded\nResult=success\nExecMainStatus=0\nActiveState=inactive\n"
                    "ExecMainExitTimestamp=Sun 2026-11-01 01:48:34 UTC\n")
        return "LoadState=not-found\n"

    monkeypatch.setattr(rd, "_guest_status", lambda _: "running")
    monkeypatch.setattr(rd, "_guest_command", guest_command)
    source = {"kind": "guest_unit", "owner_project": "portfolio-ai", "target": "portfolio-backup.service"}
    seen = backup_external.probe(source, placement=lambda project: target if project == "portfolio-ai" else None)
    assert seen == {"last_success_at": "2026-11-01T01:48:34+00:00", "last_status": "completed", "last_error": None}
    assert calls and all("portfolio-backup.service" in argv for argv in calls)

    monkeypatch.setattr(rd, "_guest_status", lambda _: "stopped")
    stopped = backup_external.probe(source, placement=lambda _: target)
    assert stopped["last_status"] == "unknown" and stopped["last_error"] == "pve / VM 180 is stopped"

    unplaced = backup_external.probe(source, placement=lambda _: None)
    assert unplaced["last_success_at"] is None and "no Proxmox placement" in unplaced["last_error"]

    def unreachable(_):
        raise rd.DeploymentError("Could not reach pve / VM 180")
    monkeypatch.setattr(rd, "_guest_status", unreachable)
    assert backup_external.probe(source, placement=lambda _: target)["last_error"] == "Could not reach pve / VM 180"


def test_artifact_glob_uses_newest_non_empty_file(tmp_path: Path):
    old, new, empty = tmp_path / "a_1.tar.gz", tmp_path / "a_2.tar.gz", tmp_path / "a_3.tar.gz"
    old.write_text("x")
    new.write_text("y")
    empty.write_text("")
    stamp = datetime(2026, 10, 1, tzinfo=UTC).timestamp()
    os.utime(old, (stamp - 86400, stamp - 86400))
    os.utime(new, (stamp, stamp))
    seen = backup_external.probe({"kind": "artifact_glob", "target": str(tmp_path / "a_*.tar.gz")})
    assert seen["last_success_at"] == datetime(2026, 10, 1, tzinfo=UTC).isoformat()
    none = backup_external.probe({"kind": "artifact_glob", "target": str(tmp_path / "zz_*")})
    assert none["last_status"] == "never"


def test_external_sources_join_the_receipt_with_the_same_window(mocker, tmp_path: Path):
    now = datetime(2026, 10, 17, 12, tzinfo=UTC)
    mocker.patch.object(backup_alerts, "SOURCES_RECEIPT", tmp_path / "sources.json")
    mocker.patch.object(backup_external, "list_external_sources", return_value=[
        {"id": "blackbox-archive", "name": "Blackbox", "owner_project": "blackbox", "kind": "systemd_unit",
         "target": "blackbox-archive.service", "frequency": "daily", "enabled": True},
        {"id": "pai", "name": "PAI", "owner_project": "portfolio-ai", "kind": "artifact_glob",
         "target": "/x", "frequency": "weekly", "enabled": True},
        {"id": "off", "name": "Off", "owner_project": None, "kind": "artifact_glob", "target": "/y",
         "frequency": "daily", "enabled": False},
    ])
    seen = {"blackbox-archive": (now - timedelta(hours=30)).isoformat(), "pai": (now - timedelta(days=90)).isoformat()}
    mocker.patch.object(backup_external, "probe", lambda source: {
        "last_success_at": seen[source["id"]], "last_status": "completed", "last_error": None})
    out = backup_alerts.external_statuses(now)
    assert set(out) == {"blackbox-archive", "pai"}
    assert out["blackbox-archive"]["ok"] and out["blackbox-archive"]["stale_after_hours"] == 48.0
    assert not out["pai"]["ok"] and out["pai"]["last_error"] == "no success within the freshness window"
    assert out["pai"]["external"] is True


def test_unreadable_source_keeps_the_last_success_already_seen(mocker, tmp_path: Path):
    """A stopped guest is not a missed backup: the last success stays until it really leaves the window."""
    now = datetime(2026, 11, 1, 21, tzinfo=UTC)
    receipt = tmp_path / "sources.json"
    receipt.write_text(json.dumps({"sources": {
        "pai": {"last_success_at": (now - timedelta(hours=11)).isoformat()},
        "old": {"last_success_at": (now - timedelta(days=15)).isoformat()},
    }}))
    mocker.patch.object(backup_alerts, "SOURCES_RECEIPT", receipt)
    mocker.patch.object(backup_external, "list_external_sources", return_value=[
        {"id": source_id, "name": source_id, "owner_project": "portfolio-ai", "kind": "guest_unit",
         "target": "portfolio-backup.service", "frequency": "weekly", "enabled": True}
        for source_id in ("pai", "old", "new")
    ])
    mocker.patch.object(backup_external, "probe", lambda source: {
        "last_success_at": None, "last_status": "unknown", "last_error": "davion-gem / VM 180 is stopped"})
    out = backup_alerts.external_statuses(now)
    assert out["pai"]["ok"] and out["pai"]["last_success_at"] == (now - timedelta(hours=11)).isoformat()
    assert out["pai"]["last_error"] == "davion-gem / VM 180 is stopped"
    assert not out["old"]["ok"] and out["old"]["last_success_at"] == (now - timedelta(days=15)).isoformat()
    assert not out["new"]["ok"] and out["new"]["last_success_at"] is None
    conditions = backup_alerts._external_conditions(out, now)
    assert conditions["sources-stale"]["reason"] == "sources-stale:new,old"


def test_a_failed_run_does_not_fall_back_to_an_older_success(mocker, tmp_path: Path):
    now = datetime(2026, 11, 1, 21, tzinfo=UTC)
    receipt = tmp_path / "sources.json"
    receipt.write_text(json.dumps({"sources": {"pai": {"last_success_at": (now - timedelta(hours=11)).isoformat()}}}))
    mocker.patch.object(backup_alerts, "SOURCES_RECEIPT", receipt)
    mocker.patch.object(backup_external, "list_external_sources", return_value=[
        {"id": "pai", "name": "pai", "owner_project": "portfolio-ai", "kind": "guest_unit",
         "target": "portfolio-backup.service", "frequency": "weekly", "enabled": True}])
    mocker.patch.object(backup_external, "probe", lambda source: {
        "last_success_at": None, "last_status": "failed", "last_error": "last run ended exit-code (exit 1)"})
    assert not backup_alerts.external_statuses(now)["pai"]["ok"]
