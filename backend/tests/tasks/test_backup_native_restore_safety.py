"""Security tests for native backup archive restoration."""

from __future__ import annotations

import gzip
import io
import stat
import tarfile
from pathlib import Path
from subprocess import CompletedProcess

import pytest

from app.tasks.backup_native_restore import preview_restore_archive, restore_archive


def _archive_path(
    tmp_path: Path,
    members: list[tuple[str, bytes, bytes, str | None]],
    *,
    modes: dict[str, int] | None = None,
) -> Path:
    """Create a gzip archive from in-memory TarInfo definitions."""
    path = tmp_path / "backup.tar.gz"
    with tarfile.open(path, "w:gz") as archive:
        for name, member_type, content, linkname in members:
            info = tarfile.TarInfo(name)
            info.type = member_type
            info.linkname = linkname or ""
            if modes and name in modes:
                info.mode = modes[name]
            info.size = len(content) if member_type == tarfile.REGTYPE else 0
            source = io.BytesIO(content) if member_type == tarfile.REGTYPE else None
            archive.addfile(info, source)
    return path


def _file(name: str, content: bytes = b"safe\n") -> tuple[str, bytes, bytes, None]:
    return (name, tarfile.REGTYPE, content, None)


def test_restore_extracts_valid_single_root_archive(tmp_path: Path) -> None:
    archive = _archive_path(tmp_path, [_file("source/docs/readme.txt", b"restored\n")])
    destination = tmp_path / "project"

    result = restore_archive(
        archive,
        destination,
        dry_run=False,
        files_only=True,
    )

    assert result["status"] == "completed"
    assert (destination / "docs" / "readme.txt").read_bytes() == b"restored\n"


def test_restore_preserves_executable_bits_but_strips_privileged_bits(tmp_path: Path) -> None:
    member_name = "source/bin/run.sh"
    archive = _archive_path(
        tmp_path,
        [_file(member_name, b"#!/bin/sh\n")],
        modes={member_name: 0o6755},
    )
    destination = tmp_path / "project"

    restore_archive(archive, destination, dry_run=False, files_only=True)

    restored_mode = stat.S_IMODE((destination / "bin" / "run.sh").stat().st_mode)
    assert restored_mode == 0o755


@pytest.mark.parametrize(
    "member_name",
    [
        "source/../project-evil/pwn.txt",
        "source/subdir/../../project-evil/pwn.txt",
        "/source/pwn.txt",
    ],
)
def test_restore_rejects_traversal_and_absolute_paths_before_writing(
    tmp_path: Path,
    member_name: str,
) -> None:
    archive = _archive_path(tmp_path, [_file(member_name, b"pwned\n")])
    destination = tmp_path / "project"

    with pytest.raises(RuntimeError, match="Unsafe archive path"):
        restore_archive(archive, destination, dry_run=False, files_only=True)

    assert not (tmp_path / "project-evil" / "pwn.txt").exists()
    assert not destination.exists()


def test_restore_rejects_existing_destination_symlink_escape(tmp_path: Path) -> None:
    archive = _archive_path(tmp_path, [_file("source/linked/pwn.txt", b"pwned\n")])
    destination = tmp_path / "project"
    outside = tmp_path / "outside"
    destination.mkdir()
    outside.mkdir()
    (destination / "linked").symlink_to(outside, target_is_directory=True)

    with pytest.raises(RuntimeError, match="Unsafe archive path"):
        restore_archive(archive, destination, dry_run=False, files_only=True)

    assert not (outside / "pwn.txt").exists()


@pytest.mark.parametrize(
    ("member_type", "linkname"),
    [
        (tarfile.SYMTYPE, "../../outside"),
        (tarfile.LNKTYPE, "../../outside"),
        (tarfile.CHRTYPE, None),
        (tarfile.BLKTYPE, None),
        (tarfile.FIFOTYPE, None),
    ],
)
def test_restore_rejects_links_and_device_members(
    tmp_path: Path,
    member_type: bytes,
    linkname: str | None,
) -> None:
    archive = _archive_path(
        tmp_path,
        [("source/unsafe", member_type, b"", linkname)],
    )

    with pytest.raises(RuntimeError, match="Unsafe archive member type"):
        restore_archive(
            archive,
            tmp_path / "project",
            dry_run=False,
            files_only=True,
        )


def test_restore_rejects_multiple_top_level_directories(tmp_path: Path) -> None:
    archive = _archive_path(
        tmp_path,
        [_file("source/a.txt"), _file("other/b.txt")],
    )

    with pytest.raises(RuntimeError, match="exactly one top-level"):
        restore_archive(
            archive,
            tmp_path / "project",
            dry_run=False,
            files_only=True,
        )


def test_noncanonical_infrastructure_dump_name_is_an_ordinary_file(
    tmp_path: Path,
) -> None:
    archive = _archive_path(
        tmp_path,
        [_file("wrong/pgdumpall.sql.gz", b"not-used")],
    )
    destination = tmp_path / "project"

    result = restore_archive(
        archive,
        destination,
        dry_run=False,
        files_only=True,
    )

    assert result["db_restored"] is None
    assert (destination / "pgdumpall.sql.gz").read_bytes() == b"not-used"


