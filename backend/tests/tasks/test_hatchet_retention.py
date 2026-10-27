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
        "_reap_stale_workers",
        side_effect=lambda *_args, **_kwargs: calls.append("reap") or {"workers_deactivated": 2},
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

    assert calls == ["reap", "backup", "cleanup", "vacuum"]
    assert result["status"] == "success"
    assert result["stale_workers"] == {"workers_deactivated": 2}
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
    reap = mocker.patch.object(hatchet_retention, "_reap_stale_workers", return_value={})
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
    assert reap.call_args.kwargs["dry_run"] is True
    backup.assert_not_called()
    vacuum.assert_not_called()
    record_run.assert_not_called()


class _FakeCursor:
    def __init__(self, statements: list[tuple[str, Any]]) -> None:
        self.statements = statements
        self.rowcount = 0

    def __enter__(self) -> _FakeCursor:
        return self

    def __exit__(self, *_exc: object) -> None:
        return None

    def execute(self, query: str, params: Any = None) -> None:
        self.statements.append((" ".join(query.split()), params))
        self.rowcount = 7 if query.lstrip().startswith("UPDATE") else 3

    def fetchone(self) -> tuple[int]:
        return (11,)


class _FakeConn:
    def __init__(self) -> None:
        self.statements: list[tuple[str, Any]] = []
        self.committed = False

    def __enter__(self) -> _FakeConn:
        return self

    def __exit__(self, *_exc: object) -> None:
        return None

    def cursor(self) -> _FakeCursor:
        return _FakeCursor(self.statements)

    def commit(self) -> None:
        self.committed = True


def test_reap_stale_workers_deactivates_and_drops_only_expired_leases(mocker) -> None:
    from app.tasks import hatchet_retention

    conn = _FakeConn()
    mocker.patch.object(hatchet_retention.psycopg, "connect", return_value=conn)

    result = hatchet_retention._reap_stale_workers(
        "dbname=hatchet", stale_after_seconds=3600, dry_run=False
    )

    writes = [sql for sql, _ in conn.statements if not sql.startswith("SET")]
    assert writes[0].startswith('UPDATE "Worker" w SET "isActive" = false WHERE w."isActive"')
    assert writes[1].startswith('DELETE FROM "Lease" l')
    assert "l.\"kind\" = 'WORKER'" in writes[1]
    assert 'l."expiresAt" < NOW()' in writes[1]
    assert all(params == {"stale_after_seconds": 3600} for sql, params in conn.statements if not sql.startswith("SET"))
    assert conn.committed
    assert result["workers_deactivated"] == 7
    assert result["leases_deleted"] == 3


def test_reap_stale_workers_dry_run_only_counts(mocker) -> None:
    from app.tasks import hatchet_retention

    conn = _FakeConn()
    mocker.patch.object(hatchet_retention.psycopg, "connect", return_value=conn)

    result = hatchet_retention._reap_stale_workers(
        "dbname=hatchet", stale_after_seconds=3600, dry_run=True
    )

    writes = [sql for sql, _ in conn.statements if not sql.startswith("SET")]
    assert all(sql.startswith("SELECT count(*)") for sql in writes)
    assert result["stale_active_workers"] == 11
    assert result["stale_worker_leases"] == 11
    assert result["workers_deactivated"] == 0
    assert result["leases_deleted"] == 0


def test_existing_target_names_only_selects_plain_unpartitioned_tables(mocker) -> None:
    from app.tasks import hatchet_retention

    cur = mocker.MagicMock()
    cur.fetchall.return_value = [("v1_lookup_table",)]

    assert hatchet_retention._existing_target_names(cur) == {"v1_lookup_table"}

    sql = cur.execute.call_args.args[0]
    assert "relkind = 'r'" in sql
    assert "NOT c.relispartition" in sql
