"""Tests for durable quality auto-fix dispatch and polling."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.api import auto_fix
from app.main import app
from app.tasks import quality_auto_fix
from app.workflows import utility
from app.workflows.models import AutoFixInput


def _client(monkeypatch) -> TestClient:
    monkeypatch.setattr(auto_fix, "validate_project_exists", lambda _project_id: None)
    return TestClient(app)


def test_trigger_auto_fix_returns_202_polling_contract(monkeypatch) -> None:
    class FakeWorkflow:
        async def aio_run_no_wait(self, workflow_input: AutoFixInput) -> SimpleNamespace:
            assert workflow_input == AutoFixInput(project_id="proj-1", check_type="ruff", limit=3)
            return SimpleNamespace(workflow_run_id="job-123")

    monkeypatch.setattr(utility, "quality_auto_fix_wf", FakeWorkflow())
    client = _client(monkeypatch)

    response = client.post(
        "/api/projects/proj-1/quality/auto-fix",
        json={"check_type": "ruff", "limit": 3},
    )

    assert response.status_code == 202
    assert response.headers["location"] == "/api/projects/proj-1/quality/auto-fix/job-123"
    assert response.json() == {
        "triggered": True,
        "check_type": "ruff",
        "fixed": 0,
        "failed": 0,
        "escalated": 0,
        "message": "Auto-fix queued as job job-123",
        "job_id": "job-123",
        "status": "queued",
    }


def test_trigger_auto_fix_rejects_unbounded_batch(monkeypatch) -> None:
    client = _client(monkeypatch)

    response = client.post(
        "/api/projects/proj-1/quality/auto-fix",
        json={"limit": 51},
    )

    assert response.status_code == 422


@pytest.mark.parametrize(
    ("hatchet_status", "api_status"),
    [
        ("PENDING", "queued"),
        ("QUEUED", "queued"),
        ("BACKOFF", "queued"),
        ("RUNNING", "running"),
        ("SUCCEEDED", "completed"),
        ("FAILED", "failed"),
        ("CANCELLED", "cancelled"),
    ],
)
def test_job_status_maps_installed_hatchet_states(
    hatchet_status: str,
    api_status: str,
) -> None:
    assert auto_fix._job_status(hatchet_status) == api_status


def test_poll_auto_fix_returns_completed_legacy_result_shape(monkeypatch) -> None:
    async def fake_get_run(_job_id: str) -> SimpleNamespace:
        return SimpleNamespace(
            input={"project_id": "proj-1", "check_type": "pytest", "limit": 2},
            status="COMPLETED",
            task_runs={
                "summitflow-quality-auto-fix": SimpleNamespace(
                    output={
                        "triggered": True,
                        "check_type": "pytest",
                        "fixed": 2,
                        "failed": 0,
                        "escalated": 0,
                        "message": "All 2 issues fixed",
                    },
                    error=None,
                )
            },
        )

    monkeypatch.setattr(auto_fix, "_get_auto_fix_run", fake_get_run)
    client = _client(monkeypatch)

    response = client.get("/api/projects/proj-1/quality/auto-fix/job-123")

    assert response.status_code == 200
    assert response.json() == {
        "triggered": True,
        "check_type": "pytest",
        "fixed": 2,
        "failed": 0,
        "escalated": 0,
        "message": "All 2 issues fixed",
        "job_id": "job-123",
        "status": "completed",
    }


def test_poll_auto_fix_hides_jobs_from_other_projects(monkeypatch) -> None:
    async def fake_get_run(_job_id: str) -> SimpleNamespace:
        return SimpleNamespace(
            input={"project_id": "other-project", "check_type": None},
            status="RUNNING",
            task_runs={},
        )

    monkeypatch.setattr(auto_fix, "_get_auto_fix_run", fake_get_run)
    client = _client(monkeypatch)

    response = client.get("/api/projects/proj-1/quality/auto-fix/job-123")

    assert response.status_code == 404


def test_quality_auto_fix_workflow_offloads_synchronous_work(monkeypatch) -> None:
    calls: list[tuple[object, tuple[object, ...]]] = []
    expected: dict[str, object] = {
        "triggered": False,
        "check_type": "ruff",
        "fixed": 0,
        "failed": 0,
        "escalated": 0,
        "message": "No unfixed issues to process",
    }

    async def fake_to_thread(function: object, *args: object) -> dict[str, object]:
        calls.append((function, args))
        return expected

    monkeypatch.setattr(utility.asyncio, "to_thread", fake_to_thread)

    result = asyncio.run(
        utility._run_quality_auto_fix_off_thread(
            AutoFixInput(project_id="proj-1", check_type="ruff", limit=4)
        )
    )

    assert result == expected
    assert calls == [(quality_auto_fix.run_quality_auto_fix, ("proj-1", "ruff", 4))]


def test_run_quality_auto_fix_commits_and_returns_legacy_counts(monkeypatch) -> None:
    connection = SimpleNamespace(commit=lambda: None)
    commits: list[bool] = []

    class ConnectionContext:
        def __enter__(self) -> SimpleNamespace:
            connection.commit = lambda: commits.append(True)
            return connection

        def __exit__(self, *_args: object) -> None:
            return None

    monkeypatch.setattr(quality_auto_fix, "get_connection", ConnectionContext)
    monkeypatch.setattr(
        quality_auto_fix,
        "_run_fix_by_type",
        lambda *_args: {"fixed": 1, "failed": 0, "escalated": 0},
    )

    result = quality_auto_fix.run_quality_auto_fix("proj-1", "ruff", 4)

    assert commits == [True]
    assert result == {
        "triggered": True,
        "check_type": "ruff",
        "fixed": 1,
        "failed": 0,
        "escalated": 0,
        "message": "All 1 issues fixed",
    }
