"""Native receipts prove independent artifacts, not a boot/DB restore drill."""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import Mock

import pytest

from app.tasks import backup_btrbk as host
from app.tasks.backup_proc import Result

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
    monkeypatch.setattr(host, "NATIVE_TARGET", target)
    monkeypatch.setenv("BACKUP_BTRBK_ENABLED", "true")
    rows = [{"source_url": "/", "target_path": str(target), "snapshot_path": "/snapshots"}]
    state = {"target_filesystem_uuid": "independent-uuid", "free_bytes": 900, "used_bytes": 100, "total_bytes": 1000}
    monkeypatch.setattr(host, "native_host_status", lambda: {"ready": True, "last_result": host._receipt()})
    monkeypatch.setattr(host, "_configuration", lambda: rows)
    monkeypatch.setattr(host, "_validate_nested_coverage", lambda _: None)
    monkeypatch.setattr(host, "_target_state", lambda _: state)
    monkeypatch.setattr(host, "_filesystem", lambda path: {"uuid": "source-fs" if path == "/" else "independent-uuid"})
    monkeypatch.setattr(host, "_boot_layout", lambda: {"disks": [{"device": "/dev/observed", "partition_layout": "fixture"}]})
    point = {"source": "/", "snapshot": "/snapshots/current", "target": str(target / "current"), "source_uuid": "source-uuid", "received_uuid": "source-uuid"}
    Path(point["target"]).mkdir()
    monkeypatch.setattr(host, "_verified_points", lambda *_: [point])
    monkeypatch.setattr(host, "_target_deletions_refused", lambda _: False)
    bulk = Mock(return_value=Result(0, stdout="format=raw type=snapshot status=success source_url=/ target_url=/snapshots/current\n"))
    monkeypatch.setattr(host, "run_process", bulk)
    monkeypatch.setattr(host.shutil, "disk_usage", lambda _: SimpleNamespace(total=1000, used=110, free=890))
    calls: list[list[str]] = []
    fail = {"artifact": None, "delete": False}
    def checked(args: list[str], *, bulk: bool = False) -> str:
        calls.append(args)
        command = args[2:] if args[:2] == ["sudo", "-n"] else args
        name = command[0]
        destination = Path(command[-1])
        if name == host.NATIVE_HELPER:
            return native(command[1:])
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
    captures = target.parent / "summitflow-host-recovery" / "captures"
    def native(command: list[str]) -> str:
        # Mirrors scripts/summitflow-native-capture against the fixture store.
        action, *rest = command
        if action == "publish":
            run_id, name, source, digest = rest
            if name.startswith(str(fail["artifact"])):
                raise RuntimeError("fixture independent artifact copy failure")
            assert hashlib.sha256(Path(source).read_bytes()).hexdigest() == digest
            (captures / run_id).mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, captures / run_id / name)
        elif action == "copy-boot":
            (captures / rest[0] / "boot").mkdir(parents=True, mode=0o700, exist_ok=True)
            (captures / rest[0] / "boot" / "kernel").write_bytes(b"fixture boot bytes")
        elif action == "read":
            return (captures / rest[0] / "capture.json").read_text()
        elif action == "remove":
            if fail["delete"]:
                raise RuntimeError("fixture deletion failure")
            shutil.rmtree(captures / rest[0])
        elif action == "list":
            directory = target if rest[0] == "target" else captures
            return "\n".join(str(path) for path in sorted(directory.iterdir()) if path.is_dir())
        elif action != "sync":
            raise AssertionError(f"Unexpected native helper command: {command}")
        return ""
    monkeypatch.setattr(host, "_checked", checked)
    stat_probe: dict[str, str | None] = {"fault": None}
    def run(args: list[str]) -> subprocess.CompletedProcess[str]:
        # Multi-path GNU root stat: one line per existing path, an error line per
        # missing one, exit 1 if any is missing.
        calls.append(args)
        assert args[:3] == ["sudo", "-n", "stat"], args
        if stat_probe["fault"] == "sudo":
            return subprocess.CompletedProcess(args, 1, "", "sudo: a password is required\n")
        paths = [Path(value) for value in args[args.index("--") + 1:]]
        lines = [f"{path}|0:{700 if path.is_dir() else 600}:{'directory' if path.is_dir() else 'regular file'}" for path in paths if path.exists()]
        error = "Input/output error" if stat_probe["fault"] == "io" else "No such file or directory"
        errors = [f"stat: cannot statx '{path}': {error}" for path in paths if not path.exists()]
        return subprocess.CompletedProcess(args, 0 if not errors else 1, "".join(f"{line}\n" for line in lines), "".join(f"{line}\n" for line in errors))
    monkeypatch.setattr(host, "_run", run)
    return {"root": root, "target": target, "rows": rows, "bulk": bulk, "calls": calls, "fail": fail, "checked": checked, "stat_probe": stat_probe}


