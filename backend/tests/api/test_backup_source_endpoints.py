from types import SimpleNamespace

from fastapi.testclient import TestClient

from app.main import app
from app.workflows._models_backup import BackupInput


def test_backup_input_defaults_source_id_to_project_id():
    backup_input = BackupInput(project_id="proj-1")

    assert backup_input.source_id == "proj-1"


def test_create_source_backup_returns_task_id(monkeypatch):
    source = {
        "id": "src-1",
        "name": "Source 1",
        "path": "/tmp/src-1",
        "source_type": "project",
        "project_id": "proj-1",
        "enabled": True,
        "frequency": "daily",
        "retention_days": 7,
        "last_run_at": None,
        "next_run_at": None,
        "created_at": None,
        "updated_at": None,
    }

    monkeypatch.setattr(
        "app.api.backups.source_endpoints.backup_store.get_source",
        lambda source_id: source if source_id == "src-1" else None,
    )

    class FakeWorkflow:
        async def aio_run_no_wait(self, backup_input):
            assert backup_input.source_id == "src-1"
            assert backup_input.project_id == "proj-1"
            return SimpleNamespace(workflow_run_id="task-123")

    monkeypatch.setattr(
        "app.workflows.utility.backup_create_wf",
        FakeWorkflow(),
        raising=False,
    )

    client = TestClient(app)
    response = client.post(
        "/api/backup-sources/src-1/backups",
        json={"note": "burst create", "keep_local": False},
    )

    assert response.status_code == 200
    assert response.json() == {
        "task_id": "task-123",
        "status": "queued",
        "message": "Backup task queued for source src-1",
    }


def test_create_project_backup_returns_task_id(monkeypatch):
    class FakeWorkflow:
        async def aio_run_no_wait(self, backup_input):
            assert backup_input.source_id == "proj-1"
            assert backup_input.project_id == "proj-1"
            return SimpleNamespace(workflow_run_id="task-456")

    monkeypatch.setattr(
        "app.workflows.utility.backup_create_wf",
        FakeWorkflow(),
        raising=False,
    )

    client = TestClient(app)
    response = client.post(
        "/api/projects/proj-1/backups",
        json={"note": "project backup", "keep_local": False},
    )

    assert response.status_code == 200
    assert response.json() == {
        "task_id": "task-456",
        "status": "queued",
        "message": "Backup task queued for project proj-1",
    }
