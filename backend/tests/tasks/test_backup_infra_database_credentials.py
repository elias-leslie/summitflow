"""Infrastructure dumps use the same existing admin secret as project dumps."""

from pathlib import Path

import pytest

from app.tasks import backup_native_infra as infra


@pytest.fixture
def native_database(monkeypatch):
    for key in ("PGUSER", "PGPASSWORD", "PGHOST", "PGPORT", "POSTGRES_ADMIN_URL", "POSTGRES_CONTAINER"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(infra, "_find_compose_container", lambda _: None)


def test_infrastructure_uses_existing_file_admin_secret(tmp_path, monkeypatch, native_database):
    home = tmp_path / "home"
    home.mkdir()
    (home / ".env.local").write_text("POSTGRES_ADMIN_URL=postgresql://backup_admin:fixture%40secret@localhost:5433/postgres\n")
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))

    def dump(command, destination, *, env, timeout):
        assert command == ["pg_dumpall", "-U", "backup_admin", "-h", "localhost", "-p", "5433"]
        assert env["PGPASSWORD"] == "fixture@secret"
        assert all("secret" not in word for word in command)
        destination.write_bytes(b"SQL")
        return 0, b""

    monkeypatch.setattr(infra, "_run_plain_stream", dump)
    assert infra._dump_infra_database(tmp_path / "all.sql") == 3


def test_explicit_pg_credentials_keep_precedence(tmp_path, monkeypatch, native_database):
    for key, value in {"PGUSER": "explicit", "PGPASSWORD": "synthetic", "PGHOST": "db.invalid", "PGPORT": "5434",
                       "POSTGRES_ADMIN_URL": "postgresql://other:unused@elsewhere.invalid/postgres"}.items():
        monkeypatch.setenv(key, value)

    def dump(command, destination, *, env, timeout):
        assert command == ["pg_dumpall", "-U", "explicit", "-h", "db.invalid", "-p", "5434"]
        assert env["PGPASSWORD"] == "synthetic"
        destination.write_bytes(b"SQL")
        return 0, b""

    monkeypatch.setattr(infra, "_run_plain_stream", dump)
    assert infra._dump_infra_database(tmp_path / "all.sql") == 3


@pytest.mark.parametrize("endpoint", [{"PGHOST": "other.invalid"}, {"PGPORT": "5434"}])
def test_admin_endpoint_mismatch_refuses_before_dump(tmp_path, monkeypatch, native_database, endpoint):
    monkeypatch.setenv("POSTGRES_ADMIN_URL", "postgresql://backup:synthetic@localhost:5432/postgres")
    for key, value in endpoint.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setattr(infra, "_run_plain_stream", lambda *args, **kwargs: pytest.fail("must refuse before dump"))
    with pytest.raises(RuntimeError, match="endpoints differ"):
        infra._dump_infra_database(tmp_path / "all.sql")


@pytest.mark.parametrize("admin_url", ["", "postgresql://backup@localhost/postgres"])
def test_missing_credentials_fail_without_prompting(tmp_path, monkeypatch, native_database, admin_url):
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    monkeypatch.setenv("POSTGRES_ADMIN_URL", admin_url)
    monkeypatch.setattr(infra, "_run_plain_stream", lambda *args, **kwargs: pytest.fail("must refuse before dump"))
    with pytest.raises(RuntimeError, match="credentials are unavailable"):
        infra._dump_infra_database(tmp_path / "all.sql")
