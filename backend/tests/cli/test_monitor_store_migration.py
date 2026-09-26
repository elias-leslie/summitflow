"""Isolated conversion and lifecycle tests for the monitor SQLite page migration."""

import fcntl
import json
import sqlite3
from contextlib import closing
from pathlib import Path

import pytest

from cli.lib import monitor_store_migration as migration
from cli.lib import service_ops, service_release


def legacy_store(state: Path) -> Path:
    state.mkdir(mode=0o700, parents=True)
    db = state / "monitor.sqlite3"
    with closing(sqlite3.connect(db)) as conn:
        conn.execute("PRAGMA page_size=1024")
        conn.execute("PRAGMA auto_vacuum=INCREMENTAL")
        conn.execute("VACUUM")
        assert conn.execute("PRAGMA journal_mode=WAL").fetchone() == ("wal",)
        conn.execute("PRAGMA synchronous=FULL")
        conn.executescript("""
            CREATE TABLE meta(key TEXT PRIMARY KEY,value TEXT NOT NULL);
            CREATE TABLE samples(id INTEGER PRIMARY KEY,process_blob BLOB NOT NULL);
            CREATE TABLE events(id INTEGER PRIMARY KEY,details_json TEXT NOT NULL);
            CREATE TABLE host_rollups(bucket_start_ns INTEGER PRIMARY KEY,values_json TEXT NOT NULL);
            INSERT INTO meta VALUES('schema_version','1');
            INSERT INTO samples VALUES(10,x'0001ff');
            INSERT INTO events VALUES(20,'{"kind":"test"}');
            INSERT INTO host_rollups VALUES(30,'{"cpu":1}');
        """)
    db.chmod(0o600)
    return db


def test_legacy_wal_store_converts_with_verified_retained_backup(tmp_path: Path) -> None:
    state = tmp_path / "monitor"
    db = legacy_store(state)
    result = migration.migrate_stopped_store(state)
    assert result.status == "converted_restart_pending"
    assert result.receipt is not None
    receipt = json.loads(result.receipt.read_text())
    assert receipt["status"] == "converted_restart_pending"
    assert not (state / "migration.interlock").exists()
    assert receipt["before"] == receipt["after"]
    backup = Path(receipt["backup"])
    assert backup.exists() and backup.stat().st_mode & 0o077 == 0
    with sqlite3.connect(db) as conn:
        assert conn.execute("PRAGMA page_size").fetchone() == (512,)
        assert conn.execute("PRAGMA auto_vacuum").fetchone() == (2,)
        assert conn.execute("PRAGMA journal_mode").fetchone() == ("wal",)
        assert conn.execute("SELECT process_blob FROM samples").fetchone() == (b"\0\1\xff",)
    with sqlite3.connect(backup) as conn:
        assert conn.execute("PRAGMA page_size").fetchone() == (1024,)
        assert conn.execute("SELECT process_blob FROM samples").fetchone() == (b"\0\1\xff",)
    assert migration.migrate_stopped_store(state).status == "converted_restart_pending"
    migration.update_restart_receipt(result.receipt, status="succeeded")
    assert migration.migrate_stopped_store(state).status == "already_current"


def test_artifact_parent_is_synced_before_conversion(tmp_path: Path, monkeypatch) -> None:
    state = tmp_path / "monitor"
    legacy_store(state)
    synced = []
    real_sync = migration._fsync_dir

    def record(path):
        synced.append(path)
        real_sync(path)

    monkeypatch.setattr(migration, "_fsync_dir", record)
    assert migration.migrate_stopped_store(state).status == "converted_restart_pending"
    assert state / "migrations" in synced
    assert synced.index(state / "migrations") < synced.index(state / "migrations" / next(
        path.name for path in (state / "migrations").iterdir()
    ))


