"""Monthly pinned restore: vault identity host files and the OmniNull hub state archive."""

from __future__ import annotations

import gzip
import hashlib
import io
import json
import sqlite3
import tarfile
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest

from app.tasks import backup_offsite_restore_test as monthly
from app.tasks import backup_pinned_restore_test as pinned
from app.tasks import backup_proxmox, backup_repository_runtime, backup_restic


def _tar(members: dict[str, bytes], *, prefix: str = "") -> bytes:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w") as tar:
        for name, data in members.items():
            info = tarfile.TarInfo(prefix + name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    return buffer.getvalue()


def _point(backup_id: str, capture: dict[str, Any] | None = None, *, offsite: str = "verified", created: str = "2026-10-12") -> dict[str, Any]:
    return {"id": backup_id, "status": "completed", "created_at": created,
            "verification_json": {"snapshot_id": "a" * 64, "remote_snapshot_id": "b" * 64, "offsite": {"status": offsite},
                                  "capture": capture or {}}}


def test_tar_paths_need_readable_non_empty_content(tmp_path: Path) -> None:
    archive = tmp_path / "files.tar"
    archive.write_bytes(_tar({"vault/identity/device.key": b"k" * 32, "vault/identity/empty": b"", "etc/pve/qemu-server/120.conf": b"x"}, prefix="./"))
    result = pinned.check_tar_paths(archive, ["/vault/identity", "/etc/pve/qemu-server/120.conf", "/var/lib/vz/snippets/a.yaml"], compressed=False)
    assert result["missing"] == ["var/lib/vz/snippets/a.yaml"]
    assert result["paths"]["vault/identity"] == {"files": 1, "bytes": 32}
    packed = tmp_path / "files.tar.gz"
    packed.write_bytes(gzip.compress(archive.read_bytes()))
    assert pinned.check_tar_paths(packed, ["/vault/identity"], compressed=True)["missing"] == []


def test_pinned_point_needs_both_snapshots_and_offsite(monkeypatch: pytest.MonkeyPatch) -> None:
    good = _point("good", created="2026-10-10")
    pending = _point("pending", offsite="pending", created="2026-10-12")
    local_only = {**_point("local", created="2026-10-11"), "verification_json": {"snapshot_id": "a" * 64, "offsite": {"status": "verified"}}}
    monkeypatch.setattr(pinned.backup_store, "list_backups", lambda **_: ([good, pending, local_only], 3))
    assert (pinned.pinned_point("pve-host-files") or {}).get("id") == "good"


def test_host_files_restore_compares_offsite_and_local_copies(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    data = _tar({"vault/identity/device.key": b"k" * 32, "etc/pve/qemu-server/120.conf": b"x"})
    copies = {True: data, False: data}

    def restore(point: dict, destination: Path, *, remote: bool = False) -> dict:
        target = destination / "stream.tar"
        target.write_bytes(copies[remote])
        return {"payload_file": str(target)}

    _scratch(monkeypatch, tmp_path)
    monkeypatch.setattr(backup_proxmox, "restore_stream_isolated", restore)
    point = _point("bkp-h", {"kind": "proxmox-files", "paths": ["/vault/identity", "/etc/pve/qemu-server/120.conf"], "stream_bytes": len(data)})
    evidence = pinned.restore_host_files(point)
    assert evidence["ok"] is True and evidence["copies_identical"] is True and evidence["remote"] is True
    copies[False] = _tar({"vault/identity/device.key": b"j" * 32, "etc/pve/qemu-server/120.conf": b"x"})
    assert pinned.restore_host_files(point)["ok"] is False


def _scratch(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    counter = iter(range(1000))

    @contextmanager
    def scratch(prefix: str, *, required_bytes: int = 0):
        path = tmp_path / f"scratch-{next(counter)}"
        path.mkdir(mode=0o700)
        yield path

    monkeypatch.setattr(pinned, "restore_scratch", scratch)


def _database(path: Path) -> bytes:
    connection = sqlite3.connect(str(path))
    connection.execute("CREATE TABLE t (x)")
    connection.execute("INSERT INTO t VALUES (1)")
    connection.commit()
    connection.close()
    return path.read_bytes()


def _hub(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, *, tamper: bool = False, drop: str | None = None, remote_size: int | None = None,
         wal: list[str] | None = None, written: list[str] | None = None) -> dict:
    written = [] if written is None else written
    hub_db = _database(tmp_path / "hub.db")
    authority = _database(tmp_path / "authority.db")
    members = {"etc/ominull/admin.key": b"a" * 57, "var/lib/ominull/ominull.db": hub_db, "var/lib/ominull/ominull.db-wal": b"",
               "var/lib/ominull-response-authority/authority.db": authority, "var/lib/ominull/unrelated.log": b"noise"}
    required = ["etc/ominull/admin.key", "var/lib/ominull/ominull.db", "var/lib/ominull-response-authority/authority.db"]
    archive = _tar({name: data for name, data in members.items() if name != drop}, prefix="./")
    manifest = {"source_id": pinned.HUB_STATE, "archive_path": "/media/x/current/lxc-150.tar", "size_bytes": len(archive),
                "sha256": hashlib.sha256(archive).hexdigest(), "required_paths_verified": required,
                "wal_paths_verified": ["var/lib/ominull/ominull.db-wal"] if wal is None else wal}
    stored = tmp_path / "stored.tar"
    stored.write_bytes(archive + (b"\0" * 512 if tamper else b""))

    class Adapter:
        def __init__(self, config: Any) -> None:
            pass

        def restore(self, snapshot: str, destination: Path, *, include: list[str]) -> dict:
            root = destination / "media/x/current"
            root.mkdir(parents=True)
            (root / "manifest.json").write_text(json.dumps(manifest))
            return {"payload_root": str(root)}

        def _command(self, *args: str, remote: bool = False) -> list[str]:
            return ["cat", str(stored)] if args[0] == "dump" else ["ls", *args]

        def _run(self, command: list[str], *, phase: str, stdout_sink: Any = None, timeout: float | None = None, text: bool = True) -> SimpleNamespace:
            if stdout_sink is not None:
                assert command[0] == "cat" and timeout == pinned._STREAM_SECONDS  # the owned runner enforces the deadline
                with stored.open("rb") as stream:
                    stdout_sink(stream)
                    written.extend(path.name for path in tmp_path.rglob("*") if path.is_file() and "scratch" in str(path))
                return SimpleNamespace(stdout=b"")
            size = len(archive) if remote_size is None else remote_size
            return SimpleNamespace(stdout=json.dumps({"path": "/media/x/current/lxc-150.tar", "type": "file", "size": size}) + "\n")

        def _env(self) -> dict[str, str]:
            return {"PATH": "/usr/bin:/bin"}

    @contextmanager
    def lock(config: Any):
        yield

    _scratch(monkeypatch, tmp_path)
    monkeypatch.setattr(pinned, "ensure_scratch_capacity", lambda path, size: None)
    monkeypatch.setattr(backup_restic, "ResticAdapter", Adapter)
    monkeypatch.setattr(backup_restic.ResticConfig, "from_env", classmethod(lambda cls, env: object()))
    monkeypatch.setattr(backup_restic, "repository_lock", lock)
    monkeypatch.setattr(backup_repository_runtime, "_backup_environment", lambda point: {})
    monkeypatch.setattr(backup_repository_runtime, "_approved_key_directory", lambda config: None)
    monkeypatch.setattr(backup_repository_runtime, "_assert_repository_identity", lambda *a, **k: None)
    return pinned.restore_hub_state(_point("bkp-o"))


def test_hub_state_restore_proves_archive_files_and_databases(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    evidence = _hub(monkeypatch, tmp_path)
    assert evidence["ok"] is True and evidence["archive"]["sha256_matches"] is True
    assert evidence["files"] == {"required": 3, "restored": 4, "missing": [], "empty": []}
    assert {item["ok"] for item in evidence["databases"].values()} == {True} and len(evidence["databases"]) == 2


def test_hub_state_writes_only_databases_and_accepts_no_wal(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    written: list[str] = []
    assert _hub(monkeypatch, tmp_path, written=written)["ok"] is True
    assert "admin.key" not in written and "ominull.db" in written  # keys are counted in memory, never written
    other = tmp_path / "no-wal"
    other.mkdir()
    assert _hub(monkeypatch, other, wal=[])["ok"] is True  # a checkpointed capture has no WAL to restore


@pytest.mark.parametrize("variant", [{"tamper": True}, {"drop": "var/lib/ominull-response-authority/authority.db"}, {"remote_size": 1}])
def test_hub_state_restore_fails_on_any_mismatch(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, variant: dict) -> None:
    assert _hub(monkeypatch, tmp_path, **variant)["ok"] is False


def test_hub_manifest_paths_must_be_safe() -> None:
    with pytest.raises(RuntimeError):
        pinned._manifest_paths({"required_paths_verified": ["../etc/shadow"]}, "required_paths_verified")
    with pytest.raises(RuntimeError):
        pinned._manifest_paths({"required_paths_verified": ["/abs"]}, "required_paths_verified")


def test_monthly_run_adds_pinned_sources_and_records_them(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(monthly, "RECEIPT", tmp_path / "monthly.json")
    rotating = {"id": "neri", "enabled": True, "path": "/n"}
    host = {"id": pinned.HOST_FILES, "enabled": True, "path": "proxmox://proxmox-gem/host/files?path=/vault/identity"}
    hub = {"id": pinned.HUB_STATE, "enabled": True, "path": "/media/x/current"}
    monkeypatch.setattr(monthly.backup_store, "list_sources", lambda: [rotating, host, hub])
    monkeypatch.setattr(monthly, "select_rotation", lambda _sources: [(rotating, {"id": "bkp-n"})])
    monkeypatch.setattr(pinned, "pinned_point", lambda source_id: {"id": f"bkp-{source_id}"})
    monkeypatch.setattr(monthly, "restore_test_point", lambda source, point: {"ok": True, "method": monthly.METHOD})
    pinned_calls = MagicMock(side_effect=lambda source, point: {"ok": True, "method": pinned.METHOD})
    monkeypatch.setattr(pinned, "restore_test_pinned", pinned_calls)
    drills: list[dict] = []
    monkeypatch.setattr(monthly.backup_store, "merge_backup_verification_json", lambda backup_id, update: None)
    monkeypatch.setattr(monthly.backup_store, "update_source_drill_result", lambda **kwargs: drills.append(kwargs))
    receipt = monthly.run_monthly_offsite_restore_test(force=True)
    assert receipt["status"] == "verified" and set(receipt["sources"]) == {"neri", pinned.HOST_FILES, pinned.HUB_STATE}
    assert pinned_calls.call_count == 2 and {item["source_id"] for item in drills} == {"neri", pinned.HOST_FILES, pinned.HUB_STATE}
    assert set(json.loads((tmp_path / "monthly.json").read_text())["sources"]) == set(receipt["sources"])
    one = monthly.run_monthly_offsite_restore_test(source_id=pinned.HUB_STATE)
    assert set(one["sources"]) == {pinned.HUB_STATE} and pinned_calls.call_count == 3
