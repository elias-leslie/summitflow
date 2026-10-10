"""Native receipts prove independent artifacts, not a boot/DB restore drill."""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import Mock

import pytest
from psycopg import OperationalError

from app.tasks import backup_btrbk as host
from app.tasks.backup_activity import BackupCancelled

NOW = datetime(2026, 10, 5, 12, tzinfo=UTC)


def test_enabled_reads_persistent_settings_and_respects_process_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("BACKUP_BTRBK_ENABLED", raising=False)
    monkeypatch.setattr(host, "get_settings", lambda: SimpleNamespace(backup_btrbk_enabled=True))
    assert host._enabled() is True
    monkeypatch.setenv("BACKUP_BTRBK_ENABLED", "false")
    assert host._enabled() is False


def test_configuration_inspection_does_not_create_operational_lock(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config = tmp_path / "btrbk.conf"
    config.write_text("\n".join(("snapshot_preserve_min latest", "snapshot_preserve no", "target_preserve_min latest", "target_preserve 7d", "snapshot_create ondemand")))
    lock = tmp_path / "operational.lock"
    monkeypatch.setattr(host, "CONFIG_PATH", config)
    original_lstat = Path.lstat
    def trusted_lstat(path: Path) -> Any:
        if path == config or path in config.parents:
            return SimpleNamespace(st_uid=0, st_mode=0o100644)
        return original_lstat(path)
    monkeypatch.setattr(Path, "lstat", trusted_lstat)
    def btrbk_list(args: list[str]) -> str:
        # Installed btrbk 0.32.5 opens its operational lock for list commands
        # too; --dry-run is the documented switch that prevents that mutation.
        if "--dry-run" not in args:
            lock.touch()
        return "\n".join(f"format=raw source_url={source} target_type=send-receive target_path=/independent" for source in host.REQUIRED_SOURCES)
    monkeypatch.setattr(host, "_checked", btrbk_list)
    assert len(host._configuration()) == len(host.REQUIRED_SOURCES)
    assert not lock.exists()


@pytest.mark.parametrize("autofs_first", [True, False])
def test_filesystem_resolves_stacked_automount_to_qualified_real_mount(monkeypatch: pytest.MonkeyPatch, autofs_first: bool) -> None:
    automount = {"target": "/mnt/native", "fstype": "autofs", "uuid": None, "fsroot": "/", "source": "systemd-1", "options": "rw"}
    mounted = {"target": "/mnt/native", "fstype": "btrfs", "uuid": "plain-target", "fsroot": "/", "source": "/dev/sda2", "options": "rw,compress=zstd:1"}
    rows = [automount, mounted] if autofs_first else [mounted, automount]
    monkeypatch.setattr(host, "_checked", lambda _: json.dumps({"filesystems": rows}))
    assert host._filesystem("/mnt/native/points") == mounted


def test_filesystem_never_selects_btrfs_behind_effective_non_btrfs_mount(monkeypatch: pytest.MonkeyPatch) -> None:
    ancestor = {"target": "/", "fstype": "btrfs", "uuid": "source"}
    mounted = {"target": "/mnt/native", "fstype": "ext4", "uuid": "other"}
    monkeypatch.setattr(host, "_checked", lambda _: json.dumps({"filesystems": [ancestor, mounted]}))
    assert host._filesystem("/mnt/native/points") == mounted
    monkeypatch.setattr(host, "_checked", lambda _: json.dumps({"filesystems": [mounted, {**mounted, "fstype": "btrfs"}]}))
    with pytest.raises(RuntimeError, match="Ambiguous"):
        host._filesystem("/mnt/native/points")


@pytest.fixture
def capture(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    root, target = tmp_path / "state", tmp_path / "independent" / "points"
    root.mkdir(mode=0o700)
    target.mkdir(parents=True)
    packages = tmp_path / "packages"
    packages.write_text("unchanged package inventory")
    monkeypatch.setattr(host, "PACKAGE_STATUS_PATH", packages)
    monkeypatch.setattr(host, "_state_root", lambda: root)
    monkeypatch.setenv("BACKUP_BTRBK_ENABLED", "true")
    rows = [{"source_url": "/", "target_path": str(target), "snapshot_path": "/snapshots"}]
    capacity = {"admitted": True, "used_bytes": 100, "free_bytes": 900, "expected_growth_bytes": 100, "target_filesystem_uuid": "independent-uuid"}
    monkeypatch.setattr(host, "native_host_status", lambda: {"ready": True, "last_result": host._receipt()})
    monkeypatch.setattr(host, "_configuration", lambda: rows)
    monkeypatch.setattr(host, "_validate_nested_coverage", lambda _: None)
    monkeypatch.setattr(host, "_capacity", lambda *_: capacity)
    monkeypatch.setattr(host, "_filesystem", lambda path: {"uuid": "source-fs" if path == "/" else "independent-uuid"})
    monkeypatch.setattr(host, "_boot_layout", lambda: {"disks": [{"device": "/dev/observed", "partition_layout": "fixture"}], "restore_verified": False})
    monkeypatch.setattr(host, "_database_manifests", lambda *_: {"status": "qualified", "manifests": [], "missing": []})
    point = {"source": "/", "snapshot": "/snapshots/current", "target": str(target / "current"), "source_uuid": "source-uuid", "received_uuid": "source-uuid"}
    Path(point["target"]).mkdir()
    monkeypatch.setattr(host, "_verified_points", lambda *_: [point])
    bulk = Mock(return_value=subprocess.CompletedProcess([], 0, "format=raw type=snapshot status=success source_url=/ target_url=/snapshots/current\n", ""))
    monkeypatch.setattr(host, "run_bulk_process", bulk)
    monkeypatch.setattr(host.shutil, "disk_usage", lambda _: SimpleNamespace(total=1000, used=110, free=890))
    calls: list[list[str]] = []
    fail = {"artifact": None, "delete": False}
    def checked(args: list[str], *, bulk: bool = False) -> str:
        calls.append(args)
        command = args[2:] if args[:2] == ["sudo", "-n"] else args
        name = command[0]
        destination = Path(command[-1])
        if name == "mkdir":
            destination.mkdir(parents=True, mode=0o700, exist_ok=True)
        elif name == "stat":
            if not destination.exists():
                raise RuntimeError("missing fixture artifact")
            return "0:700:directory" if destination.is_dir() else "0:600:regular file"
        elif name == "rsync":
            (destination / "kernel").write_bytes(b"fixture boot bytes")
        elif name == "install":
            if destination.name.startswith(str(fail["artifact"])):
                raise RuntimeError("fixture independent artifact copy failure")
            shutil.copyfile(command[-2], destination)
            destination.chmod(0o600)
        elif name == "sha256sum":
            return hashlib.sha256(destination.read_bytes()).hexdigest() + "  " + str(destination)
        elif name == "mv":
            Path(command[-2]).replace(destination)
        elif name == "sync":
            return ""
        elif name == "find":
            directory = Path(command[1])
            return "\n".join(str(path) for path in directory.iterdir() if path.is_dir())
        elif name == "cat":
            return destination.read_text()
        elif name == "rm":
            if fail["delete"]:
                raise RuntimeError("fixture deletion failure")
            if destination.is_dir():
                shutil.rmtree(destination)
            else:
                destination.unlink(missing_ok=True)
        elif name == "rmdir":
            destination.rmdir()
        elif name == "btrfs":
            return "ro=true" if "property" in command else "Received UUID: source-uuid\n"
        else:
            raise AssertionError(f"Unexpected fixture command: {args}")
        return ""
    monkeypatch.setattr(host, "_checked", checked)
    return {"root": root, "target": target, "rows": rows, "bulk": bulk, "calls": calls, "fail": fail, "checked": checked}


def test_completion_published_only_after_every_independent_artifact(capture: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:
    write = host._write_receipt
    statuses = []
    def observe(payload: dict[str, Any]) -> None:
        statuses.append(payload["status"])
        if payload["status"] == "completed":
            directory = Path(payload["boot_path"]).parent
            assert json.loads((directory / "capture.json").read_text())["status"] == "completed"
            assert all((directory / name).is_file() for name in ("journal.log", "layout.json", "database-manifests.json"))
            assert (directory / "boot" / "kernel").is_file()
        write(payload)
    monkeypatch.setattr(host, "_write_receipt", observe)
    result = host.run_native_host_backup(now=NOW)
    assert result["status"] == "completed"
    assert statuses == ["running", "running", "completed"]
    assert result["restore_verified"] is False
    assert json.loads((capture["root"] / "last-good.json").read_text())["run_id"] == result["run_id"]
    assert (capture["root"] / "receipts" / f"{result['run_id']}.json").is_file()


@pytest.mark.parametrize("artifact", ["journal.log", "layout.json", "database-manifests.json", "capture.json"])
def test_failed_target_metadata_never_publishes_local_completed_or_erases_last_good(capture: dict[str, Any], monkeypatch: pytest.MonkeyPatch, artifact: str) -> None:
    host._write_receipt({"status": "completed", "evidence": "previous successful recovery"})
    capture["fail"]["artifact"] = artifact
    write, statuses = host._write_receipt, []
    def observe(payload: dict[str, Any]) -> None:
        statuses.append(payload["status"])
        write(payload)
    monkeypatch.setattr(host, "_write_receipt", observe)
    result = host.run_native_host_backup(now=NOW)
    assert result["status"] == "failed"
    assert "completed" not in statuses
    assert json.loads((capture["root"] / "last-good.json").read_text())["evidence"] == "previous successful recovery"
    assert Path(result["evidence"]).is_file()
    assert Path(result["boot_path"]).exists()
    assert json.loads((capture["root"] / "receipts" / f"{result['run_id']}.json").read_text())["status"] == "failed"


def test_interrupted_capture_keeps_local_and_independent_failure_evidence(capture: dict[str, Any]) -> None:
    capture["bulk"].side_effect = BackupCancelled("fixture interruption")
    result = host.run_native_host_backup(now=NOW)
    assert result["status"] == "cancelled"
    assert "fixture interruption" in Path(result["evidence"]).read_text()
    assert json.loads((Path(result["boot_path"]).parent / "capture.json").read_text())["status"] == "cancelled"
    assert not (capture["root"] / "last-good.json").exists()


def test_catalogue_outage_keeps_failed_local_and_independent_capture_receipts(capture: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(host, "_database_manifests", Mock(side_effect=OperationalError("fixture catalogue outage")))
    result = host.run_native_host_backup(now=NOW)
    assert result["status"] == "failed"
    assert result["capture_complete"] is True
    assert host._receipt() == result
    assert json.loads((Path(result["boot_path"]).parent / "capture.json").read_text())["status"] == "failed"
    assert "fixture catalogue outage" in Path(result["evidence"]).read_text()
    assert not (capture["root"] / "last-good.json").exists()


def test_partial_database_association_finishes_without_another_host_capture(capture: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(host, "_database_manifests", lambda *_: {"status": "partial", "missing": [{"project_id": "nested-db"}]})
    partial = host.run_native_host_backup(now=NOW)
    assert partial["status"] == "partial"
    assert partial["reason"] == "database-recovery-incomplete"
    assert not (capture["root"] / "last-good.json").exists()
    monkeypatch.setattr(host, "_database_manifests", lambda *_: {"status": "qualified", "manifests": [{"project_id": "nested-db", "has_db": True}], "missing": []})
    # Association can finish outside the heavyweight host capture window.
    monkeypatch.setattr(host, "get_settings", lambda: SimpleNamespace(backup_schedule_timezone="UTC", backup_schedule_start_hour=2, backup_schedule_end_hour=6))
    result = host.run_scheduled_host_backup(NOW + timedelta(hours=1))
    assert result["status"] == "completed"
    assert result["run_id"] == partial["run_id"]
    capture["bulk"].assert_called_once()
    assert sum("rsync" in command for command in capture["calls"]) == 1
    assert len(list((capture["root"] / "receipts").glob("*.json"))) == 1


def test_disabled_and_daily_incomplete_never_start_capture(capture: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BACKUP_BTRBK_ENABLED", "false")
    assert host.run_scheduled_host_backup(NOW) == {"status": "skipped", "reason": "host-backup-disabled"}
    capture["bulk"].assert_not_called()
    monkeypatch.setenv("BACKUP_BTRBK_ENABLED", "true")
    monkeypatch.setattr(host, "get_settings", lambda: SimpleNamespace(backup_schedule_timezone="UTC", backup_schedule_start_hour=None, backup_schedule_end_hour=None))
    host._write_receipt({"status": "failed", "started_at": NOW.isoformat(), "evidence": "retained partial operation"})
    assert host.run_scheduled_host_backup(NOW)["reason"] == "daily-host-backup-incomplete"
    capture["bulk"].assert_not_called()


@pytest.mark.parametrize("fault", [None, "missing-source", "missing-transfer", "uuid", "writable"])
def test_required_current_received_point_is_qualified(monkeypatch: pytest.MonkeyPatch, fault: str | None) -> None:
    rows = [{"source_url": "/root", "target_path": "/independent"}]
    transactions = [{"type": "snapshot", "status": "success", "source_url": "/root", "target_url": "/snapshots/current"},
                    {"type": "send-receive", "status": "success", "source_url": "/snapshots/current", "target_url": "/independent/current"}]
    if fault == "missing-source":
        transactions.pop(0)
    if fault == "missing-transfer":
        transactions.pop()
    def checked(args: list[str]) -> str:
        if "property" in args:
            return "ro=false" if fault == "writable" else "ro=true"
        return "UUID: source\n" if args[-1] == "/snapshots/current" else "Received UUID: " + ("different" if fault == "uuid" else "source")
    monkeypatch.setattr(host, "_checked", checked)
    if fault:
        with pytest.raises(RuntimeError):
            host._verified_points(rows, transactions)
    else:
        assert host._verified_points(rows, transactions)[0]["received_uuid"] == "source"


def test_nested_coverage_exempts_only_canonical_managed_workpoints(monkeypatch: pytest.MonkeyPatch) -> None:
    rows = [{"source_url": "/workspaces", "snapshot_path": "/host-snapshots"}]
    monkeypatch.setattr(host, "get_workspaces_root", lambda: Path("/workspaces"))
    monkeypatch.setattr(host, "_filesystem", lambda _: {"fsroot": "/@workspaces"})
    monkeypatch.setattr(host, "_checked", lambda _: "ID 300 gen 1 top level 5 path @workspaces/.snapshots/project/point\n")
    host._validate_nested_coverage(rows)
    for nested in ("project/.snapshots/durable", "project/__snapshots/durable", "project/data"):
        monkeypatch.setattr(host, "_checked", lambda _, nested=nested: f"ID 301 gen 1 top level 5 path @workspaces/{nested}\n")
        with pytest.raises(RuntimeError, match="explicit host coverage"):
            host._validate_nested_coverage(rows)


def test_root_qualification_rejects_writable_or_symlink_metadata(monkeypatch: pytest.MonkeyPatch) -> None:
    for metadata in ("1000:700:directory", "0:777:directory", "0:700:symbolic link"):
        monkeypatch.setattr(host, "_checked", lambda _, metadata=metadata: metadata)
        with pytest.raises(RuntimeError, match="root-owned"):
            host._qualify_target_directory(Path("/independent/metadata"))


@pytest.mark.parametrize("live,failure,status", [(True, False, "completed"), (False, True, "completed"), (False, False, "failed"), (False, False, "completed")])
def test_boot_metadata_cleanup_follows_native_point_lifetime_and_retains_failed_catalogue(capture: dict[str, Any], live: bool, failure: bool, status: str) -> None:
    target = capture["target"]
    run_id = "20261004T120000Z-01234567"
    directory = target.parent / "summitflow-host-recovery" / "captures" / run_id
    (directory / "boot").mkdir(parents=True)
    (directory / "boot" / "kernel").write_bytes(b"matching kernel")
    point = target / "previous"
    if live:
        point.mkdir()
    payload = {"adapter": host.ADAPTER, "run_id": run_id, "status": status, "boot_path": str(directory / "boot"), "points": [{"target": str(point)}]}
    (directory / "capture.json").write_text(json.dumps(payload))
    host._write_receipt(payload)
    capture["fail"]["delete"] = failure
    result = host._cleanup_superseded(target, "20261005T120000Z-89abcdef")
    catalogue = capture["root"] / "receipts" / f"{run_id}.json"
    if not live and not failure and status == "completed":
        assert result["removed"] == [run_id]
        assert not directory.exists() and not catalogue.exists()
        assert json.loads((capture["root"] / "last-good.json").read_text())["point_availability"] == "expired"
    else:
        assert not result["removed"]
        assert catalogue.is_file() and (directory / "capture.json").is_file()
        assert (directory / "boot" / "kernel").is_file()
    assert bool(result["blockers"]) == failure
    assert result["reclaimed_bytes"] == 0  # Unchanged usage proves no invented savings.


@pytest.mark.parametrize("fault", [None, "has_db", "unverified", "row-unverified", "pending-check", "stale", "wrong-project", "wrong-source", "no-offsite", "missing-identity"])
def test_declared_nested_database_requires_fresh_matching_independent_manifest(monkeypatch: pytest.MonkeyPatch, fault: str | None) -> None:
    monkeypatch.setattr(host, "testing_project_ids", lambda: set())
    project = {"id": "canonical-project", "root_path": "/srv/workspaces/nested/project"}
    source = {"id": "source-alias", "project_id": "legacy-project", "source_type": "project", "frequency": "four_hourly"}
    verification = {"verified": True, "has_db": True, "verified_at": NOW.isoformat(), "format": "restic-v1", "repository_id": "local", "snapshot_id": "point", "remote_repository_id": "independent", "remote_snapshot_id": "remote-point", "offsite": {"status": "verified"}}
    record: dict[str, Any] = {"id": "db-recovery", "source_id": "source-alias", "project_id": "legacy-project", "status": "completed", "verified": True, "location": "restic:point", "started_at": (NOW - timedelta(hours=1)).isoformat(), "verification_json": verification}
    if fault == "has_db":
        verification["has_db"] = False
    elif fault == "unverified":
        verification["verified"] = False
    elif fault == "row-unverified":
        record["verified"] = False
    elif fault == "pending-check":
        verification["structural_check_pending"] = True
    elif fault == "stale":
        record["started_at"] = (NOW - timedelta(hours=5)).isoformat()
    elif fault == "wrong-project":
        record["project_id"] = "other-project"
    elif fault == "wrong-source":
        record["source_id"] = "other-source"
    elif fault == "no-offsite":
        verification["offsite"] = {"status": "pending"}
    elif fault == "missing-identity":
        verification.pop("remote_snapshot_id")
    monkeypatch.setattr(host, "list_projects", lambda: [project])
    monkeypatch.setattr(host.backup_store, "list_sources", lambda: [source])
    monkeypatch.setattr(host, "get_project_identity", lambda *_: {"project": {"id": "canonical-project"}, "database": {"shared_with": "canonical-db"}})
    monkeypatch.setattr(host, "_load_db_config", lambda *_: {"configured": "true", "host": "localhost", "port": "5432", "name": "canonical_db"})
    monkeypatch.setattr(host, "get_project_aliases", lambda *_: ("canonical-project", "legacy-project"))
    monkeypatch.setattr(host.backup_store, "list_backups", lambda **_: ([record], 1))
    result = host._database_manifests([{"source_url": "/srv/workspaces"}], NOW)
    assert result["status"] == ("partial" if fault else "qualified")
    if fault:
        assert result["missing"][0]["project_id"] == "canonical-project"
        assert not result["manifests"]
        if fault == "stale":
            # An out-of-window point never qualifies; the receipt names it.
            assert result["missing"][0]["reason"] == "verified-database-point-stale"
            assert result["missing"][0]["latest_verified_captured_at"] == (NOW - timedelta(hours=5)).astimezone(UTC).isoformat()
            assert result["missing"][0]["freshness_window_seconds"] == 4 * 3600
        else:
            assert result["missing"][0]["reason"] == "fresh-independent-verified-database-point-unavailable"
    else:
        assert result["manifests"][0]["backup_id"] == "db-recovery"
        assert result["manifests"][0]["restore_verified"] is False


@pytest.mark.parametrize("configuration", ["true", "false", "unresolved"])
def test_database_coverage_uses_capture_resolver_without_requiring_manifest_declaration(monkeypatch: pytest.MonkeyPatch, configuration: str) -> None:
    monkeypatch.setattr(host, "testing_project_ids", lambda: set())
    monkeypatch.setattr(host, "list_projects", lambda: [{"id": "legacy-project", "root_path": "/srv/workspaces/projects/canonical-project"}])
    monkeypatch.setattr(host.backup_store, "list_sources", lambda: [])
    monkeypatch.setattr(host, "get_project_identity", lambda *_: {"project": {"id": "canonical-project"}})
    monkeypatch.setattr(host, "get_project_aliases", lambda *_: ("canonical-project", "legacy-project"))

    def resolve(name: str, env: dict[str, str]) -> dict[str, str]:
        assert name == "canonical-project" and env == {"BACKUP_PROJECT_ID": "canonical-project"}
        if configuration == "unresolved":
            raise RuntimeError("Private resolver detail must not enter the receipt")
        return {"configured": configuration, "host": "localhost", "port": "5432", "name": "canonical_db", "password": "private-test-value"}

    monkeypatch.setattr(host, "_load_db_config", resolve)
    result = host._database_manifests([{"source_url": "/srv/workspaces"}], NOW)
    assert result["status"] == ("qualified" if configuration == "false" else "partial")
    assert not result["manifests"]
    if configuration != "false":
        assert result["missing"] == [{"project_id": "canonical-project", "reason": "database-configuration-unresolved" if configuration == "unresolved" else "fresh-independent-verified-database-point-unavailable", "source_ids": []}]
    assert "private" not in json.dumps(result).lower()


@pytest.mark.parametrize("category,enabled", [("testing", False), ("testing", None), ("testing", True), ("prod", False), (None, False)])
def test_only_explicitly_disabled_testing_database_policies_are_excluded(monkeypatch: pytest.MonkeyPatch, category: str | None, enabled: bool | None) -> None:
    # Production list_projects() deliberately omits category; use its canonical
    # testing registry query rather than inventing a field in the fixture.
    monkeypatch.setattr(host, "list_projects", lambda: [{"id": "project", "root_path": "/srv/workspaces/project"}])
    monkeypatch.setattr(host, "testing_project_ids", lambda: {"project"} if category == "testing" else set())
    source = {"id": "source", "project_id": "project", "source_type": "project", "enabled": enabled}
    monkeypatch.setattr(host.backup_store, "list_sources", lambda: [source])
    monkeypatch.setattr(host, "get_project_identity", lambda *_: {})
    monkeypatch.setattr(host, "get_project_aliases", lambda *_: ("project",))
    monkeypatch.setattr(host, "_load_db_config", lambda *_: {"configured": "true", "host": "localhost", "port": "5432", "name": "project"})
    monkeypatch.setattr(host.backup_store, "list_backups", lambda **_: ([], 0))
    result = host._database_manifests([{"source_url": "/srv/workspaces"}], NOW)
    excluded = category == "testing" and enabled is False
    assert result["status"] == ("qualified" if excluded else "partial")
    assert bool(result["excluded"]) is excluded
    assert bool(result["missing"]) is not excluded
    if excluded:
        assert result["excluded"][0]["portable_database_recovery_covered"] is False


@pytest.mark.parametrize("fault", [None, "host", "port", "name", "dump", "stale"])
def test_shared_database_association_requires_exact_endpoint_and_qualified_full_dump(monkeypatch: pytest.MonkeyPatch, fault: str | None) -> None:
    monkeypatch.setattr(host, "testing_project_ids", lambda: set())
    projects = [{"id": name, "root_path": f"/srv/workspaces/{name}"} for name in ("supplier", "legacy")]
    sources = [{"id": name, "project_id": name, "source_type": "project", "frequency": "daily" if name == "supplier" else "four_hourly"} for name in ("supplier", "legacy")]
    verification = {"verified": True, "has_db": True, "verified_at": NOW.isoformat(), "format": "restic-v1", "repository_id": "local", "snapshot_id": "point", "remote_repository_id": "remote", "remote_snapshot_id": "remote-point", "offsite": {"status": "verified"}, "capture": {"db_dump_name": "partial.sql" if fault == "dump" else ".summitflow-recovery/database.sql"}}
    record = {"id": "db-point", "source_id": "supplier", "project_id": "supplier", "status": "completed", "verified": True, "location": "restic:point", "started_at": (NOW - timedelta(hours=5 if fault == "stale" else 1)).isoformat(), "verification_json": verification}
    monkeypatch.setattr(host, "list_projects", lambda: projects)
    monkeypatch.setattr(host.backup_store, "list_sources", lambda: sources)
    monkeypatch.setattr(host, "get_project_identity", lambda *_: {})
    monkeypatch.setattr(host, "get_project_aliases", lambda project, *_: (project,))
    def resolve(name: str, _: dict[str, str]) -> dict[str, str]:
        config = {"configured": "true", "host": "localhost" if name == "supplier" else "127.0.0.1", "port": "5432", "name": "shared"}
        if name == "legacy" and fault in {"host", "port", "name"}:
            config[fault] = "different"
        return config
    monkeypatch.setattr(host, "_load_db_config", resolve)
    monkeypatch.setattr(host.backup_store, "list_backups", lambda source_id, **_: ([record], 1) if source_id == "supplier" else ([], 0))
    result = host._database_manifests([{"source_url": "/srv/workspaces"}], NOW)
    assert result["status"] == ("partial" if fault else "qualified")
    if fault:
        assert result["missing"][0]["project_id"] == "legacy"
    else:
        association = next(item for item in result["manifests"] if item["project_id"] == "legacy")
        assert association["database_point_project_id"] == "supplier" and association["backup_id"] == "db-point"
        assert association["restore_verified"] is False


@pytest.mark.parametrize("ready", [False, True])
def test_readiness_never_claims_restore_verified(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, ready: bool) -> None:
    monkeypatch.setattr(host, "_state_root", lambda: tmp_path)
    config = tmp_path / "qualified-config"
    config.write_text("fixture")
    monkeypatch.setattr(host, "CONFIG_PATH", config)
    monkeypatch.setattr(host.shutil, "which", lambda _: "/usr/bin/btrbk" if ready else None)
    monkeypatch.setattr(host, "_configuration", lambda: [{"source_url": "/", "target_path": "/independent/points"}])
    monkeypatch.setattr(host, "_validate_nested_coverage", lambda _: None)
    monkeypatch.setattr(host, "_qualify_target_directory", lambda _: None)
    monkeypatch.setattr(host, "_capacity", lambda *_: {"admitted": True, "reason": None})
    monkeypatch.setattr(host, "_run", lambda _: subprocess.CompletedProcess([], 0))
    result = host.native_host_status()
    assert result["ready"] is ready
    assert result["restore_verified"] is False


def test_boot_layout_uses_observed_device_ancestry(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(host, "_filesystem", lambda _: {"source": "/dev/sdz2[/@root]", "uuid": "observed", "fsroot": "/@root"})
    calls = []
    def checked(args: list[str]) -> str:
        calls.append(args)
        return "/dev/sdz2 part\n/dev/sdz disk\n" if args[0] == "lsblk" else "label: gpt\n"
    monkeypatch.setattr(host, "_checked", checked)
    result = host._boot_layout()
    assert result["disks"] == [{"device": "/dev/sdz", "partition_layout": "label: gpt\n"}]
    assert all("/dev/nvme0n1" not in command for command in calls)
    assert all("--raw" in command for command in calls if command[0] == "lsblk")
    assert result["restore_verified"] is False


def test_capacity_keeps_full_filesystem_bound_even_with_small_previous_increment(monkeypatch: pytest.MonkeyPatch) -> None:
    rows = [{"source_url": "/source", "target_path": "/independent"}]
    monkeypatch.setenv("SF_HOST_RETENTION_PRESSURE_MIN_FREE_GB", "0")
    monkeypatch.setattr(host, "_filesystem", lambda path: {"uuid": "source" if path in {"/source", "/boot", "/boot/efi"} else "target", "fstype": "btrfs", "options": "compress=zstd"})
    monkeypatch.setattr(Path, "stat", lambda *_args, **_kwargs: SimpleNamespace(st_ino=256))
    monkeypatch.setattr(host.shutil, "disk_usage", lambda path: SimpleNamespace(total=1000, used=600, free=400) if path == "/source" else SimpleNamespace(total=1000, used=500, free=500))
    monkeypatch.setattr(host, "_allocation_headroom", lambda *_: {"available": True, "admitted": True, "missing": 0})
    result = host._capacity(rows, {"growth_peak_bytes": 1})
    assert result["expected_growth_bytes"] == 600
    assert result["admitted"] is False


@pytest.mark.parametrize("fault", [None, "source-exhausted", "target-exhausted", "unreadable", "invalid", "wrong-uuid"])
def test_capacity_requires_measured_allocation_headroom_on_each_unique_filesystem(monkeypatch: pytest.MonkeyPatch, fault: str | None) -> None:
    gib = 1024**3
    rows = [{"source_url": path, "target_path": "/independent/points"} for path in ("/source", "/source/nested", "/workspace")]
    monkeypatch.setenv("SF_HOST_RETENTION_PRESSURE_MIN_FREE_GB", "25")
    def filesystem(path: str) -> dict[str, str]:
        uuid = "target" if path.startswith("/independent") else "workspace" if path == "/workspace" else "source"
        return {"uuid": uuid, "fstype": "btrfs", "options": "rw,compress=zstd:1"}
    monkeypatch.setattr(host, "_filesystem", filesystem)
    monkeypatch.setattr(Path, "stat", lambda *_args, **_kwargs: SimpleNamespace(st_ino=256))
    monkeypatch.setattr(host.shutil, "disk_usage", lambda path: SimpleNamespace(total=100 * gib, used=70 * gib, free=30 * gib) if path.startswith("/source") else SimpleNamespace(total=1000 * gib, used=100 * gib, free=900 * gib))
    calls = []
    def guard(args: list[str]) -> subprocess.CompletedProcess[str]:
        assert args[:4] == ["sudo", "-n", host.SPACE_GUARD, "--check-only"]
        path, uuid = args[5], args[7]
        calls.append((path, uuid))
        if fault == "unreadable" and uuid == "source":
            return subprocess.CompletedProcess(args, 1, json.dumps({"path": path, "error": "usage unavailable"}), "")
        usage = {"size": 1000 * gib, "free": 30 * gib, "missing": 0, "unallocated": 20 * gib, "metadata_size": 2 * gib, "metadata_used": gib}
        exhausted = (fault == "source-exhausted" and uuid == "source") or (fault == "target-exhausted" and uuid == "target")
        if exhausted:
            usage.update(unallocated=1024**2, metadata_used=int(usage["metadata_size"] * 0.9146))
        if fault == "invalid" and uuid == "source":
            usage["metadata_used"] = usage["metadata_size"] + 1
        report = {"path": path, "uuid": "unexpected" if fault == "wrong-uuid" and uuid == "source" else uuid, "after": usage,
                  "policy": {"trigger_bytes": 8 * gib, "target_bytes": 12 * gib}}
        return subprocess.CompletedProcess(args, int(exhausted), json.dumps(report), "")
    monkeypatch.setattr(host, "_run", guard)
    result = host._capacity(rows, None)
    assert calls == [("/source", "source"), ("/workspace", "workspace"), ("/independent/points", "target")]
    assert result["expected_growth_bytes"] == 170 * gib
    assert result["admitted"] is (fault is None)
    assert result["reason"] == (None if fault is None else "insufficient-btrfs-allocation-headroom" if "exhausted" in fault else "btrfs-allocation-headroom-unavailable")
    assert result["reserve_bytes"] == 25 * gib
    if fault is None or "exhausted" in fault:
        allocation = result["target_allocation"] if fault == "target-exhausted" else result["source_filesystems"][0]["allocation"]
        assert allocation["trigger_bytes"] == 8 * gib and allocation["target_bytes"] == 12 * gib
        assert allocation["unallocated"] == (1024**2 if fault else 20 * gib)
        assert allocation["metadata_used_percent"] == pytest.approx(91.46 if fault else 50)


@pytest.mark.parametrize("fault", ["missing-layout", "relocated-metadata", "changed-target-uuid"])
def test_association_retry_fails_closed_on_lost_artifact_or_identity(capture: dict[str, Any], monkeypatch: pytest.MonkeyPatch, fault: str) -> None:
    result = host.run_native_host_backup(now=NOW)
    assert result["status"] == "completed"
    previous = (capture["root"] / "last-good.json").read_bytes()
    result["status"] = "partial"
    if fault == "missing-layout":
        (capture["root"] / "operations" / result["run_id"] / "layout.json").unlink()
    elif fault == "relocated-metadata":
        result["boot_path"] = "/etc/unrelated/boot"
    else:
        monkeypatch.setattr(host, "_filesystem", lambda _: {"uuid": "changed"})
    resumed = host._resume_association(result, NOW)
    assert resumed["status"] == "failed"
    assert (capture["root"] / "last-good.json").read_bytes() == previous
    capture["bulk"].assert_called_once()


@pytest.mark.parametrize("fault", ["same-uuid", "metadata-on-source"])
def test_capacity_rejects_dependent_target_or_metadata_parent(monkeypatch: pytest.MonkeyPatch, fault: str) -> None:
    rows = [{"source_url": "/source", "target_path": "/independent/points"}]
    def filesystem(path: str) -> dict[str, str]:
        source = path == "/source" or (fault == "metadata-on-source" and path == "/independent")
        return {"uuid": "same" if fault == "same-uuid" else "source" if source else "target", "fstype": "btrfs", "options": "compress=zstd"}
    monkeypatch.setattr(host, "_filesystem", filesystem)
    with pytest.raises(RuntimeError, match="independent"):
        host._capacity(rows, None)


def test_empty_project_registry_never_qualifies_database_recovery(monkeypatch: pytest.MonkeyPatch) -> None:
    # A catalogue with no projects (for example a test database) once wrote a
    # vacuous "qualified" association with zero manifests over a live receipt.
    monkeypatch.setattr(host, "testing_project_ids", lambda: set())
    monkeypatch.setattr(host, "list_projects", lambda: [])
    monkeypatch.setattr(host.backup_store, "list_sources", lambda: [])
    result = host._database_manifests([{"source_url": "/"}], NOW)
    assert result["status"] == "partial"
    assert result["missing"] == [{"project_id": None, "reason": "project-registry-empty", "source_ids": []}]


def test_tests_never_reach_live_native_host_state() -> None:
    assert host._enabled() is False
    assert not host._state_root().is_relative_to(Path.home() / ".local/state/summitflow")
