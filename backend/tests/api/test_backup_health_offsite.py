"""Backup health projection for latest offsite and isolated-restore evidence."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest


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
async def test_offsite_retry_marks_latest_backup_pending_and_queues_workflow(monkeypatch) -> None:
    from app.api.backups import source_endpoints
    from app.workflows import utility

    merged: list[tuple[str, object]] = []
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
    assert merged == [("backup-1", {"offsite": {"status": "pending"}})]
    queued.assert_awaited_once()


@pytest.mark.asyncio
async def test_storage_probe_reports_local_key_and_gio_readiness(
    tmp_path,
    monkeypatch,
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
        lambda: {"ready": True},
    )
    monkeypatch.setattr(
        storage_endpoints.safe_subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(returncode=0, stdout="", stderr=""),
    )

    result = await storage_endpoints.test_storage_backend("local-1")

    assert result["success"] is True
    assert result["local_success"] is True
    assert result["offsite_success"] is True
    assert result["encryption_ready"] is True
    assert updates == [("local-1", True)]
