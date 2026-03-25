"""Tests for backup response helper coercion."""

from __future__ import annotations

from datetime import UTC, datetime

from app.api.backups.source_endpoints import _source_to_response
from app.api.backups.storage_endpoints import _backend_to_response


def test_source_to_response_coerces_optional_fields() -> None:
    response = _source_to_response(
        {
            "id": "summitflow",
            "name": "SummitFlow",
            "path": "/srv/workspaces/projects/summitflow",
            "source_type": "project",
            "project_id": "summitflow",
            "enabled": True,
            "frequency": "daily",
            "retention_days": 14,
            "last_run_at": "2026-03-25T10:00:00Z",
            "next_run_at": object(),
            "created_at": "2026-03-24T10:00:00Z",
            "updated_at": "",
            "last_drill_at": None,
            "last_drill_ok": "yes",
            "last_drill_backup_id": 123,
        }
    )

    assert response.last_run_at == datetime(2026, 3, 25, 10, 0, tzinfo=UTC)
    assert response.next_run_at is None
    assert response.created_at == datetime(2026, 3, 24, 10, 0, tzinfo=UTC)
    assert response.updated_at is None
    assert response.last_drill_at is None
    assert response.last_drill_ok is None
    assert response.last_drill_backup_id is None


def test_backend_to_response_coerces_optional_fields() -> None:
    response = _backend_to_response(
        {
            "id": "nas",
            "name": "NAS",
            "backend_type": "smb",
            "config": {"share": "backups"},
            "is_default": True,
            "enabled": True,
            "last_test_at": "2026-03-25T12:00:00Z",
            "last_test_ok": "yes",
            "created_at": object(),
            "updated_at": "2026-03-25T12:30:00Z",
        }
    )

    assert response.config == {"share": "backups"}
    assert response.last_test_at == datetime(2026, 3, 25, 12, 0, tzinfo=UTC)
    assert response.last_test_ok is None
    assert response.created_at is None
    assert response.updated_at == datetime(2026, 3, 25, 12, 30, tzinfo=UTC)