def test_completion_published_only_after_every_independent_artifact(capture: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:
    write = host._write_receipt
    statuses = []
    def observe(payload: dict[str, Any]) -> None:
        statuses.append(payload["status"])
        if payload["status"] == "completed":
            directory = Path(payload["boot_path"]).parent
            assert json.loads((directory / "capture.json").read_text())["status"] == "completed"
            assert all((directory / name).is_file() for name in ("journal.log", "layout.json"))
            assert (directory / "boot" / "kernel").is_file()
        write(payload)
    monkeypatch.setattr(host, "_write_receipt", observe)
    result = host.run_native_host_backup(now=NOW)
    assert result["status"] == "completed"
    assert statuses == ["running", "running", "completed"]
    assert json.loads((capture["root"] / "last-good.json").read_text())["run_id"] == result["run_id"]
    assert (capture["root"] / "receipts" / f"{result['run_id']}.json").is_file()


@pytest.mark.parametrize("artifact", ["journal.log", "layout.json", "capture.json"])
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


def _subvolume_listing(monkeypatch: pytest.MonkeyPatch, *rows: str, rc: int = 0, outcome: str = "applied",
                       header: str = "ID\tgen\ttop level\tpath\t\n--\t---\t---------\t----\t\n", suffix: str = "") -> list[list[str]]:
    """Nightshift's diag.read btrfs.subvolumes response; children of the mount print relative to it."""
    calls: list[list[str]] = []
    monkeypatch.setattr(host, "_filesystem", lambda _: {"options": "rw,compress=zstd:1,subvolid=346,subvol=/@workspaces"})
    def run(args: list[str]) -> subprocess.CompletedProcess[str]:
        calls.append(args)
        out = header + "".join(f"{row}\t\n" for row in rows) + suffix
        response = {"id": "0" * 32, "outcome": outcome, "result": {"rc": 0, "out": out, "err": ""}}
        return subprocess.CompletedProcess(args, rc, json.dumps(response), "")
    monkeypatch.setattr(host, "_run", run)
    return calls


def test_nested_coverage_exempts_only_canonical_managed_workpoints(monkeypatch: pytest.MonkeyPatch) -> None:
    rows = [{"source_url": "/workspaces", "snapshot_path": "/host-snapshots"}]
    monkeypatch.setattr(host, "get_workspaces_root", lambda: Path("/workspaces"))
    # Subvolumes elsewhere in the filesystem (other parents) are not below this source.
    calls = _subvolume_listing(monkeypatch, "300\t1\t346\t\t.snapshots/project/point", "301\t1\t5\t\t@other/data",
                               "302\t1\t300\t\t.snapshots/project/point/inner")
    host._validate_nested_coverage(rows)
    assert calls == [["nightshift", "request", "diag.read", "probe=btrfs.subvolumes", "target=/workspaces",
                      "--reason", "maintain", "--agent", "summitflow-host-backup", "--wait", "120"]]
    for nested in ("project/.snapshots/durable", "project/__snapshots/durable", "project/data"):
        _subvolume_listing(monkeypatch, f"301\t1\t346\t\t{nested}")
        with pytest.raises(RuntimeError, match="explicit host coverage"):
            host._validate_nested_coverage(rows)


@pytest.mark.parametrize("fault", ["exit", "shadow", "truncated", "header", "row", "escape", "absolute"])
def test_nested_coverage_fails_closed_on_an_unusable_listing(monkeypatch: pytest.MonkeyPatch, fault: str) -> None:
    rows = [{"source_url": "/workspaces", "snapshot_path": "/host-snapshots"}]
    monkeypatch.setattr(host, "get_workspaces_root", lambda: Path("/workspaces"))
    child = {"escape": "../outside", "absolute": "/abs"}.get(fault, ".snapshots/project/point")
    _subvolume_listing(monkeypatch, "garbage" if fault == "row" else f"300\t1\t346\t\t{child}",
                       rc=1 if fault == "exit" else 0, outcome="shadow" if fault == "shadow" else "applied",
                       suffix="\n[truncated]" if fault == "truncated" else "",
                       **({"header": "ID gen path\n"} if fault == "header" else {}))
    with pytest.raises(RuntimeError):
        host._validate_nested_coverage(rows)


def test_nested_coverage_requires_the_mounted_subvolume_identity(monkeypatch: pytest.MonkeyPatch) -> None:
    _subvolume_listing(monkeypatch)
    monkeypatch.setattr(host, "_filesystem", lambda _: {"options": "rw,subvol=/@workspaces"})
    with pytest.raises(RuntimeError, match="Cannot identify"):
        host._child_subvolumes(Path("/workspaces"))


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


@pytest.mark.parametrize("fault", [None, "sudo", "io"])
def test_metadata_cleanup_reports_a_receiptless_capture_directory_without_blocking(capture: dict[str, Any], fault: str | None) -> None:
    # An interrupted removal deleted boot and the receipt but left operator files behind.
    run_id = "20261006T115729Z-984410df"
    directory = capture["target"].parent / "summitflow-host-recovery" / "captures" / run_id
    directory.mkdir(parents=True)
    (directory / "bounded-recovery-verification.json").write_text("{}")
    capture["stat_probe"]["fault"] = fault
    result = host._cleanup_superseded(capture["target"], "20261016T063000Z-0e0f6422")
    assert (directory / "bounded-recovery-verification.json").is_file()
    assert not result["removed"]
    if fault:
        # A failed probe or a receipt read error is never mistaken for an absent receipt.
        assert result["result"] == "partial" and result["blockers"][0]["run_id"] == run_id
        assert not result["uncatalogued"]
    else:
        assert result["result"] == "completed" and not result["blockers"]
        assert result["uncatalogued"] == [run_id]


@pytest.mark.parametrize("ready", [False, True])
def test_readiness_follows_the_install_and_a_clean_btrbk_dry_run(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, ready: bool) -> None:
    monkeypatch.setattr(host, "_state_root", lambda: tmp_path)
    config = tmp_path / "qualified-config"
    config.write_text("fixture")
    monkeypatch.setattr(host, "CONFIG_PATH", config)
    monkeypatch.setattr(host.shutil, "which", lambda _: "/usr/bin/btrbk" if ready else None)
    monkeypatch.setattr(host, "_configuration", lambda: [{"source_url": "/", "target_path": "/independent/points"}])
    monkeypatch.setattr(host, "_validate_nested_coverage", lambda _: None)
    monkeypatch.setattr(host, "_qualify_target_directory", lambda _: None)
    monkeypatch.setattr(host, "_target_state", lambda _: {"target_filesystem_uuid": "u", "free_bytes": 1, "used_bytes": 1, "total_bytes": 2})
    monkeypatch.setattr(host, "_run", lambda _: subprocess.CompletedProcess([], 0))
    result = host.native_host_status()
    assert result["ready"] is ready


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


def test_tests_never_reach_live_native_host_state() -> None:
    assert host._enabled() is False
    assert not host._state_root().is_relative_to(Path.home() / ".local/state/summitflow")


def test_nested_coverage_resolves_a_symlinked_workspaces_root(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    # The default root (~/.local/share/summitflow/workspaces) links to the Btrfs mount;
    # work snapshots under the real mount are still managed workpoints.
    mount = tmp_path / "srv-workspaces"
    (mount / ".snapshots" / "WIP").mkdir(parents=True)
    link = tmp_path / "home-workspaces"
    link.symlink_to(mount)
    rows = [{"source_url": str(mount), "snapshot_path": "/host-snapshots"}]
    monkeypatch.setattr(host, "get_workspaces_root", lambda: link)
    _subvolume_listing(monkeypatch, "300\t1\t346\t\t.snapshots/WIP/projects/WIP/point")
    host._validate_nested_coverage(rows)
    _subvolume_listing(monkeypatch, "301\t1\t346\t\tprojects/data")
    with pytest.raises(RuntimeError, match="explicit host coverage"):
        host._validate_nested_coverage(rows)


def test_target_deletion_preview_failure_preserves_points(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(host, "_target_deletions_exceed_retention", Mock(side_effect=OSError("sudo unavailable")))
    assert host._target_deletions_refused(tmp_path) is True


def test_target_deletion_preview_trips_on_mass_expiry(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    names = [f"root.2026100{day}" for day in range(1, 8)]
    plan = "\n".join(f"format=raw type=delete status=success target_url={tmp_path / name}" for name in names[:5])
    monkeypatch.setattr(host, "_run", lambda _: subprocess.CompletedProcess([], 0, plan, ""))
    monkeypatch.setattr(host, "NATIVE_TARGET", tmp_path)
    monkeypatch.setattr(host, "_checked", lambda *_args, **_kwargs: "\n".join(str(tmp_path / name) for name in names))
    assert host._target_deletions_refused(tmp_path) is True
    monkeypatch.setattr(host, "_run", lambda _: subprocess.CompletedProcess([], 0, plan.splitlines()[0], ""))
    assert host._target_deletions_refused(tmp_path) is False




def test_a_second_run_skips_while_one_is_active(capture: dict[str, Any]) -> None:
    with host.host_run_lock():
        assert host.run_native_host_backup(now=NOW) == {"status": "skipped", "reason": "host-backup-active"}
    capture["bulk"].assert_not_called()


def test_a_disabled_host_backup_starts_nothing(capture: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BACKUP_BTRBK_ENABLED", "false")
    assert host.run_native_host_backup(now=NOW) == {"status": "skipped", "reason": "host-backup-disabled"}
    capture["bulk"].assert_not_called()
