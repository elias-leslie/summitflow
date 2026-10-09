"""The canonical fixture owns only its disposable database and cleans up failures."""

from __future__ import annotations

import json
import subprocess
import tomllib
from pathlib import Path
from unittest.mock import MagicMock
from urllib.parse import parse_qs, urlsplit

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
    with pytest.raises(RuntimeError, match="stage bound"), fixture.database_fixture(lifetime_seconds=2131):
        pytest.fail("Unbounded fixture must never start")


def test_python_stage_has_measured_budget_and_bounded_cleanup_reserves(prepared_fixture, monkeypatch):
    root, operations, _connection = prepared_fixture
    config = Path(__file__).resolve().parents[3] / ".st-check.toml"
    stage = next(stage for stage in tomllib.loads(config.read_text())["native"]["stages"] if stage["id"] == "python")
    runs = []

    def run(command, **kwargs):
        runs.append((command, kwargs))
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(fixture.sys, "argv", ["native_check_fixture.py", "python"])
    monkeypatch.setattr(fixture.subprocess, "run", run)

    assert fixture.main() == 0
    assert runs[0][1]["timeout"] == 180
    # 19.2% headroom over the measured 1560s exhaustion, not an unbounded retry.
    assert runs[1][1]["timeout"] == 1860
    assert {argument.removeprefix("--deselect=") for argument in runs[1][0]
            if argument.startswith("--deselect=")} == {
        "tests/cli/test_saved_work_snapshots.py::test_native_btrfs_shared_capture_readonly_recovery_and_isolated_restore",
        "tests/cli/test_saved_work_snapshots.py::test_native_nested_saved_source_is_refused_and_disposable_tracked_fixture_preserved",
    }
    # A short private pytest base keeps tmp_path AF_UNIX sockets under the
    # 108-byte limit when TMPDIR is deep mounted scratch.
    basetemp = Path(next(argument for argument in runs[1][0] if argument.startswith("--basetemp="))
                    .removeprefix("--basetemp="))
    assert basetemp.parent == Path(fixture.tempfile.gettempdir()) and len(basetemp.name) <= 8
    assert not basetemp.exists()
    owner = next(item for item in tomllib.loads(config.read_text())["native"]["stages"]
                 if item["id"] == "owner-btrfs-snapshots")
    assert owner["required"] is False and owner["applicable"] is False
    assert "ST_SNAPSHOT_TEST_ROOT" in owner["reason"]
    create = next(arguments for arguments, _env in operations if arguments[0] == "create")
    assert "sleep 2130; kill -TERM 1" in create[-1]
    ledger = next((root / ".dev-tools" / "native-fixtures").glob("*.json"))
    assert json.loads(ledger.read_text())["maximum_lifetime_seconds"] == 2130
    # The fixture retains bootstrap/readiness/cleanup (180+60+30); the outer
    # stage also reserves image inspection/create/start (3x30s).
    assert stage["timeout_seconds"] == 2220


def test_python_timeout_still_removes_only_its_bounded_fixture(prepared_fixture, monkeypatch):
    root, operations, _connection = prepared_fixture

    def run(command, **kwargs):
        if "-m" in command:
            raise subprocess.TimeoutExpired(command, kwargs["timeout"])
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(fixture.sys, "argv", ["native_check_fixture.py", "python"])
    monkeypatch.setattr(fixture.subprocess, "run", run)

    with pytest.raises(subprocess.TimeoutExpired) as error:
        fixture.main()
    assert error.value.timeout == 1860
    create = next(arguments for arguments, _env in operations if arguments[0] == "create")
    name = create[create.index("--name") + 1]
    assert operations[-1][0] == ("rm", "--force", name)
    ledger = json.loads((root / ".dev-tools" / "native-fixtures" / (name + ".json")).read_text())
    assert ledger["state"] == "removed"
    assert ledger["maximum_lifetime_seconds"] == 2130


def test_fixture_maps_docker_host_mount_but_keeps_sandbox_socket_url(prepared_fixture, monkeypatch, tmp_path):
    _root, operations, _connection = prepared_fixture
    host = tmp_path / "host-scratch"
    host.mkdir()
    monkeypatch.setenv("ST_NATIVE_TMP_HOST_ROOT", str(host))

    with fixture.database_fixture(lifetime_seconds=210) as environment:
        socket = Path(parse_qs(urlsplit(environment["DATABASE_URL"]).query)["host"][0])
        create = next(arguments for arguments, _env in operations if arguments[0] == "create")
        mount = create[create.index("--mount") + 1]
        # The mapping names this process's private /tmp even when TMPDIR is
        # deep host scratch, as in direct native stages.
        assert socket.is_relative_to("/tmp")
        assert mount == f"type=bind,source={host / socket.relative_to('/tmp')},target=/var/run/postgresql"
        assert str(host) not in environment["DATABASE_URL"]


@pytest.mark.parametrize("mapping", ["relative", "/tmp", "/var/tmp/../tmp"])
def test_fixture_rejects_invalid_host_scratch_mapping_before_container_create(prepared_fixture, monkeypatch, mapping):
    _root, operations, _connection = prepared_fixture
    monkeypatch.setenv("ST_NATIVE_TMP_HOST_ROOT", mapping)
    with pytest.raises(RuntimeError, match="scratch mapping"), fixture.database_fixture(lifetime_seconds=210):
        pytest.fail("Invalid mapping must never reach Docker create")
    assert all(arguments[0] != "create" for arguments, _env in operations)


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
