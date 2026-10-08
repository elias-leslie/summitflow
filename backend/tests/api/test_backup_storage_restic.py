"""Pilot backend configuration rejects secrets and unsafe repository scope."""

from __future__ import annotations

import sys
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException
from starlette.requests import Request


@pytest.fixture
def repository_config(monkeypatch):
    from app.api.backups import storage_endpoints as endpoints

    monkeypatch.setattr(endpoints, "backup_key_directory", lambda: Path("/fixture/keys"))
    return {
        "engine": "restic", "restic_local_repository": "/fixture/repository",
        "restic_local_password_file": "/fixture/keys/local-password",
        "restic_key_directory": "/fixture/keys",
    }


@pytest.fixture
def backend(repository_config):
    return {
        "id": "pilot", "name": "Pilot", "backend_type": "local", "config": repository_config,
        "is_default": False, "enabled": True, "last_test_at": None, "last_test_ok": None,
        "created_at": None, "updated_at": None,
    }


@pytest.mark.asyncio
async def test_create_restic_backend_stores_only_refs_and_stays_nondefault(monkeypatch, backend, repository_config):
    from app.api.backups import storage_endpoints as endpoints
    from app.api.backups.models import StorageBackendCreate

    create = MagicMock(return_value=backend)
    credentials = MagicMock(side_effect=AssertionError("No inline credentials may be written"))
    monkeypatch.setattr(endpoints.backup_store, "create_backend", create)
    monkeypatch.setattr(endpoints, "_write_smb_credentials", credentials)
    result = await endpoints.create_storage_backend(StorageBackendCreate(
        name="Pilot", backend_type="local", config=repository_config,
    ))
    assert result.is_default is False
    create.assert_called_once_with(name="Pilot", backend_type="local", config=repository_config, is_default=False)
    credentials.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("settings", [
    {"password": "fixture-inline-secret"},
    {"restic_password": "fixture-inline-secret"},
    {"token": "fixture-inline-secret"},
    {"restic_rclone_config": {"token": "fixture-inline-secret"}},
    {"engine": ["restic"]},
    {"restic_local_repository": "relative/repository"},
    {"restic_local_repository": "/"},
    {"restic_local_password_file": "relative/password"},
    {"restic_key_directory": None},
    {"restic_key_directory": "/outside/private"},
    {"restic_local_password_file": "/outside/local-password"},
    {"restic_rclone_config": "/fixture/keys/nested/rclone.conf"},
    {"restic_remote_repository": "rclone:drive:"},
    {"restic_remote_repository": "rclone:drive:/"},
    {"restic_remote_repository": "rclone:drive:."},
    {"restic_remote_repository": "rclone:drive:folder/../other"},
    {"restic_remote_repository": "rclone::drive,token=fixture-inline-secret:/folder"},
    {"restic_remote_repository": "https://user:fixture-inline-secret@example.invalid/repo"},
    {"restic_remote_repository": "/fixture/repository"},
    {"restic_remote_repository": "/fixture/repository/child"},
    {"restic_remote_repository": "/fixture"},
])
async def test_create_rejects_unsafe_configuration_before_any_write(monkeypatch, repository_config, settings):
    from app.api.backups import storage_endpoints as endpoints
    from app.api.backups.models import StorageBackendCreate

    create = MagicMock()
    credentials = MagicMock()
    monkeypatch.setattr(endpoints.backup_store, "create_backend", create)
    monkeypatch.setattr(endpoints, "_write_smb_credentials", credentials)
    config = {
        **repository_config, "restic_remote_password_file": "/fixture/keys/remote-password",
        "restic_rclone_config": "/fixture/keys/rclone.conf", **settings,
    }
    with pytest.raises(HTTPException) as error:
        await endpoints.create_storage_backend(StorageBackendCreate(name="Pilot", backend_type="local", config=config))
    assert error.value.status_code == 400
    assert "fixture-inline-secret" not in error.value.detail
    create.assert_not_called()
    credentials.assert_not_called()


@pytest.mark.asyncio
async def test_restic_is_rejected_for_smb_before_credential_write(monkeypatch, repository_config):
    from app.api.backups import storage_endpoints as endpoints
    from app.api.backups.models import StorageBackendCreate

    credentials = MagicMock()
    monkeypatch.setattr(endpoints, "_write_smb_credentials", credentials)
    with pytest.raises(HTTPException) as error:
        await endpoints.create_storage_backend(StorageBackendCreate(name="Pilot", backend_type="smb", config=repository_config))
    assert error.value.status_code == 400
    credentials.assert_not_called()


