"""Freshness of backups other projects run: systemd unit and artifact probes, and the receipt merge."""

from __future__ import annotations

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


def test_external_sources_join_the_receipt_with_the_same_window(mocker):
    now = datetime(2026, 10, 17, 12, tzinfo=UTC)
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
