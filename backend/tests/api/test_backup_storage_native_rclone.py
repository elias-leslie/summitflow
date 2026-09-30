"""Native archive offsite configuration is bounded and credential-reference-only."""
from pathlib import Path

import pytest
from fastapi import HTTPException


@pytest.fixture
def configuration(monkeypatch):
    from app.api.backups import storage_endpoints
    monkeypatch.setattr(storage_endpoints, "backup_key_directory", lambda: Path("/private/keys"))
    return {"engine": "native", "root_path": "/backup", "offsite_transport": "rclone", "offsite_rclone_remote": "drive:bounded", "offsite_rclone_config": "/private/keys/rclone.conf"}


def test_native_rclone_env_uses_same_capture_engine_and_file_reference(configuration) -> None:
    from app.api.backups.storage_endpoints import _validate_engine_config
    from app.tasks.backup_utils import offsite_is_configured, storage_config_env
    _validate_engine_config(configuration, "local")
    env = storage_config_env({**configuration, "backend_type": "local"})
    assert env["BACKUP_ENGINE"] == "native"
    assert env["BACKUP_OFFSITE_RCLONE_REMOTE"] == "drive:bounded"
    assert env["BACKUP_OFFSITE_RCLONE_CONFIG"] == "/private/keys/rclone.conf"
    assert offsite_is_configured(env)


@pytest.mark.parametrize("settings", [
    {"offsite_transport": ["rclone"]},
    {"offsite_transport": "unrecognized"},
    {"offsite_rclone_remote": "drive:"},
    {"offsite_rclone_remote": "drive:/"},
    {"offsite_rclone_remote": "drive:folder/../other"},
    {"offsite_rclone_remote": "drive:folder?token=fixture-secret"},
    {"offsite_rclone_remote": ":drive,token=fixture-secret:bounded"},
    {"offsite_rclone_config": {"token": "fixture-secret"}},
    {"offsite_rclone_config": "/outside/rclone.conf"},
    {"offsite_rclone_config": "relative.conf"},
])
def test_native_rclone_scope_is_validated_without_exposing_input(configuration, settings) -> None:
    from app.api.backups.storage_endpoints import _validate_engine_config
    with pytest.raises(HTTPException) as exc:
        _validate_engine_config({**configuration, **settings}, "local")
    assert exc.value.status_code == 400
    assert "fixture-secret" not in exc.value.detail


def test_incomplete_selected_transport_is_reported_as_configured(monkeypatch) -> None:
    from app.tasks.backup_utils import offsite_is_configured
    monkeypatch.delenv("BACKUP_OFFSITE_GIO_URI", raising=False)
    monkeypatch.delenv("BACKUP_OFFSITE_TRANSPORT", raising=False)
    assert offsite_is_configured({"BACKUP_OFFSITE_TRANSPORT": "rclone"})
    assert not offsite_is_configured({})


def test_permanent_expiry_is_boolean_and_pinned_to_root(configuration):
    from app.api.backups.storage_endpoints import _validate_engine_config
    from app.tasks.backup_utils import storage_config_env

    configuration.update(offsite_rclone_permanent_expiry=True, offsite_rclone_root_id="approved-root")
    _validate_engine_config(configuration, "local")
    env = storage_config_env(configuration)
    assert env["BACKUP_OFFSITE_RCLONE_PERMANENT_EXPIRY"] == "true"
    assert env["BACKUP_OFFSITE_RCLONE_ROOT_ID"] == "approved-root"


@pytest.mark.parametrize("settings", [
    {"offsite_rclone_permanent_expiry": "true"},
    {"offsite_rclone_permanent_expiry": True},
    {"offsite_rclone_permanent_expiry": True, "offsite_rclone_root_id": "../other"},
    {"offsite_rclone_permanent_expiry": True, "offsite_rclone_root_id": "approved-root", "offsite_transport": "gio"},
])
def test_permanent_expiry_rejects_unpinned_or_invalid_configuration(configuration, settings):
    from app.api.backups.storage_endpoints import _validate_engine_config
    with pytest.raises(HTTPException):
        _validate_engine_config({**configuration, **settings}, "local")


@pytest.mark.asyncio
@pytest.mark.parametrize("reachable", [True, False])
async def test_probe_reads_rclone_metadata_without_gio_or_upload(configuration, monkeypatch, tmp_path, reachable) -> None:
    from app.api.backups import storage_endpoints
    from app.tasks import backup_native_rclone
    configuration["root_path"] = str(tmp_path / "backups")
    monkeypatch.setattr(storage_endpoints.backup_store, "get_backend", lambda _: {"backend_type": "local", "config": configuration})
    monkeypatch.setattr(storage_endpoints.backup_store, "update_test_result", lambda *_: None)
    monkeypatch.setattr(storage_endpoints, "get_backup_key_status", lambda: {"ready": True})
    def probe(env):
        assert env["BACKUP_OFFSITE_RCLONE_REMOTE"] == "drive:bounded"
        if not reachable:
            raise RuntimeError("fixture secret diagnostics must not escape")
        return {"reachable": True}
    monkeypatch.setattr(backup_native_rclone, "probe_rclone_destination", probe)
    monkeypatch.setattr(storage_endpoints.safe_subprocess, "run", lambda *_args, **_kwargs: pytest.fail("GIO must not be used"))
    result = await storage_endpoints.test_storage_backend("local-1")
    assert result["offsite_success"] is reachable
    assert result["success"] is reachable
    assert "fixture secret" not in str(result["message"])