@pytest.mark.asyncio
async def test_update_rejects_inline_secret_before_any_write(monkeypatch, backend, repository_config):
    from app.api.backups import storage_endpoints as endpoints
    from app.api.backups.models import StorageBackendUpdate

    monkeypatch.setattr(endpoints.backup_store, "get_backend", lambda _: backend)
    update = MagicMock()
    credentials = MagicMock()
    monkeypatch.setattr(endpoints.backup_store, "update_backend", update)
    monkeypatch.setattr(endpoints, "_write_smb_credentials", credentials)
    with pytest.raises(HTTPException):
        await endpoints.update_storage_backend("pilot", StorageBackendUpdate(config={**repository_config, "password": "fixture-inline-secret"}))
    update.assert_not_called()
    credentials.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("replacement", [
    {"restic_local_repository": "/fixture/changed-repository"},
    {"restic_local_password_file": "/fixture/keys/changed-password"},
    {"engine": "native", "root_path": "/backup"},
])
async def test_retained_backups_make_repository_identity_immutable(monkeypatch, backend, repository_config, replacement):
    from app.api.backups import storage_endpoints as endpoints
    from app.api.backups.models import StorageBackendUpdate

    monkeypatch.setattr(endpoints.backup_store, "get_backend", lambda _: backend)
    referenced = MagicMock(return_value=True)
    monkeypatch.setattr(endpoints.backup_store, "backend_has_backups", referenced)
    update = MagicMock()
    monkeypatch.setattr(endpoints.backup_store, "update_backend", update)
    config = replacement if replacement.get("engine") == "native" else {**repository_config, **replacement}
    with pytest.raises(HTTPException) as error:
        await endpoints.update_storage_backend("pilot", StorageBackendUpdate(config=config))
    assert error.value.status_code == 409
    referenced.assert_called_once_with("pilot")
    update.assert_not_called()


@pytest.mark.asyncio
async def test_referenced_repository_metadata_and_qualification_can_change(monkeypatch, backend, repository_config):
    from app.api.backups import storage_endpoints as endpoints
    from app.api.backups.models import StorageBackendUpdate

    monkeypatch.setattr(endpoints.backup_store, "get_backend", lambda _: backend)
    referenced = MagicMock(return_value=True)
    monkeypatch.setattr(endpoints.backup_store, "backend_has_backups", referenced)
    update = MagicMock(return_value=backend)
    monkeypatch.setattr(endpoints.backup_store, "update_backend", update)
    config = {**repository_config, "restic_offsite_prune_qualified": True, "restic_automatic_maintenance": False}
    await endpoints.update_storage_backend("pilot", StorageBackendUpdate(name="Renamed", enabled=False, config=config))
    update.assert_called_once_with("pilot", name="Renamed", enabled=False, config=config)
    referenced.assert_not_called()


@pytest.mark.asyncio
async def test_backend_deletion_is_blocked_while_backups_reference_it(monkeypatch, backend):
    from app.api.backups import storage_endpoints as endpoints

    monkeypatch.setattr(endpoints.backup_store, "get_backend", lambda _: backend)
    monkeypatch.setattr(endpoints.backup_store, "backend_has_backups", lambda _: True)
    delete = MagicMock()
    monkeypatch.setattr(endpoints.backup_store, "delete_backend", delete)
    with pytest.raises(HTTPException) as error:
        await endpoints.delete_storage_backend("pilot")
    assert error.value.status_code == 409
    delete.assert_not_called()


@pytest.mark.parametrize("row,expected", [((True,), True), ((False,), False), (None, False)])
def test_backend_reference_lookup_uses_bound_id(monkeypatch, row, expected):
    from app.storage.backups import storage_backends

    cursor = MagicMock()
    cursor.fetchone.return_value = row
    monkeypatch.setattr(storage_backends, "get_cursor", lambda: nullcontext(cursor))
    assert storage_backends.backend_has_backups("pilot") is expected
    cursor.execute.assert_called_once_with("SELECT EXISTS(SELECT 1 FROM backups WHERE storage_backend_id = %s)", ("pilot",))


