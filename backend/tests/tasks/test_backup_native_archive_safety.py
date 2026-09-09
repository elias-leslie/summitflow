"""Safety tests for native backup archive creation and verification."""

from __future__ import annotations

import io
import os
import tarfile
from pathlib import Path
from unittest.mock import Mock

import pytest

from app.tasks.backup_native_archive import (
    _add_project_files,
    archive_sha256,
    verify_archive,
)
from app.tasks.backup_native_infra import _copy_if_exists
from app.tasks.backup_native_restore import restore_archive


def test_archive_checksum_streams_instead_of_reading_whole_file(
    tmp_path: Path,
    monkeypatch,
) -> None:
    archive_path = tmp_path / "archive.bin"
    archive_path.write_bytes(b"streamed checksum")
    monkeypatch.setattr(
        Path,
        "read_bytes",
        lambda _self: (_ for _ in ()).throw(AssertionError("read_bytes used")),
    )

    assert archive_sha256(archive_path) == (
        "sha256:ab3db5fcf969b552ec278733651168f03ccc4fb2fb4a06a127a82b8f0316be5d"
    )


def test_project_archive_skips_links_special_files_and_reserved_dump_names(
    tmp_path: Path,
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    (project / "regular.txt").write_text("safe\n")
    (project / "outside-link").symlink_to(tmp_path / "outside")
    os.mkfifo(project / "named-pipe")
    (project / "database.sql.gz").write_bytes(b"reserved root content")
    nested = project / "nested"
    nested.mkdir()
    (nested / "database.sql.gz").write_bytes(b"repository content")
    archive_path = tmp_path / "project.tar.gz"

    with tarfile.open(archive_path, "w:gz") as archive:
        count = _add_project_files(archive, project, "source", ())

    with tarfile.open(archive_path, "r:gz") as archive:
        members = archive.getmembers()

    assert count == 2
    assert [member.name for member in members] == [
        "source/regular.txt",
        "source/nested/database.sql.gz",
    ]
    assert all(member.isreg() for member in members)

    verification = verify_archive(
        archive_path,
        db_dump_name="database.sql.gz",
        expects_db=False,
    )
    destination = tmp_path / "restored"
    restore_archive(archive_path, destination, dry_run=False, files_only=True)

    assert verification["verified"] is True
    assert verification["has_db"] is False
    assert (destination / "regular.txt").read_text() == "safe\n"
    assert (destination / "nested" / "database.sql.gz").read_bytes() == (
        b"repository content"
    )


def test_infrastructure_copy_skips_links_and_special_files(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "regular.txt").write_text("safe\n")
    (source / "outside-link").symlink_to(tmp_path / "outside")
    os.mkfifo(source / "named-pipe")
    destination = tmp_path / "copied"

    assert _copy_if_exists(source, destination) == 1
    assert (destination / "regular.txt").read_text() == "safe\n"
    assert not (destination / "outside-link").exists()
    assert not (destination / "named-pipe").exists()
    assert _copy_if_exists(source / "outside-link", tmp_path / "direct-link") == 0


def test_archive_verification_rejects_member_types_restore_cannot_handle(
    tmp_path: Path,
) -> None:
    archive_path = tmp_path / "unsafe.tar.gz"
    with tarfile.open(archive_path, "w:gz") as archive:
        regular = tarfile.TarInfo("source/regular.txt")
        regular.size = 4
        archive.addfile(regular, io.BytesIO(b"safe"))
        link = tarfile.TarInfo("source/link")
        link.type = tarfile.SYMTYPE
        link.linkname = "../../outside"
        archive.addfile(link)

    result = verify_archive(
        archive_path,
        db_dump_name="database.sql.gz",
        expects_db=False,
    )

    assert result["verified"] is False
    assert "unsupported member type" in result["errors"][0]


def test_archive_verification_rejects_path_restore_cannot_handle(tmp_path: Path) -> None:
    archive_path = tmp_path / "unsafe-path.tar.gz"
    with tarfile.open(archive_path, "w:gz") as archive:
        regular = tarfile.TarInfo("source/../outside.txt")
        regular.size = 4
        archive.addfile(regular, io.BytesIO(b"safe"))

    result = verify_archive(
        archive_path,
        db_dump_name="database.sql.gz",
        expects_db=False,
    )

    assert result["verified"] is False
    assert "unsafe member path" in result["errors"][0]


def test_archive_verification_requires_exact_unique_database_member(tmp_path: Path) -> None:
    archive_path = tmp_path / "misleading.tar.gz"
    with tarfile.open(archive_path, "w:gz") as archive:
        regular = tarfile.TarInfo("source/notdatabase.sql.gz")
        regular.size = 4
        archive.addfile(regular, io.BytesIO(b"safe"))

    result = verify_archive(
        archive_path,
        db_dump_name="database.sql.gz",
        expects_db=True,
    )

    assert result["verified"] is False
    assert result["has_db"] is False
    assert result["errors"] == ["Critical: database.sql.gz missing"]


def test_infrastructure_layout_only_reserves_pgdumpall_member(tmp_path: Path) -> None:
    archive_path = tmp_path / "infrastructure.tar.gz"
    with tarfile.open(archive_path, "w:gz") as archive:
        regular = tarfile.TarInfo("infrastructure/database.sql.gz")
        regular.size = 4
        archive.addfile(regular, io.BytesIO(b"safe"))

    result = verify_archive(
        archive_path,
        db_dump_name="pgdumpall.sql.gz",
        expects_db=True,
    )

    assert result["verified"] is False
    assert result["has_db"] is False
    assert result["errors"] == ["Critical: pgdumpall.sql.gz missing"]


def test_archive_verification_rejects_empty_archive(tmp_path: Path) -> None:
    archive_path = tmp_path / "empty.tar.gz"
    with tarfile.open(archive_path, "w:gz"):
        pass

    result = verify_archive(
        archive_path,
        db_dump_name="database.sql.gz",
        expects_db=False,
    )

    assert result["verified"] is False
    assert result["errors"] == ["Critical: archive contains no regular files"]


def test_archive_verification_rejects_file_without_top_level_root(
    tmp_path: Path,
) -> None:
    archive_path = tmp_path / "rootless.tar.gz"
    with tarfile.open(archive_path, "w:gz") as archive:
        regular = tarfile.TarInfo("orphan.txt")
        regular.size = 4
        archive.addfile(regular, io.BytesIO(b"safe"))

    result = verify_archive(
        archive_path,
        db_dump_name="database.sql.gz",
        expects_db=False,
    )

    assert result["verified"] is False
    assert result["errors"] == [
        "Critical: archive files must use exactly one top-level directory"
    ]


@pytest.mark.parametrize("source_state", ["missing", "empty", "populated"])
@pytest.mark.parametrize("local_only", [False, True])
def test_native_backup_rejects_invalid_source_before_storage(tmp_path, monkeypatch, source_state, local_only):
    from app.tasks import backup_native, backup_native_archive
    project = tmp_path / "source"
    if source_state != "missing":
        project.mkdir()
    if source_state == "populated":
        (project / "note.txt").write_text("recoverable content\n")
    monkeypatch.setattr(backup_native_archive, "_dump_database", lambda *a: (0, False))
    store = Mock(return_value={"stored": True})
    monkeypatch.setattr(backup_native, "_store_local_project_archive", store)
    monkeypatch.setattr(backup_native, "_upload_project_archive", store)
    monkeypatch.setattr(backup_native, "_storage_config", lambda *a: None)
    if source_state == "populated":
        assert backup_native.run_project_backup(project_dir=str(project), source_id="source", local_only=local_only) == {"stored": True}
        assert store.call_count == 1
        assert store.call_args.args[2]["verification"]["verified"] is True
    else:
        with pytest.raises((RuntimeError, FileNotFoundError), match=r"does not exist|no regular files"):
            backup_native.run_project_backup(project_dir=str(project), source_id="source", local_only=local_only)
        store.assert_not_called()



def test_unreadable_subdirectory_cannot_produce_verified_partial_backup(tmp_path, monkeypatch):
    from app.tasks import backup_native, backup_native_archive
    project = tmp_path / "source"
    blocked = project / "private-data"
    blocked.mkdir(parents=True)
    (project / "readable.txt").write_text("partial content\n")
    (blocked / "important.txt").write_text("must be included\n")
    original_scandir = os.scandir
    def scandir(path):
        if not isinstance(path, int) and Path(path) == blocked:
            raise PermissionError("source permission denied")
        return original_scandir(path)
    monkeypatch.setattr(os, "scandir", scandir)
    monkeypatch.setattr(backup_native_archive, "_dump_database", lambda *a: (0, False))
    store = Mock()
    monkeypatch.setattr(backup_native, "_upload_project_archive", store)
    with pytest.raises(PermissionError, match="source permission denied"):
        backup_native.run_project_backup(project_dir=str(project), source_id="source")
    store.assert_not_called()