def test_active_managed_reader_defers_without_touching_database(tmp_path: Path) -> None:
    state = tmp_path / "monitor"
    db = legacy_store(state)
    lock = state / "maintenance.lock"
    with lock.open("w") as stream:
        lock.chmod(0o600)
        fcntl.flock(stream, fcntl.LOCK_SH | fcntl.LOCK_NB)
        with pytest.raises(migration.MonitorMigrationDeferred, match="maintenance lock is active"):
            migration.migrate_stopped_store(state)
    with sqlite3.connect(db) as conn:
        assert conn.execute("PRAGMA page_size").fetchone() == (1024,)
    assert not (state / "migrations").exists()


def test_other_collector_blocks_migration_before_database_access(tmp_path: Path) -> None:
    state = tmp_path / "monitor"
    db = legacy_store(state)
    lock = state / "collector.lock"
    with lock.open("w") as stream:
        lock.chmod(0o600)
        fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(migration.MonitorMigrationDeferred, match="collector lock is active"):
            migration.migrate_stopped_store(state)
    with sqlite3.connect(db) as conn:
        assert conn.execute("PRAGMA page_size").fetchone() == (1024,)
    assert not (state / "migrations").exists()


def test_existing_interlock_requires_recovery_even_if_page_is_current(tmp_path: Path) -> None:
    state = tmp_path / "monitor"
    legacy_store(state)
    (state / "migration.interlock").write_text("/retained/receipt.json\n")
    with pytest.raises(migration.MonitorMigrationFailed, match="manual recovery"):
        migration.migrate_stopped_store(state)


def test_pending_recovery_remains_hard_failure_if_interlock_write_fails(
    tmp_path: Path, monkeypatch,
) -> None:
    state = tmp_path / "monitor"
    legacy_store(state)
    result = migration.migrate_stopped_store(state)
    assert result.receipt is not None
    receipt = json.loads(result.receipt.read_text())
    receipt["after"]["samples"]["count"] += 1
    result.receipt.write_text(json.dumps(receipt))

    def fail_marker(_state, _receipt):
        raise OSError("injected no space")

    monkeypatch.setattr(migration, "retain_restart_interlock", fail_marker)
    with pytest.raises(migration.MonitorMigrationFailed, match="interlock could not be written"):
        migration.migrate_stopped_store(state)


def test_insufficient_space_defers_before_backup(tmp_path: Path, monkeypatch) -> None:
    state = tmp_path / "monitor"
    db = legacy_store(state)
    usage = migration.shutil.disk_usage(state)
    monkeypatch.setattr(migration.shutil, "disk_usage", lambda _: usage._replace(free=0))
    with pytest.raises(migration.MonitorMigrationDeferred, match="insufficient free space"):
        migration.migrate_stopped_store(state)
    with sqlite3.connect(db) as conn:
        assert conn.execute("PRAGMA page_size").fetchone() == (1024,)
    assert not (state / "migrations").exists()


def test_post_mutation_failure_keeps_backup_and_records_stop(tmp_path: Path, monkeypatch) -> None:
    state = tmp_path / "monitor"
    legacy_store(state)
    real_fingerprint = migration._fingerprint
    calls = 0

    def fail_after_vacuum(conn):
        nonlocal calls
        calls += 1
        if calls == 3:
            raise ValueError("injected verification failure")
        return real_fingerprint(conn)

    monkeypatch.setattr(migration, "_fingerprint", fail_after_vacuum)
    with pytest.raises(migration.MonitorMigrationFailed, match="retained backup"):
        migration.migrate_stopped_store(state)
    receipts = list((state / "migrations").glob("*/receipt.json"))
    assert len(receipts) == 1
    receipt = json.loads(receipts[0].read_text())
    assert receipt["status"] == "failed_after_mutation"
    assert Path(receipt["backup"]).exists()
    assert (state / "migration.interlock").exists()


