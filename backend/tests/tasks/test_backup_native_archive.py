from __future__ import annotations

from pathlib import Path

import pytest


def test_dump_database_prefers_passed_pg_credentials(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Use supplied PGUSER/PGPASSWORD for pg_dump, not only process env."""
    from app.tasks import backup_native_archive

    monkeypatch.delenv("PGUSER", raising=False)
    monkeypatch.delenv("PGPASSWORD", raising=False)
    monkeypatch.setattr(backup_native_archive, "_read_env_file", lambda _path: {})
    env = {
        "DB_NAME": "summitflow",
        "DB_USER": "app_user",
        "DB_PASSWORD": "app_password",
        "PGUSER": "admin_user",
        "PGPASSWORD": "admin_password",
        "PGHOST": "db.local",
        "PGPORT": "5433",
    }

    def fake_run_gzip_stream(
        command: list[str],
        destination: Path,
        *,
        env: dict[str, str] | None,
        timeout: int,
    ) -> tuple[int, bytes]:
        assert command == [
            "pg_dump",
            "-U",
            "admin_user",
            "-h",
            "db.local",
            "-p",
            "5433",
            "summitflow",
        ]
        assert env is not None
        assert env["PGPASSWORD"] == "admin_password"
        assert timeout == backup_native_archive.BACKUP_TIMEOUT
        destination.write_bytes(b"dump")
        return 0, b""

    monkeypatch.setattr(
        backup_native_archive,
        "_run_gzip_stream",
        fake_run_gzip_stream,
    )

    db_bytes, expects_db = backup_native_archive._dump_database(
        "summitflow",
        tmp_path / "database.sql.gz",
        env,
    )

    assert db_bytes == 4
    assert expects_db
