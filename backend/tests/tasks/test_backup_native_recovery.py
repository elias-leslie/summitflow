"""Focused tests for portable project recovery and encrypted offsite sync."""

from __future__ import annotations

import sqlite3
import subprocess
from pathlib import Path
from typing import Any, cast

import pytest


def _git(project: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(project), *args],
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


def test_archive_restores_git_history_index_worktree_sqlite_and_safe_links(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.tasks import backup_native_archive
    from app.tasks.backup_native_restore import restore_isolated_archive

    project = tmp_path / "project"
    project.mkdir()
    _git(project, "init", "-b", "main")
    _git(project, "config", "user.name", "Fixture")
    _git(project, "config", "user.email", "fixture@example.invalid")
    (project / "tracked.txt").write_text("base\n")
    (project / ".gitignore").write_text("valuable.local\n")
    _git(project, "add", ".")
    _git(project, "commit", "-m", "base")
    original_head = _git(project, "rev-parse", "HEAD")

    (project / "tracked.txt").write_text("unstaged\n")
    (project / "staged.txt").write_text("staged\n")
    _git(project, "add", "staged.txt")
    (project / "untracked.txt").write_text("untracked\n")
    (project / "valuable.local").write_text("ignored but valuable\n")
    docs = project / "docs"
    docs.mkdir()
    (docs / "readme.txt").write_text("linked\n")
    (project / "docs-link").symlink_to("docs", target_is_directory=True)
    (project / "unsafe-link").symlink_to(tmp_path / "outside")

    database = project / "state.sqlite3"
    with sqlite3.connect(database) as connection:
        connection.execute("CREATE TABLE evidence(value TEXT)")
        connection.execute("INSERT INTO evidence VALUES ('recoverable')")

    monkeypatch.setattr(backup_native_archive, "_dump_database", lambda *_args: (0, False))
    staging = tmp_path / "staging"
    staging.mkdir()
    result = backup_native_archive._create_project_archive(project, "project", staging, {})

    assert result["verification"]["verified"] is True
    assert result["verification"]["recovery"]["git"]["head"] == original_head
    assert result["verification"]["recovery"]["snapshot_symlinks"] == 1

    restored = tmp_path / "restored"
    recovery = restore_isolated_archive(Path(result["archive_path"]), restored)

    assert recovery["recovery"]["git_restored"] is True
    assert _git(restored, "rev-parse", "HEAD") == original_head
    status = _git(restored, "status", "--short", "--ignored")
    assert " M tracked.txt" in status
    assert "A  staged.txt" in status
    assert "?? untracked.txt" in status
    assert "!! valuable.local" in status
    assert (restored / "docs-link").is_symlink()
    assert (restored / "docs-link").readlink().as_posix() == "docs"
    assert not (restored / "unsafe-link").exists()
    with sqlite3.connect(restored / "state.sqlite3") as connection:
        assert connection.execute("SELECT value FROM evidence").fetchone() == ("recoverable",)


def test_snapshot_fails_closed_when_source_changes_during_copy(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.tasks import backup_native_recovery as recovery

    project = tmp_path / "project"
    project.mkdir()
    changing = project / "changing.txt"
    changing.write_text("before")
    original_copy = recovery.copy_inventory_snapshot

    def copy_then_change(project_dir, destination, inventory):
        original_copy(project_dir, destination, inventory)
        changing.write_text("after")

    monkeypatch.setattr(recovery, "copy_inventory_snapshot", copy_then_change)

    with pytest.raises(RuntimeError, match="changed during capture"):
        recovery.build_consistent_snapshot(project, tmp_path / "stage", (), lambda *_args: False)


def test_snapshot_always_excludes_private_backup_key_directory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.tasks import backup_native_recovery as recovery

    project = tmp_path / "project"
    project.mkdir()
    (project / "safe.txt").write_text("safe")
    key_dir = project / ".private-keys"
    key_dir.mkdir()
    (key_dir / "backup-identity.agekey").write_text("must not archive")
    monkeypatch.setattr(recovery, "backup_key_directory", lambda: key_dir)

    snapshot, _manifest = recovery.build_consistent_snapshot(
        project,
        tmp_path / "stage",
        (),
        lambda rel, patterns: any(rel == item or rel.startswith(f"{item}/") for item in patterns),
    )

    assert (snapshot / "safe.txt").is_file()
    assert not (snapshot / ".private-keys").exists()


def test_offsite_replication_verifies_download_and_records_provider_uri(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.tasks import backup_native_offsite as offsite

    archive = tmp_path / "source-20260921-120000.tar.gz.age"
    archive.write_bytes(b"encrypted payload")
    remote_bytes: dict[str, bytes] = {}

    monkeypatch.setattr(offsite.shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(offsite, "_ensure_display_folder", lambda *_args: "google-drive://account/folder-id")
    provider_ids = iter([None, "google-drive://account/file-id"])
    monkeypatch.setattr(offsite, "_find_display_child", lambda *_args: next(provider_ids))
    monkeypatch.setattr(offsite, "_apply_remote_retention", lambda *_args: [])

    def run(command: list[str], *, timeout: int = 300):
        if command[:2] == ["gio", "copy"] and Path(command[-2]).is_file():
            remote_bytes[command[-1]] = Path(command[-2]).read_bytes()
        elif command[:2] == ["gio", "copy"]:
            Path(command[-1]).write_bytes(remote_bytes["google-drive://account/folder-id/source-20260921-120000.tar.gz.age"])
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr(offsite, "_run", run)

    result = offsite.replicate_completed_archive(
        archive,
        source_id="source",
        local_dir=tmp_path,
        env={
            "BACKUP_OFFSITE_GIO_URI": "google-drive://account/my-drive-id",
        },
        retention_days=14,
    )

    assert result["status"] == "verified"
    assert result["location"] == "google-drive://account/file-id"
    assert result["transfer_bytes"] == len(b"encrypted payload") * 2
    manifest = (tmp_path / offsite.OFFSITE_MANIFEST_NAME).read_text()
    assert "google-drive://account/file-id" in manifest


def test_offsite_retry_replaces_only_mismatching_archive_object(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.tasks import backup_native_offsite as offsite

    archive = tmp_path / "source-20260921-120000.tar.gz.age"
    archive.write_bytes(b"complete encrypted payload")
    source_folder = "google-drive://account/folder-id"
    stale_uri = "google-drive://account/stale-file-id"
    replacement_uri = "google-drive://account/replacement-file-id"
    requested_uri = f"{source_folder}/{archive.name}"
    remote_bytes = {stale_uri: b"partial"}
    removed: list[str] = []

    monkeypatch.setattr(offsite.shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(offsite, "_ensure_display_folder", lambda *_args: source_folder)
    provider_ids = iter([stale_uri, replacement_uri])
    monkeypatch.setattr(offsite, "_find_display_child", lambda *_args: next(provider_ids))
    monkeypatch.setattr(offsite, "_apply_remote_retention", lambda *_args: [])

    def run(command: list[str], *, timeout: int = 300):
        if command[:2] == ["gio", "remove"]:
            removed.append(command[-1])
            remote_bytes.pop(command[-1], None)
        elif command[:2] == ["gio", "copy"] and Path(command[-2]).is_file():
            remote_bytes[replacement_uri] = Path(command[-2]).read_bytes()
            remote_bytes[requested_uri] = remote_bytes[replacement_uri]
        elif command[:2] == ["gio", "copy"]:
            Path(command[-1]).write_bytes(remote_bytes[command[-2]])
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr(offsite, "_run", run)

    result = offsite.replicate_completed_archive(
        archive,
        source_id="source",
        local_dir=tmp_path,
        env={"BACKUP_OFFSITE_GIO_URI": "google-drive://account/my-drive-id"},
        retention_days=14,
        retry=True,
    )

    assert result["status"] == "verified"
    assert result["location"] == replacement_uri
    assert removed == [stale_uri]
    assert result["transfer_bytes"] == len(b"partial") + len(archive.read_bytes()) * 2


def test_isolated_restore_persists_same_backup_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.tasks import backup_executor

    source = tmp_path / "source"
    archive = source / "backups" / "source-20260921-120000.tar.gz"
    archive.parent.mkdir(parents=True)
    archive.write_bytes(b"fixture")
    from app.tasks.backup_native_archive import archive_sha256
    archive_checksum = archive_sha256(archive)
    merged: list[tuple[str, object]] = []
    monkeypatch.setattr(
        backup_executor.backup_store,
        "get_backup",
        lambda _backup_id: {
            "id": "backup-1",
            "source_id": "source",
            "name": archive.name,
            "checksum": archive_checksum,
        },
    )
    monkeypatch.setattr(
        backup_executor.backup_store,
        "get_source",
        lambda _source_id: {"path": str(source)},
    )
    monkeypatch.setattr(
        backup_executor.backup_store,
        "merge_backup_verification_json",
        lambda backup_id, value: merged.append((backup_id, value)),
    )
    monkeypatch.setattr(
        backup_executor,
        "restore_isolated_archive",
        lambda path, destination: {
            "archive": str(path),
            "destination": str(destination),
            "recovery": {"git_restored": True},
        },
    )

    result = backup_executor.restore_backup_isolated("backup-1", tmp_path / "restored")
    evidence = cast(dict[str, Any], result["evidence"])

    assert evidence["ok"] is True
    assert evidence["git_restored"] is True
    assert merged[0][0] == "backup-1"
    merged_evidence = cast(dict[str, Any], merged[0][1])
    isolated_restore = cast(dict[str, Any], merged_evidence["isolated_restore"])
    assert isolated_restore["archive_checksum"] == archive_checksum


def test_isolated_restore_rejects_source_mismatch_and_unproven_download(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.tasks import backup_executor

    archive = tmp_path / "downloaded.tar.gz.age"
    archive.write_bytes(b"ciphertext")
    monkeypatch.setattr(
        backup_executor.backup_store,
        "get_backup",
        lambda _backup_id: {
            "id": "backup-1",
            "source_id": "summitflow",
            "name": archive.name,
            "checksum": "",
        },
    )
    monkeypatch.setattr(
        backup_executor.backup_store,
        "get_source",
        lambda _source_id: {"path": str(tmp_path)},
    )

    with pytest.raises(RuntimeError, match="belongs to source summitflow"):
        backup_executor.restore_backup_isolated(
            "backup-1",
            tmp_path / "source-mismatch",
            expected_source_id="other-source",
        )

    with pytest.raises(RuntimeError, match="recorded checksum"):
        backup_executor.restore_backup_isolated(
            "backup-1",
            tmp_path / "unproven",
            archive_file=archive,
        )


def test_archive_encryption_fails_closed_without_validated_recipient(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services.backup_keys import BackupKeyUnavailableError
    from app.tasks.backup_native_offsite import encrypt_completed_archive

    plaintext = tmp_path / "backup.tar.gz"
    plaintext.write_bytes(b"sensitive")

    monkeypatch.setattr(
        "app.tasks.backup_native_offsite.get_backup_key_paths",
        lambda **_kwargs: (_ for _ in ()).throw(
            BackupKeyUnavailableError("backup_key_not_verified")
        ),
    )

    with pytest.raises(BackupKeyUnavailableError, match="backup_key_not_verified"):
        encrypt_completed_archive(
            plaintext,
            tmp_path / "backup.tar.gz.age",
            {},
        )