@pytest.mark.asyncio
@pytest.mark.parametrize("remote", ["rclone:drive:SummitFlow/restic", "/fixture/independent-repository"])
async def test_bounded_independent_remote_refs_are_accepted(monkeypatch, backend, repository_config, remote):
    from app.api.backups import storage_endpoints as endpoints
    from app.api.backups.models import StorageBackendCreate

    config = {
        **repository_config, "restic_remote_repository": remote,
        "restic_remote_password_file": "/fixture/keys/remote-password", "restic_rclone_config": "/fixture/keys/rclone.conf",
    }
    monkeypatch.setattr(endpoints.backup_store, "create_backend", lambda **values: {**backend, "config": values["config"]})
    result = await endpoints.create_storage_backend(StorageBackendCreate(name="Pilot", backend_type="local", config=config))
    assert result.config == config


@pytest.mark.asyncio
@pytest.mark.parametrize("ready", [True, False])
@pytest.mark.parametrize("remote", [None, "rclone:drive:SummitFlow/restic"])
async def test_restic_probe_checks_readiness_without_age_or_initialization(monkeypatch, backend, ready, remote):
    from app.api.backups import storage_endpoints as endpoints

    if remote:
        backend["config"].update(
            restic_remote_repository=remote, restic_remote_password_file="/fixture/keys/remote-password",
            restic_rclone_config="/fixture/keys/rclone.conf",
        )
    monkeypatch.setattr(endpoints.backup_store, "get_backend", lambda _: backend)
    update = MagicMock()
    monkeypatch.setattr(endpoints.backup_store, "update_test_result", update)
    age = MagicMock(side_effect=AssertionError("Restic does not require age"))
    monkeypatch.setattr(endpoints, "get_backup_key_status", age)
    readiness = MagicMock(return_value={"ready": ready, "error": "pinned binary unavailable"})
    adapter = MagicMock(return_value=SimpleNamespace(readiness=readiness))
    monkeypatch.setattr(endpoints, "ResticAdapter", adapter)

    result = await endpoints.test_storage_backend("pilot")

    assert result["success"] is ready
    assert result["encryption_ready"] is ready
    assert result["offsite_success"] is None
    assert result["offsite_ready"] is (ready if remote else None)
    assert result["repository_connectivity_checked"] is False
    readiness.assert_called_once_with(local_only=remote is None)
    update.assert_called_once_with("pilot", ready)
    age.assert_not_called()


@pytest.fixture
def repository_runtime(monkeypatch, backend):
    from app.api.backups import storage_endpoints as endpoints

    runtime = SimpleNamespace(
        initialize_repository=MagicMock(return_value={"status": "initialized"}),
        repository_status=MagicMock(return_value={"status": "ready"}),
        maintain_repository=MagicMock(return_value={"status": "preview"}),
    )
    monkeypatch.setitem(sys.modules, "app.tasks.backup_repository_runtime", runtime)
    monkeypatch.setattr(endpoints.backup_store, "get_backend", lambda _: backend)
    monkeypatch.setattr(endpoints, "require_owner", MagicMock())
    return endpoints, runtime


@pytest.mark.asyncio
async def test_repository_operations_forward_selected_environment_and_preview_default(repository_runtime):
    endpoints, runtime = repository_runtime
    request = Request({"type": "http"})
    await endpoints.initialize_storage_repository("pilot", request, local_only=True)
    await endpoints.storage_repository_status("pilot")
    await endpoints.maintain_storage_repository("pilot", request)

    env = {
        "STORAGE_BACKEND_TYPE": "local", "BACKUP_ENGINE": "restic", "BACKUP_STORAGE_BACKEND_ID": "pilot",
        "RESTIC_LOCAL_REPOSITORY": "/fixture/repository", "RESTIC_LOCAL_PASSWORD_FILE": "/fixture/keys/local-password",
        "RESTIC_KEY_DIRECTORY": "/fixture/keys",
    }
    runtime.initialize_repository.assert_called_once_with(env, local_only=True)
    runtime.repository_status.assert_called_once_with(env)
    runtime.maintain_repository.assert_called_once_with(env, dry_run=True, force_critical_restore=False)


@pytest.mark.asyncio
async def test_credentials_in_immediate_private_subdirectory_are_accepted(monkeypatch, backend, repository_config):
    from app.api.backups import storage_endpoints as endpoints
    from app.api.backups.models import StorageBackendCreate

    config = {
        **repository_config, "restic_key_directory": "/fixture/keys/restic",
        "restic_local_password_file": "/fixture/keys/restic/local-password",
    }
    monkeypatch.setattr(endpoints.backup_store, "create_backend", lambda **values: {**backend, "config": values["config"]})
    result = await endpoints.create_storage_backend(StorageBackendCreate(name="Pilot", backend_type="local", config=config))
    assert result.config == config


