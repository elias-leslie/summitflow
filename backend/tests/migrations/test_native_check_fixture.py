"""The canonical fixture owns only its disposable database and cleans up failures."""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from scripts import native_check_fixture as fixture


@pytest.fixture
def prepared_fixture(tmp_path, monkeypatch):
    monkeypatch.setattr(fixture, "ROOT", tmp_path)
    image = "sha256:" + "a" * 64
    image_lock = tmp_path / "image.lock"
    image_lock.write_text(image + "\n")
    monkeypatch.setattr(fixture, "IMAGE_LOCK", image_lock)
    operations = []

    def docker(*arguments, environment=None):
        operations.append((arguments, environment))
        return image if arguments[:2] == ("image", "inspect") else "fixture-id"

    monkeypatch.setattr(fixture, "docker", docker)
    connection = MagicMock()
    connection.__enter__.return_value = connection
    connection.execute.return_value.fetchone.return_value = (0,)
    monkeypatch.setattr(fixture.psycopg, "connect", MagicMock(return_value=connection))
    return tmp_path, operations, connection


def test_fixture_is_pinned_empty_private_and_removed(prepared_fixture, monkeypatch):
    root, operations, connection = prepared_fixture
    monkeypatch.setenv("DATABASE_URL", "postgresql://production.invalid/production")
    monkeypatch.setenv("DATABASE_ADMIN_URL", "production-admin")
    with fixture.database_fixture(lifetime_seconds=210) as environment:
        assert "/summitflow_test?host=" in environment["TEST_DATABASE_URL"]
        assert environment["DATABASE_URL"] == environment["TEST_DATABASE_URL"]
        assert environment["DATABASE_ADMIN_URL"] == ""
        assert not (fixture.Path(environment["HOME"]) / ".env.local").exists()
        create, docker_env = next(operation for operation in operations if operation[0][0] == "create")
        assert create[create.index("--network") + 1] == "none"
        assert create[create.index("--pull") + 1] == "never"
        assert "--read-only" in create
        assert "sleep 210; kill -TERM 1" in create[-1]
        assert docker_env["POSTGRES_PASSWORD"] not in " ".join(create)
        assert str(root) not in create[create.index("--mount") + 1]
        connection.execute.assert_called_once()
    assert operations[-1][0][:2] == ("rm", "--force")
    ledger = next((root / ".dev-tools" / "native-fixtures").glob("*.json"))
    data = json.loads(ledger.read_text())
    assert data["state"] == "removed" and data["maximum_lifetime_seconds"] == 210
    assert docker_env["POSTGRES_PASSWORD"] not in ledger.read_text()


def test_interruption_removes_only_current_fixture(prepared_fixture):
    _root, operations, _connection = prepared_fixture
    with pytest.raises(KeyboardInterrupt), fixture.database_fixture():
        raise KeyboardInterrupt
    create = next(arguments for arguments, _env in operations if arguments[0] == "create")
    name = create[create.index("--name") + 1]
    assert operations[-1][0] == ("rm", "--force", name)


def test_fixture_rejects_nonempty_database_before_yield(prepared_fixture):
    _root, operations, connection = prepared_fixture
    connection.execute.return_value.fetchone.return_value = (1,)
    with pytest.raises(RuntimeError, match="not entirely empty"), fixture.database_fixture():
        pytest.fail("Nonempty database must never be provided to schema checks")
    assert operations[-1][0][:2] == ("rm", "--force")


def test_fixture_refuses_unavailable_image_without_create(prepared_fixture, monkeypatch):
    _root, operations, _connection = prepared_fixture
    monkeypatch.setattr(fixture, "docker", lambda *_args, **_kwargs: "changed-image")
    with pytest.raises(RuntimeError, match="preparation must be explicit"), fixture.database_fixture():
        pytest.fail("Fixture must not pull or substitute an image")
    assert operations == []


def test_fixture_lifetime_cannot_exceed_stage_bound():
    with pytest.raises(RuntimeError, match="stage bound"), fixture.database_fixture(lifetime_seconds=1801):
        pytest.fail("Unbounded fixture must never start")


def test_fixture_cleanup_failure_is_visible_and_bounded(prepared_fixture, monkeypatch):
    root, _operations, _connection = prepared_fixture
    original = fixture.docker

    def docker(*arguments, **kwargs):
        if arguments[0] == "rm":
            raise RuntimeError("Fixture cleanup unavailable")
        return original(*arguments, **kwargs)

    monkeypatch.setattr(fixture, "docker", docker)
    with pytest.raises(RuntimeError, match="cleanup unavailable"), fixture.database_fixture(lifetime_seconds=210):
        pass
    ledger = next((root / ".dev-tools" / "native-fixtures").glob("*.json"))
    data = json.loads(ledger.read_text())
    assert data["state"] == "cleanup_unavailable_watchdog_bounded"
    assert data["maximum_lifetime_seconds"] == 210
