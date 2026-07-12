"""Security tests for shell-free infrastructure archive validation."""

from __future__ import annotations

import gzip
import io
import tarfile
from pathlib import Path
from unittest.mock import patch

from app.tasks import backup_restore_test as restore_validation


def _write_archive(path: Path, members: list[tuple[str, bytes]]) -> None:
    with tarfile.open(path, "w:gz") as archive:
        for name, content in members:
            member = tarfile.TarInfo(name)
            member.size = len(content)
            archive.addfile(member, io.BytesIO(content))


def test_archive_headers_are_read_without_shell_commands(tmp_path: Path) -> None:
    archive = tmp_path / "infra.tar.gz"
    _write_archive(
        archive,
        [
            ("infrastructure/pgdumpall.sql.gz", gzip.compress(b"-- PostgreSQL dump\n")),
            ("infrastructure/configs/redis-dump.rdb", b"REDIS0011"),
        ],
    )

    with patch("app.tasks.backup_restore_test.subprocess.run") as run:
        assert restore_validation._validate_pgdump_header(str(archive)) is True
        assert restore_validation._validate_redis_header(str(archive)) is True

    run.assert_not_called()


def test_archive_header_validation_rejects_duplicate_database_members(
    tmp_path: Path,
) -> None:
    archive = tmp_path / "duplicate.tar.gz"
    content = gzip.compress(b"-- PostgreSQL dump\n")
    _write_archive(
        archive,
        [
            ("infrastructure/pgdumpall.sql.gz", content),
            ("infrastructure/nested/pgdumpall.sql.gz", content),
        ],
    )

    assert restore_validation._validate_pgdump_header(str(archive)) is False


def test_archive_header_validation_treats_missing_redis_dump_as_optional(
    tmp_path: Path,
) -> None:
    archive = tmp_path / "no-redis.tar.gz"
    _write_archive(
        archive,
        [("infrastructure/pgdumpall.sql.gz", gzip.compress(b"-- dump\n"))],
    )

    assert restore_validation._validate_redis_header(str(archive)) is True