@pytest.mark.parametrize("path,operation,expected", [
    ("/api/backup-storage/pilot/initialize?local_only=true", "initialize_repository", {"local_only": True}),
    ("/api/backup-storage/pilot/maintenance", "maintain_repository", {"dry_run": True, "force_critical_restore": False}),
    ("/api/backup-storage/pilot/maintenance?dry_run=false", "maintain_repository", {"dry_run": False, "force_critical_restore": False}),
    ("/api/backup-storage/pilot/maintenance?force_critical_restore=true", "maintain_repository", {"dry_run": True, "force_critical_restore": True}),
    ("/api/backup-storage/pilot/maintenance?dry_run=false&force_critical_restore=true", "maintain_repository", {"dry_run": False, "force_critical_restore": True}),
])
def test_repository_routes_parse_explicit_operation_flags(repository_runtime, path, operation, expected):
    from fastapi.testclient import TestClient

    from app.main import app

    _endpoints, runtime = repository_runtime
    response = TestClient(app).post(path)
    assert response.status_code == 200, response.text
    assert getattr(runtime, operation).call_args.kwargs == expected


@pytest.mark.parametrize("force", [False, True])
def test_cli_force_restore_reaches_existing_owner_api(repository_runtime, monkeypatch, force):
    from fastapi.testclient import TestClient
    from typer.testing import CliRunner

    from app.main import app as api_app
    from cli.commands import backup_storage
    from cli.main import app as cli_app

    endpoints, runtime = repository_runtime
    client = TestClient(api_app)

    def post(path, **_kwargs):
        response = client.post("/api/" + path)
        assert response.status_code == 200, response.text
        return response.json()

    monkeypatch.setattr(backup_storage, "_api_post", post)
    args = ["backup", "storage", "maintenance", "pilot", "--apply"]
    if force:
        args.append("--force-critical-restore")
    result = CliRunner().invoke(cli_app, args)
    assert result.exit_code == 0, result.output
    assert runtime.maintain_repository.call_args.kwargs == {"dry_run": False, "force_critical_restore": force}
    endpoints.require_owner.assert_called_once()


def test_force_restore_query_rejects_invalid_boolean(repository_runtime):
    from fastapi.testclient import TestClient

    from app.main import app

    _, runtime = repository_runtime
    response = TestClient(app).post("/api/backup-storage/pilot/maintenance?force_critical_restore=invalid")
    assert response.status_code == 422
    runtime.maintain_repository.assert_not_called()


@pytest.mark.asyncio
async def test_forced_restore_still_requires_owner(repository_runtime, monkeypatch):
    endpoints, runtime = repository_runtime

    def deny(_request):
        raise HTTPException(status_code=403, detail="Owner access required")

    monkeypatch.setattr(endpoints, "require_owner", deny)
    with pytest.raises(HTTPException) as error:
        await endpoints.maintain_storage_repository("pilot", Request({"type": "http"}), force_critical_restore=True)
    assert error.value.status_code == 403
    runtime.maintain_repository.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["initialize_storage_repository", "maintain_storage_repository"])
async def test_mutating_repository_endpoints_require_owner(repository_runtime, monkeypatch, operation):
    endpoints, runtime = repository_runtime

    def deny(_request):
        raise HTTPException(status_code=403, detail="Owner access required")

    monkeypatch.setattr(endpoints, "require_owner", deny)
    with pytest.raises(HTTPException) as error:
        await getattr(endpoints, operation)("pilot", Request({"type": "http"}))
    assert error.value.status_code == 403
    runtime.initialize_repository.assert_not_called()
    runtime.maintain_repository.assert_not_called()


@pytest.mark.asyncio
async def test_repository_failure_is_reported_without_initializing_again(repository_runtime):
    from app.tasks.backup_restic import ResticError

    endpoints, runtime = repository_runtime
    runtime.initialize_repository.side_effect = ResticError("Repository open failed; initialization refused")
    with pytest.raises(HTTPException) as error:
        await endpoints.initialize_storage_repository("pilot", Request({"type": "http"}))
    assert error.value.status_code == 409
    assert runtime.initialize_repository.call_count == 1