@pytest.mark.parametrize(
    ("member_name", "restored_path"),
    [
        ("source/nested/database.sql.gz", "nested/database.sql.gz"),
        ("infrastructure/database.sql.gz", "database.sql.gz"),
        (
            "infrastructure/configs/pgdumpall.sql.gz",
            "configs/pgdumpall.sql.gz",
        ),
    ],
)
def test_nested_database_dump_names_are_restored_as_ordinary_files(
    tmp_path: Path,
    member_name: str,
    restored_path: str,
) -> None:
    archive = _archive_path(tmp_path, [_file(member_name, b"not-used")])
    destination = tmp_path / "project"

    result = restore_archive(
        archive,
        destination,
        dry_run=False,
        files_only=True,
    )

    assert result["db_restored"] is None
    assert (destination / restored_path).read_bytes() == b"not-used"


def test_restore_rejects_duplicate_canonical_database_dump(tmp_path: Path) -> None:
    archive = _archive_path(
        tmp_path,
        [
            _file("source/database.sql.gz", b"first"),
            _file("source/database.sql.gz", b"second"),
        ],
    )

    with pytest.raises(RuntimeError, match="at most one database dump"):
        restore_archive(
            archive,
            tmp_path / "project",
            dry_run=False,
            files_only=True,
        )


def test_restore_rejects_duplicate_ordinary_path(tmp_path: Path) -> None:
    archive = _archive_path(
        tmp_path,
        [
            _file("source/docs/readme.txt", b"first"),
            _file("source/docs/readme.txt", b"second"),
        ],
    )

    with pytest.raises(RuntimeError, match="duplicate path"):
        restore_archive(
            archive,
            tmp_path / "project",
            dry_run=False,
            files_only=True,
        )


def test_restore_rejects_file_directory_collision(tmp_path: Path) -> None:
    archive = _archive_path(
        tmp_path,
        [
            _file("source/config", b"file"),
            _file("source/config/settings.json", b"{}"),
        ],
    )

    with pytest.raises(RuntimeError, match="file/directory collision"):
        restore_archive(
            archive,
            tmp_path / "project",
            dry_run=False,
            files_only=True,
        )


def test_restore_prevalidates_all_destination_targets_before_writing(
    tmp_path: Path,
) -> None:
    archive = _archive_path(
        tmp_path,
        [
            _file("source/first.txt", b"must-not-be-written"),
            _file("source/linked/pwn.txt", b"pwned"),
        ],
    )
    destination = tmp_path / "project"
    outside = tmp_path / "outside"
    destination.mkdir()
    outside.mkdir()
    (destination / "linked").symlink_to(outside, target_is_directory=True)

    with pytest.raises(RuntimeError, match="Unsafe archive path"):
        restore_archive(archive, destination, dry_run=False, files_only=True)

    assert not (destination / "first.txt").exists()
    assert not (outside / "pwn.txt").exists()


def test_restore_prevalidates_existing_destination_type_collisions(
    tmp_path: Path,
) -> None:
    archive = _archive_path(
        tmp_path,
        [
            _file("source/first.txt", b"must-not-be-written"),
            ("source/config", tarfile.DIRTYPE, b"", None),
        ],
    )
    destination = tmp_path / "project"
    destination.mkdir()
    (destination / "config").write_text("existing file")

    with pytest.raises(RuntimeError, match="directory conflicts with existing file"):
        restore_archive(archive, destination, dry_run=False, files_only=True)

    assert not (destination / "first.txt").exists()


def test_database_restore_streams_decompressed_dump_from_disk(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sql = b"CREATE TABLE restored(id integer);\n" * 1000
    archive = _archive_path(
        tmp_path,
        [_file("source/database.sql.gz", gzip.compress(sql))],
    )
    observed: dict[str, object] = {}

    monkeypatch.setattr(
        "app.tasks.backup_native_restore._load_db_config",
        lambda _name, _env: {
            "user": "summitflow",
            "password": "secret",
            "host": "localhost",
            "port": "5432",
            "name": "summitflow",
        },
    )

    def fake_run(command, **kwargs):
        observed["command"] = command
        observed["input"] = kwargs["stdin"].read()
        assert "input" not in kwargs
        return CompletedProcess(command, 0, stdout=b"", stderr=b"")

    monkeypatch.setattr("app.tasks.backup_native_restore.subprocess.run", fake_run)

    result = restore_archive(archive, tmp_path / "project", dry_run=False)

    assert result["db_restored"] == "database.sql.gz"
    assert observed["input"] == sql
    command = observed["command"]
    assert isinstance(command, list)
    assert command[-2:] == ["-v", "ON_ERROR_STOP=1"]


def test_database_like_suffix_is_restored_as_an_ordinary_file(tmp_path: Path) -> None:
    archive = _archive_path(
        tmp_path,
        [_file("source/notdatabase.sql.gz", b"ordinary\n")],
    )
    destination = tmp_path / "project"

    result = restore_archive(
        archive,
        destination,
        dry_run=False,
        files_only=True,
    )

    assert result["db_restored"] is None
    assert (destination / "notdatabase.sql.gz").read_bytes() == b"ordinary\n"


def test_preview_rejects_unsafe_archive_layout(tmp_path: Path) -> None:
    archive = _archive_path(
        tmp_path,
        [_file("source/../project-evil/pwn.txt", b"pwned\n")],
    )

    with pytest.raises(RuntimeError, match="Unsafe archive path"):
        preview_restore_archive(archive, files_only=True)