def test_interlock_fsync_failure_is_hard_not_deferred(tmp_path: Path, monkeypatch) -> None:
    state = tmp_path / "monitor"
    legacy_store(state)
    real_sync = migration._fsync_dir

    def fail_after_marker(path):
        if path == state and (state / "migration.interlock").exists():
            raise OSError("injected interlock fsync failure")
        real_sync(path)

    monkeypatch.setattr(migration, "_fsync_dir", fail_after_marker)
    with pytest.raises(migration.MonitorMigrationFailed, match="retained backup"):
        migration.migrate_stopped_store(state)
    assert (state / "migration.interlock").exists()
    receipt = next((state / "migrations").glob("*/receipt.json"))
    assert Path(json.loads(receipt.read_text())["backup"]).exists()


def test_pending_restart_refuses_changed_store_and_retains_interlock(tmp_path: Path) -> None:
    state = tmp_path / "monitor"
    db = legacy_store(state)
    result = migration.migrate_stopped_store(state)
    assert result.status == "converted_restart_pending"
    with sqlite3.connect(db) as conn:
        conn.execute("INSERT INTO events VALUES(99,'changed')")
    with pytest.raises(migration.MonitorMigrationFailed, match="no longer matches"):
        migration.migrate_stopped_store(state)
    assert (state / "migration.interlock").exists()


def _managed_project(root: Path) -> service_ops.ProjectServices:
    return service_ops.ProjectServices(
        project_id="summitflow", root=root, backend_service="backend.service",
        frontend_service="frontend.service",
        default_workers=("summitflow-host-monitor.service",), optional_workers=(),
        backend_port=8001, frontend_port=3001, backend_dir=root / "backend",
        frontend_dir=root / "frontend", health_endpoint="/health",
    )


def test_managed_migration_requires_prior_live_reader_release(tmp_path: Path, monkeypatch) -> None:
    live = tmp_path / "live"
    reader = live / "backend/monitor_reader/reader.py"
    reader.parent.mkdir(parents=True)
    reader.write_text("# old release has no lock\n")
    monkeypatch.setattr(service_release, "current_source_root", lambda _project: live)
    stops = []
    monkeypatch.setattr(service_ops, "run", lambda command: stops.append(command) or 0)
    with pytest.raises(service_ops.ServiceError, match="deploy the monitor reader lock"):
        service_ops.migrate_host_monitor_store(_managed_project(tmp_path))
    assert stops == []


def test_running_backend_release_attestation_uses_process_cwd(tmp_path: Path) -> None:
    proc = tmp_path / "proc"
    release = tmp_path / "release"
    (release / "backend").mkdir(parents=True)
    (proc / "42").mkdir(parents=True)
    (proc / "42" / "cwd").symlink_to(release / "backend")
    assert service_ops._backend_process_release_root(42, proc_root=proc) == release
    with pytest.raises(service_ops.ServiceError, match="cannot attest"):
        service_ops._backend_process_release_root(43, proc_root=proc)


def test_stale_backend_process_blocks_before_collector_stop(tmp_path: Path, monkeypatch) -> None:
    live = tmp_path / "live"
    reader = live / "backend/monitor_reader/reader.py"
    reader.parent.mkdir(parents=True)
    reader.write_text("MONITOR_MAINTENANCE_LOCK_VERSION = 2\n")
    monkeypatch.setattr(service_release, "current_source_root", lambda _project: live)
    monkeypatch.setattr(service_ops, "_service_main_pid", lambda _service: 42)
    monkeypatch.setattr(service_ops, "_backend_process_release_root", lambda _pid: tmp_path / "stale")
    stops = []
    monkeypatch.setattr(service_ops, "run", lambda command: stops.append(command) or 0)
    with pytest.raises(service_ops.ServiceError, match="running backend has not loaded"):
        service_ops.migrate_host_monitor_store(_managed_project(tmp_path))
    assert stops == []


