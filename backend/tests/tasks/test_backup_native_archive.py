from __future__ import annotations

from pathlib import Path

import pytest


def test_project_can_include_durable_artifacts_without_including_caches(tmp_path: Path) -> None:
    import tarfile

    from app.tasks import backup_native_archive as archive

    document = tmp_path / "data/artifacts/resume.pdf"
    document.parent.mkdir(parents=True)
    document.write_bytes(b"%PDF-1.7")
    cache = tmp_path / "backend/.venv/cache"
    cache.parent.mkdir(parents=True)
    cache.write_text("cache")
    (tmp_path / ".backupignore").write_text("!data/artifacts\n*.log\n")
    with tarfile.open(tmp_path / "check.tar", "w") as output:
        archive._add_project_files(output, tmp_path, "example", archive._load_excludes(tmp_path))
    with tarfile.open(tmp_path / "check.tar") as result:
        assert "example/data/artifacts/resume.pdf" in result.getnames()
        assert "example/backend/.venv/cache" not in result.getnames()
    assert archive._should_exclude("data/artifacts/resume.pdf", archive.DEFAULT_EXCLUDES)


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


def test_rls_backup_uses_existing_admin_identity(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.tasks import backup_native_archive as archive

    monkeypatch.delenv("PGUSER", raising=False)
    monkeypatch.delenv("PGPASSWORD", raising=False)
    monkeypatch.delenv("POSTGRES_ADMIN_URL", raising=False)
    monkeypatch.setattr(archive, "_read_env_file", lambda _: {
        "POSTGRES_ADMIN_URL": "postgresql://backup_admin:fixture@localhost:5432/postgres",
    })
    def dump(command, destination, *, env, timeout):
        assert command[2] == "backup_admin"
        assert env["PGPASSWORD"] == "fixture"
        assert command[-1] == "jobinator"
        destination.write_bytes(b"dump")
        return 0, b""
    monkeypatch.setattr(archive, "_run_gzip_stream", dump)
    assert archive._dump_database("jobinator-4000", tmp_path / "db.gz", {
        "DB_NAME": "jobinator", "DB_PASSWORD": "app-fixture", "PGHOST": "127.0.0.1",
    }) == (4, True)
