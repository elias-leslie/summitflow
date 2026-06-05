"""Tests for the Hatchet retention guard."""

from __future__ import annotations

import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def test_parse_hatchet_duration_strings() -> None:
    from app.tasks.hatchet_retention import _parse_duration_hours

    assert _parse_duration_hours("720h") == 720
    assert _parse_duration_hours("1h30m") == 1.5
    assert _parse_duration_hours("45m") == 0.75
    assert _parse_duration_hours("") is None
    assert _parse_duration_hours("30d") is None


def test_create_hatchet_retention_backup_uses_pg_env_not_password_arg(
    mocker,
    tmp_path: Path,
) -> None:
    from app.tasks.hatchet_retention import create_hatchet_retention_backup

    calls: dict[str, Any] = {}

    def fake_run(args, **kwargs):
        calls["args"] = args
        calls["kwargs"] = kwargs
        Path(args[-1]).write_bytes(b"dump")
        return subprocess.CompletedProcess(args, 0, "", "")

    mocker.patch("app.tasks.hatchet_retention.safe_subprocess.run", side_effect=fake_run)

    result = create_hatchet_retention_backup(
        conninfo="host=localhost port=5432 dbname=hatchet user=admin password=test-secret",
        backup_dir=tmp_path,
    )

    args = calls["args"]
    assert isinstance(args, list)
    assert "test-secret" not in " ".join(str(arg) for arg in args)
    kwargs = calls["kwargs"]
    assert isinstance(kwargs, dict)
    env = kwargs["env"]
    assert env["PGDATABASE"] == "hatchet"
    assert env["PGPASSWORD"] == "test-secret"
    assert result["size_bytes"] == 4
    assert Path(result["path"]).exists()


def test_run_hatchet_retention_guard_backs_up_before_deleting(mocker, tmp_path: Path) -> None:
    from app.tasks import hatchet_retention

    calls: list[str] = []
    target_names = {target.name for target in hatchet_retention.RETENTION_TABLES}
    mocker.patch.object(hatchet_retention, "_hatchet_conninfo", return_value="dbname=hatchet")
    mocker.patch.object(
        hatchet_retention,
        "_get_hatchet_context",
        return_value=(
            target_names,
            {"retention_hours": 720, "periods": ["720h"], "source": "hatchet_tenant"},
            720.0,
        ),
    )
    mocker.patch.object(
        hatchet_retention,
        "create_hatchet_retention_backup",
        side_effect=lambda **_kwargs: calls.append("backup")
        or {"path": str(tmp_path / "hatchet.dump"), "size_bytes": 1},
    )

    def fake_cleanup(_conninfo, _targets, _cutoff, *, batch_size, dry_run):
        calls.append("cleanup")
        assert batch_size == hatchet_retention.DEFAULT_BATCH_SIZE
        assert dry_run is False
        return {
            "v1_task_events_olap": {"deleted": 5},
            "v1_statuses_olap": {"deleted": 0},
            "v1_lookup_table_olap": {"deleted": 0},
            "v1_lookup_table": {"deleted": 3},
        }

    mocker.patch.object(hatchet_retention, "_cleanup_existing_tables", side_effect=fake_cleanup)
    mocker.patch.object(
        hatchet_retention,
        "_vacuum_tables",
        side_effect=lambda *_args: calls.append("vacuum") or {"v1_task_events_olap": {}},
    )
    record_run = mocker.patch.object(
        hatchet_retention.maintenance_store,
        "record_maintenance_run",
    )

    result = hatchet_retention.run_hatchet_retention_guard(
        backup_dir=tmp_path,
        now=datetime(2026, 6, 5, tzinfo=UTC),
    )

    assert calls == ["backup", "cleanup", "vacuum"]
    assert result["status"] == "success"
    assert result["total_deleted"] == 8
    assert result["cutoff"].startswith("2026-05-06T")
    record_run.assert_called_once()
    assert record_run.call_args.args[:2] == ("hatchet_retention_guard", "success")
    assert record_run.call_args.kwargs["rows_cleaned"] == 8


def test_run_hatchet_retention_guard_dry_run_skips_backup_vacuum_and_record(mocker) -> None:
    from app.tasks import hatchet_retention

    target_names = {target.name for target in hatchet_retention.RETENTION_TABLES}
    mocker.patch.object(hatchet_retention, "_hatchet_conninfo", return_value="dbname=hatchet")
    mocker.patch.object(
        hatchet_retention,
        "_get_hatchet_context",
        return_value=(
            target_names,
            {"retention_hours": 720, "periods": ["720h"], "source": "hatchet_tenant"},
            720.0,
        ),
    )
    backup = mocker.patch.object(hatchet_retention, "create_hatchet_retention_backup")
    vacuum = mocker.patch.object(hatchet_retention, "_vacuum_tables")
    record_run = mocker.patch.object(
        hatchet_retention.maintenance_store,
        "record_maintenance_run",
    )

    def fake_cleanup(_conninfo, _targets, _cutoff, *, batch_size, dry_run):
        assert batch_size == 100
        assert dry_run is True
        return {"v1_task_events_olap": {"expired_before": 10, "deleted": 0}}

    mocker.patch.object(hatchet_retention, "_cleanup_existing_tables", side_effect=fake_cleanup)

    result = hatchet_retention.run_hatchet_retention_guard(dry_run=True, batch_size=100)

    assert result["dry_run"] is True
    assert result["total_deleted"] == 0
    backup.assert_not_called()
    vacuum.assert_not_called()
    record_run.assert_not_called()
