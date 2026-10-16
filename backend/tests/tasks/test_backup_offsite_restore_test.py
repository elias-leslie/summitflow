"""Monthly offsite restore test: selection, dump parsing, evidence and alerting."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from app.tasks import backup_offsite_restore_test as monthly

DUMP = """--
-- PostgreSQL database dump
--
CREATE TABLE public.messages (id integer);
ALTER TABLE public.messages OWNER TO neri;
CREATE POLICY own_rows ON public.messages TO neri_app USING (true);
GRANT SELECT ON TABLE public.messages TO neri_reader, PUBLIC;
ALTER DEFAULT PRIVILEGES FOR ROLE neri IN SCHEMA public GRANT SELECT ON TABLES TO neri_reader;
COPY public.messages (id) FROM stdin;
1
2
3
\\.
COPY public."Empty Table" (id) FROM stdin;
\\.
COPY public.notes (body) FROM stdin;
GRANT looks like DDL but is data TO intruder;
\\.
"""


def _point(backup_id: str, *, has_db: bool, size: int = 1024, kind: str = "directory") -> dict:
    return {
        "id": backup_id, "status": "completed", "created_at": "2026-10-11T00:00:00+00:00", "size_bytes": size,
        "verification_json": {"format": "restic-v1", "has_db": has_db, "snapshot_id": "a" * 64, "remote_snapshot_id": "b" * 64,
                              "offsite": {"status": "verified"}, "capture": {"kind": kind}, "logical_bytes": size},
    }


def test_dump_row_counts_and_roles_read_copy_blocks_without_treating_data_as_ddl(tmp_path: Path) -> None:
    dump = tmp_path / "database.sql"
    dump.write_text(DUMP)
    assert monthly.dump_row_counts(dump) == {"public.messages": 3, "public.Empty Table": 0, "public.notes": 1}
    assert monthly._dump_roles(dump) == ["neri", "neri_app", "neri_reader"]


def test_truncated_copy_block_is_rejected(tmp_path: Path) -> None:
    dump = tmp_path / "database.sql"
    dump.write_text("COPY public.messages (id) FROM stdin;\n1\n")
    with pytest.raises(RuntimeError, match="inside a COPY block"):
        monthly.dump_row_counts(dump)


def test_restore_verified_needs_a_recent_passing_drill() -> None:
    now = datetime(2026, 10, 11, tzinfo=UTC)
    assert monthly.restore_verified({"last_drill_ok": True, "last_drill_at": now - timedelta(days=30)}, now=now)
    assert not monthly.restore_verified({"last_drill_ok": True, "last_drill_at": now - timedelta(days=40)}, now=now)
    assert not monthly.restore_verified({"last_drill_ok": False, "last_drill_at": now}, now=now)
    assert not monthly.restore_verified({}, now=now)


def test_rotation_picks_least_recently_drilled_small_file_and_database_sources(monkeypatch: pytest.MonkeyPatch) -> None:
    now = datetime(2026, 10, 11, tzinfo=UTC)
    sources = [
        {"id": "infrastructure", "enabled": True, "path": "/srv"},
        {"id": "guest", "enabled": True, "path": "proxmox://h/qemu/1"},
        {"id": "off", "enabled": False, "path": "/x"},
        {"id": "files-recent", "enabled": True, "path": "/a", "last_drill_at": now},
        {"id": "files-old", "enabled": True, "path": "/b", "last_drill_at": now - timedelta(days=60)},
        {"id": "huge", "enabled": True, "path": "/c"},
        {"id": "db-never", "enabled": True, "path": "/d"},
        {"id": "db-recent", "enabled": True, "path": "/e", "last_drill_at": now},
    ]
    points = {
        "infrastructure": _point("i", has_db=True), "guest": _point("g", has_db=False), "off": _point("o", has_db=False),
        "files-recent": _point("fr", has_db=False), "files-old": _point("fo", has_db=False),
        "huge": _point("h", has_db=False, size=monthly.MAX_RESTORE_BYTES + 1),
        "db-never": _point("dn", has_db=True), "db-recent": _point("dr", has_db=True),
    }
    monkeypatch.setattr(monthly, "_offsite_point", lambda source_id: points[source_id])
    selected = monthly.select_rotation(sources)
    assert [(source["id"], point["id"]) for source, point in selected] == [("files-old", "fo"), ("db-never", "dn")]


def test_offsite_point_skips_unverified_and_guest_streams(monkeypatch: pytest.MonkeyPatch) -> None:
    pending = _point("pending", has_db=False)
    pending["verification_json"]["offsite"] = {"status": "pending"}
    pending["created_at"] = "2026-10-12T00:00:00+00:00"
    stream = _point("stream", has_db=False, kind="proxmox-qemu")
    good = _point("good", has_db=False)
    monkeypatch.setattr(monthly.backup_store, "list_backups", lambda **_: ([pending, stream, good], 3))
    selected = monthly._offsite_point("x")
    assert selected is not None and selected["id"] == "good"


def test_failures_record_evidence_alert_once_and_retry_before_cadence(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(monthly, "RECEIPT", tmp_path / "monthly.json")
    source = {"id": "neri", "enabled": True, "path": "/n"}
    point = _point("bkp-n", has_db=True)
    monkeypatch.setattr(monthly.backup_store, "list_sources", lambda: [source])
    monkeypatch.setattr(monthly, "select_rotation", lambda _sources: [(source, point)])
    restore = MagicMock(side_effect=RuntimeError("restore failed"))
    monkeypatch.setattr(monthly, "restore_test_point", restore)
    merged, drills, alerts = [], [], MagicMock()
    monkeypatch.setattr(monthly.backup_store, "merge_backup_verification_json", lambda backup_id, update: merged.append((backup_id, update)))
    monkeypatch.setattr(monthly.backup_store, "update_source_drill_result", lambda **kwargs: drills.append(kwargs))
    monkeypatch.setattr(monthly, "create_notification", alerts)

    first = monthly.run_monthly_offsite_restore_test()
    assert first["status"] == "failed" and drills[-1]["ok"] is False and merged[-1][1]["isolated_restore"]["ok"] is False
    assert alerts.call_count == 1
    source["last_drill_ok"] = False
    second = monthly.run_monthly_offsite_restore_test()  # A failure does not satisfy the cadence.
    assert second["status"] == "failed" and alerts.call_count == 1

    restore.side_effect = None
    restore.return_value = {"ok": True, "method": monthly.METHOD}
    assert monthly.run_monthly_offsite_restore_test()["status"] == "verified" and drills[-1]["ok"] is True
    assert monthly.run_monthly_offsite_restore_test()["status"] == "skipped"
    assert monthly.run_monthly_offsite_restore_test(force=True)["status"] == "verified"


def test_restore_test_point_rebuilds_the_captured_repository_from_its_bundle(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import shutil
    import subprocess
    from contextlib import contextmanager

    from app.tasks import backup_native_archive as archive
    from app.tasks import backup_native_recovery as recovery
    from app.tasks import backup_repository_runtime as runtime
    from app.tasks import backup_restic

    project = tmp_path / "project"
    project.mkdir()
    for command in (("init", "-b", "main"), ("config", "user.name", "Fixture"), ("config", "user.email", "fixture@example.invalid")):
        subprocess.run(["git", "-C", str(project), *command], check=True, capture_output=True)
    for value in ("one", "two"):
        (project / "work.txt").write_text(value)
        subprocess.run(["git", "-C", str(project), "add", "work.txt"], check=True, capture_output=True)
        subprocess.run(["git", "-C", str(project), "commit", "-qm", value], check=True, capture_output=True)
    snapshot, _ = recovery.build_consistent_snapshot(project, tmp_path / "stage", (".git",), archive._should_exclude, git_history_mode="full")

    class Adapter:
        def __init__(self, _config):
            pass

        def restore(self, _snapshot_id, target, **_options):
            shutil.copytree(snapshot, target / "payload")
            return {"payload_root": str(target / "payload")}

    @contextmanager
    def scratch_dir(_prefix, **_options):
        path = tmp_path / "scratch"
        path.mkdir()
        yield path

    monkeypatch.setattr(backup_restic, "ResticAdapter", Adapter)
    monkeypatch.setattr(backup_restic.ResticConfig, "from_env", staticmethod(lambda _env: object()))
    for name in ("_approved_key_directory", "_assert_repository_identity"):
        monkeypatch.setattr(runtime, name, lambda *_args, **_kwargs: None)
    monkeypatch.setattr(runtime, "_backup_environment", lambda _point: {})
    monkeypatch.setattr(runtime, "_known_restore_bytes", lambda _point: 1024)
    monkeypatch.setattr(monthly, "restore_scratch", scratch_dir)
    evidence = monthly.restore_test_point({"id": "project"}, _point("backup", has_db=False))
    assert evidence["ok"] is True
    assert evidence["git_history"]["source"] == "full" and evidence["git_history"]["commit_count"] == 2
