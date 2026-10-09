"""Backup health projection for latest offsite and isolated-restore evidence."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest


@pytest.fixture(autouse=True)
def no_repository_database_access(monkeypatch):
    from app.api.backups import health_endpoints

    monkeypatch.setattr(health_endpoints.backup_store, "list_backends", lambda **_: [])


@pytest.mark.asyncio
async def test_health_adds_sanitized_combined_repository_restore(monkeypatch):
    from app.api.backups import health_endpoints
    from app.tasks import backup_repository_runtime as runtime

    monkeypatch.setattr(health_endpoints.backup_store, "get_backup_health_summary", lambda: [])
    monkeypatch.setattr(health_endpoints.backup_store, "list_backends", lambda **_: [
        {"id": "remote", "name": "Offsite backup", "backend_type": "local", "config": {"engine": "restic", "restic_remote_repository": "rclone:fixture:bounded"}},
        {"id": "native", "config": {"engine": "native"}},
    ])
    monkeypatch.setattr(health_endpoints, "storage_config_env", lambda _: {"BACKUP_STORAGE_BACKEND_ID": "remote"})
    monkeypatch.setattr(runtime, "repository_recovery_status", lambda _: {
        "status": "failed", "last_success_at": "2026-10-01T12:00:00+00:00",
        "latest_attempt": {"status": "failed", "reason": "mapped-links-unresolved", "failed_source_id": "claude-config", "cached": True},
    })
    response = await health_endpoints.backup_health()
    assert len(response.repositories) == 1
    repository = response.repositories[0]
    assert repository.backend_id == "remote"
    assert repository.critical_restore.status == "failed"
    assert repository.critical_restore.latest_attempt is not None
    assert repository.critical_restore.latest_attempt.cached is True


@pytest.mark.asyncio
@pytest.mark.parametrize("engine,remote,hours,expected", [
    ("restic", "rclone:fixture:bounded", 72, "verified"),
    ("restic", "rclone:fixture:bounded", 169, "stale"),
    ("restic", "", 72, "stale"),
    ("native", "", 72, "stale"),
])
async def test_infrastructure_confidence_matches_effective_recovery_cadence(monkeypatch, engine, remote, hours, expected) -> None:
    from app.api.backups import health_endpoints

    monkeypatch.setattr(health_endpoints.backup_store, "get_backup_health_summary", lambda: [{
        "source_id": "infrastructure", "source_name": "System Backup", "source_type": "infrastructure", "enabled": True,
        "last_success_at": "2026-09-21T12:00:00+00:00", "last_backup_status": "completed",
        "latest_backup_id": "current-point", "last_drill_backup_id": "tested-point",
        "last_drill_ok": True, "last_drill_at": "2026-09-21T12:00:00+00:00",
        "latest_verification_json": {"offsite": {"status": "verified"}},
    }])
    monkeypatch.setattr(health_endpoints, "build_storage_env", lambda _: {"BACKUP_ENGINE": engine, "RESTIC_REMOTE_REPOSITORY": remote})
    monkeypatch.setattr(health_endpoints, "_hours_since", lambda _: hours)
    monkeypatch.setattr(health_endpoints, "verify_archive_coverage", lambda _: SimpleNamespace(complete=True))

    result = await health_endpoints.backup_health()

    assert result.sources[0].restore_confidence == expected
    assert result.sources[0].last_drill_backup_id == "tested-point"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("drill_backup_id", "confidence", "coverage_complete", "drill_ok", "expected"),
    [("older-backup", "verified", True, True, "green"), ("backup-current", "verified", True, True, "green"),
     ("backup-current", "stale", True, True, "yellow"),
     ("older-backup", "stale", True, True, "yellow"), (None, "verified", True, True, "yellow"),
     ("backup-current", "verified", False, True, "yellow"),
     ("older-backup", "partial", True, False, "red"),
     (None, "untested", True, None, "yellow")],
)
async def test_infra_green_requires_fresh_dated_drill_and_current_coverage(
    monkeypatch, drill_backup_id, confidence, coverage_complete, drill_ok, expected,
) -> None:
    from app.api.backups import health_endpoints

    monkeypatch.setattr(health_endpoints.backup_store, "get_backup_health_summary", lambda: [{
        "source_id": "infrastructure", "source_name": "System Backup",
        "source_type": "infrastructure", "enabled": True,
        "last_success_at": "2026-09-21T12:00:00+00:00", "last_backup_status": "completed",
        "latest_backup_id": "backup-current", "last_drill_backup_id": drill_backup_id,
        "last_drill_ok": drill_ok, "last_drill_at": "2026-09-21T12:10:00+00:00",
        "latest_verification_json": {"offsite": {"status": "verified"}},
    }])
    monkeypatch.setattr(health_endpoints, "build_storage_env", lambda _: {})
    monkeypatch.setattr(health_endpoints, "_compute_restore_confidence", lambda **_: confidence)
    monkeypatch.setattr(health_endpoints, "verify_archive_coverage", lambda _: SimpleNamespace(complete=coverage_complete))

    result = await health_endpoints.backup_health()
    assert result.sources[0].health_status == expected
    assert result.sources[0].coverage_complete is coverage_complete
    assert result.sources[0].last_drill_backup_id == drill_backup_id
    assert result.sources[0].latest_backup_id == "backup-current"


@pytest.mark.asyncio
async def test_health_projects_latest_offsite_evidence_and_disabled_state(monkeypatch) -> None:
    from app.api.backups import health_endpoints

    monkeypatch.setattr(
        health_endpoints.backup_store,
        "get_backup_health_summary",
        lambda: [
            {
                "source_id": "summitflow",
                "source_name": "SummitFlow",
                "source_type": "project",
                "enabled": False,
                "last_success_at": "2026-09-21T12:00:00+00:00",
                "last_backup_status": "completed",
                "failure_count_7d": 0,
                "pending_upload_count": 0,
                "latest_backup_id": "backup-1",
                "latest_verification_json": {
                    "offsite": {
                        "status": "failed",
                        "error": "provider unavailable",
                    },
                    "isolated_restore": {
                        "ok": True,
                        "verified_at": "2026-09-21T13:00:00+00:00",
                    },
                },
            }
        ],
    )
    monkeypatch.setattr(
        health_endpoints,
        "build_storage_env",
        lambda _source_id: {"BACKUP_OFFSITE_GIO_URI": "google-drive://account/root"},
    )

    result = await health_endpoints.backup_health()
    item = result.sources[0]

    assert item.health_status == "disabled"
    assert item.latest_backup_id == "backup-1"
    assert item.offsite_status == "failed"
    assert item.offsite_error == "provider unavailable"
    assert item.last_isolated_restore_ok is True
    assert item.last_isolated_restore_at == "2026-09-21T13:00:00+00:00"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("offsite_status", "expected_error"),
    [("verified", None), ("pending", None), ("failed", "previous transfer failed")],
)
async def test_health_only_projects_current_offsite_failure(monkeypatch, offsite_status, expected_error) -> None:
    from app.api.backups import health_endpoints

    verification = {"offsite": {"status": offsite_status, "error": "previous transfer failed"}}
    monkeypatch.setattr(health_endpoints.backup_store, "get_backup_health_summary", lambda: [{
        "source_id": "summitflow", "source_name": "SummitFlow", "source_type": "project", "enabled": True,
        "last_success_at": "2026-09-21T12:00:00+00:00", "last_backup_status": "completed",
        "latest_verification_json": verification,
    }])
    monkeypatch.setattr(health_endpoints, "build_storage_env", lambda _: {})

    result = await health_endpoints.backup_health()

    assert result.sources[0].offsite_error == expected_error
    assert verification["offsite"]["error"] == "previous transfer failed"


@pytest.mark.asyncio
async def test_offsite_retry_marks_latest_backup_pending_and_queues_workflow(monkeypatch) -> None:
    from app.api.backups import source_endpoints
    from app.workflows import utility

    monkeypatch.setattr(source_endpoints, "acquire_backup_lock", lambda _: "owner")

    merged: list[tuple[str, dict[str, Any]]] = []
    monkeypatch.setattr(
        source_endpoints.backup_store,
        "get_backup",
        lambda _backup_id: {
            "id": "backup-1",
            "source_id": "summitflow",
            "status": "completed",
        },
    )
    monkeypatch.setattr(
        source_endpoints.backup_store,
        "merge_backup_verification_json",
        lambda backup_id, value: merged.append((backup_id, value)),
    )
    queued = AsyncMock(return_value=SimpleNamespace(workflow_run_id="workflow-1"))
    monkeypatch.setattr(utility.backup_offsite_sync_wf, "aio_run_no_wait", queued)

    result = await source_endpoints.sync_source_backup_offsite("summitflow", "backup-1")

    assert result.status == "queued"
    assert result.task_id == "workflow-1"
    assert len(merged) == 1  # No late queue response can overwrite a newer run.
    first = merged[0][1]
    assert first["offsite"] == {"status": "pending"}
    queued.assert_awaited_once()
    dispatched = queued.call_args.args[0]
    assert first["activity"]["run_id"] == dispatched.attempt_id
    assert dispatched.attempt_id not in {None, "", dispatched.owner_token}


@pytest.mark.asyncio
async def test_offsite_duplicate_retry_is_blocked_by_source_lease(monkeypatch) -> None:
    from fastapi import HTTPException

    from app.api.backups import source_endpoints

    monkeypatch.setattr(source_endpoints.backup_store, "get_backup", lambda _: {
        "id": "backup-1", "source_id": "source", "status": "completed",
    })
    monkeypatch.setattr(source_endpoints, "acquire_backup_lock", lambda _: None)
    with pytest.raises(HTTPException) as error:
        await source_endpoints.sync_source_backup_offsite("source", "backup-1")
    assert error.value.status_code == 409


@pytest.mark.asyncio
@pytest.mark.parametrize("encryption_ready", [True, False])
async def test_storage_probe_reports_local_key_and_gio_readiness(
    tmp_path,
    monkeypatch,
    encryption_ready,
) -> None:
    from app.api.backups import storage_endpoints

    monkeypatch.setattr(
        storage_endpoints.backup_store,
        "get_backend",
        lambda _backend_id: {
            "id": "local-1",
            "backend_type": "local",
            "config": {
                "root_path": str(tmp_path / "backups"),
                "offsite_gio_uri": "google-drive://account/root-id",
            },
        },
    )
    updates: list[tuple[str, bool]] = []
    monkeypatch.setattr(
        storage_endpoints.backup_store,
        "update_test_result",
        lambda backend_id, success: updates.append((backend_id, success)),
    )
    monkeypatch.setattr(
        storage_endpoints,
        "get_backup_key_status",
        lambda: {"ready": encryption_ready},
    )
    monkeypatch.setattr(
        storage_endpoints.safe_subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(returncode=0, stdout="", stderr=""),
    )

    result = await storage_endpoints.test_storage_backend("local-1")

    assert result["success"] is encryption_ready
    assert result["local_success"] is True
    assert result["offsite_success"] is True
    assert result["encryption_ready"] is encryption_ready
    assert updates == [("local-1", encryption_ready)]
    message = result["message"]
    assert isinstance(message, str)
    assert "Google Drive reachable" in message
    if not encryption_ready:
        assert "recovery key is not verified" in message