@pytest.mark.parametrize("active", [True, False])
def test_converted_store_starts_collector_before_reporting_success(
    tmp_path: Path, monkeypatch, active: bool,
) -> None:
    live = tmp_path / "live"
    reader = live / "backend/monitor_reader/reader.py"
    reader.parent.mkdir(parents=True)
    reader.write_text("MONITOR_MAINTENANCE_LOCK_VERSION = 2\n")
    monkeypatch.setattr(service_release, "current_source_root", lambda _project: live)
    monkeypatch.setattr(service_ops, "_service_main_pid", lambda _service: 42)
    monkeypatch.setattr(service_ops, "_backend_process_release_root", lambda _pid: live)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    state = tmp_path / ".local/state/summitflow/monitor"
    db = legacy_store(state)
    monkeypatch.setattr(service_ops, "service_exists", lambda _service: True)
    monkeypatch.setattr(service_ops, "_wait_service_inactive", lambda _service: True)
    monkeypatch.setattr(service_ops, "_wait_service_active", lambda _service: active)
    commands = []
    monkeypatch.setattr(service_ops, "run", lambda command: commands.append(command) or 0)
    if active:
        result = service_ops.migrate_host_monitor_store(_managed_project(tmp_path))
        assert result.status == "migrated"
        assert result.receipt is not None
        assert json.loads(result.receipt.read_text())["status"] == "succeeded"
        assert not (state / "migration.interlock").exists()
    else:
        with pytest.raises(service_ops.ServiceError, match="did not become active"):
            service_ops.migrate_host_monitor_store(_managed_project(tmp_path))
        receipt = next((state / "migrations").glob("*/receipt.json"))
        assert json.loads(receipt.read_text())["status"] == "collector_restart_failed"
        assert (state / "migration.interlock").exists()
        assert commands[-1][-2:] == ["stop", "summitflow-host-monitor.service"]
    assert commands[0][-2:] == ["stop", "summitflow-host-monitor.service"]
    assert commands[1][-2:] == ["start", "summitflow-host-monitor.service"]
    with sqlite3.connect(db) as conn:
        assert conn.execute("PRAGMA page_size").fetchone() == (512,)


@pytest.mark.parametrize("failure,deferred", [
    (migration.MonitorMigrationDeferred("reader busy"), True),
    (migration.MonitorMigrationFailed("conversion failed"), False),
])
def test_managed_migration_resumes_only_pre_mutation_failure(
    tmp_path: Path, monkeypatch, failure: Exception, deferred: bool,
) -> None:
    live = tmp_path / "live"
    reader = live / "backend/monitor_reader/reader.py"
    reader.parent.mkdir(parents=True)
    reader.write_text("MONITOR_MAINTENANCE_LOCK_VERSION = 2\n")
    monkeypatch.setattr(service_release, "current_source_root", lambda _project: live)
    monkeypatch.setattr(service_ops, "_service_main_pid", lambda _service: 42)
    monkeypatch.setattr(service_ops, "_backend_process_release_root", lambda _pid: live)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    state = tmp_path / ".local/state/summitflow/monitor"
    state.mkdir(parents=True)
    (state / "monitor.sqlite3").touch()
    monkeypatch.setattr(service_ops, "service_exists", lambda _service: True)
    monkeypatch.setattr(service_ops, "_wait_service_inactive", lambda _service: True)
    monkeypatch.setattr(service_ops, "_wait_service_active", lambda _service: True)
    commands = []
    monkeypatch.setattr(service_ops, "run", lambda command: commands.append(command) or 0)
    monkeypatch.setattr(service_ops, "migrate_stopped_store", lambda _state: (_ for _ in ()).throw(failure))
    if deferred:
        assert service_ops.migrate_host_monitor_store(_managed_project(tmp_path)).status == "deferred"
        assert len(commands) == 2 and commands[1][-2:] == ["start", "summitflow-host-monitor.service"]
    else:
        with pytest.raises(service_ops.ServiceError, match="conversion failed"):
            service_ops.migrate_host_monitor_store(_managed_project(tmp_path))
        assert len(commands) == 1 and commands[0][-2:] == ["stop", "summitflow-host-monitor.service"]
