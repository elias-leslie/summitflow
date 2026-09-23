"""Owner cancellation is run-bound and never claims instant termination."""

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Literal
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from app.access_control import AccessPrincipal
from app.api.backups import source_endpoints


@contextmanager
def client_for(role: Literal["owner", "viewer", "none"] = "owner") -> Iterator[TestClient]:
    app = FastAPI()

    @app.middleware("http")
    async def principal(request: Request, call_next):
        request.state.principal = (
            None if role == "none" else AccessPrincipal("fixture@example.test", role, True)
        )
        return await call_next(request)

    app.include_router(source_endpoints.router)
    with TestClient(app, base_url="https://summitflow.example") as client:
        yield client


@pytest.fixture
def active_backup(monkeypatch: pytest.MonkeyPatch) -> Mock:
    monkeypatch.setattr(source_endpoints.backup_store, "get_backup", lambda _id: {
        "id": "backup-1", "source_id": "source", "status": "completed",
        "verification_json": {"activity": {"run_id": "run-current", "active": True}},
    })
    signal = Mock(return_value=True)
    monkeypatch.setattr(source_endpoints.backup_store, "request_backup_cancellation", signal)
    return signal


@pytest.mark.parametrize("role", ["viewer", "none"])
def test_cancellation_refuses_nonowner_before_signalling(
    role: Literal["viewer", "none"], active_backup: Mock,
) -> None:
    with client_for(role) as client:
        response = client.post(
            "/backup-sources/source/backups/backup-1/cancel",
            json={"run_id": "run-current"}, headers={"Origin": "https://summitflow.example"},
        )
    assert response.status_code == 403
    active_backup.assert_not_called()


def test_cancellation_refuses_cross_origin(active_backup: Mock) -> None:
    with client_for() as client:
        response = client.post(
            "/backup-sources/source/backups/backup-1/cancel",
            json={"run_id": "run-current"},
            headers={"Origin": "https://other.example", "Sec-Fetch-Site": "cross-site"},
        )
    assert response.status_code == 403
    active_backup.assert_not_called()


def test_cancellation_signals_exact_run_and_returns_cancelling_not_terminal(active_backup: Mock) -> None:
    with client_for() as client:
        response = client.post(
            "/backup-sources/source/backups/backup-1/cancel",
            json={"run_id": "run-current"}, headers={"Origin": "https://summitflow.example"},
        )
    assert response.status_code == 200
    assert response.json()["status"] == "cancelling"
    assert response.json()["task_id"] == "run-current"
    active_backup.assert_called_once_with("backup-1", "run-current")


def test_stale_attempt_returns_conflict(active_backup: Mock) -> None:
    active_backup.return_value = False
    with client_for() as client:
        response = client.post(
            "/backup-sources/source/backups/backup-1/cancel",
            json={"run_id": "run-old"}, headers={"Origin": "https://summitflow.example"},
        )
    assert response.status_code == 409
    active_backup.assert_called_once_with("backup-1", "run-old")


def test_source_mismatch_does_not_signal_another_source(active_backup: Mock) -> None:
    with client_for() as client:
        response = client.post(
            "/backup-sources/another-source/backups/backup-1/cancel",
            json={"run_id": "run-current"}, headers={"Origin": "https://summitflow.example"},
        )
    assert response.status_code == 404
    active_backup.assert_not_called()


@pytest.mark.asyncio
async def test_queue_failure_releases_only_acquired_source_lease(
    active_backup: Mock, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.workflows import utility

    monkeypatch.setattr(source_endpoints, "acquire_backup_lock", lambda _source: "exact-owner-token")
    released = Mock()
    merged = Mock()
    queued = AsyncMock(side_effect=RuntimeError("queue unavailable"))
    monkeypatch.setattr(source_endpoints, "release_backup_lock", released)
    monkeypatch.setattr(source_endpoints.backup_store, "merge_backup_verification_json", merged)
    monkeypatch.setattr(utility.backup_offsite_sync_wf, "aio_run_no_wait", queued)
    with pytest.raises(RuntimeError, match="queue unavailable"):
        await source_endpoints.sync_source_backup_offsite("source", "backup-1")
    released.assert_called_once_with("source", "exact-owner-token")
    assert merged.call_args.args[1]["activity"]["active"] is False
    assert merged.call_args.args[1]["offsite"]["status"] == "failed"


@pytest.mark.asyncio
@pytest.mark.parametrize("queue_fails", [False, True])
async def test_queue_closeout_cannot_overwrite_a_newer_attempt(
    active_backup: Mock, monkeypatch: pytest.MonkeyPatch, queue_fails: bool,
) -> None:
    from app.workflows import utility

    state: dict = {}
    calls: list[str] = []
    attempt_ids: list[str] = []
    monkeypatch.setattr(source_endpoints, "acquire_backup_lock", lambda _: "private-lease-token")

    def merge(_id, update, **kwargs):
        expected = kwargs.get("expected_activity_run_id")
        if expected is not None and state["activity"]["run_id"] != expected:
            calls.append("stale-write-rejected")
            return None
        state.update(update)
        calls.append("write")
        return state

    async def queue(value):
        attempt_ids.append(value.attempt_id)
        assert state["activity"]["run_id"] == value.attempt_id
        assert value.attempt_id != value.owner_token
        state.update({"activity": {"run_id": "newer-attempt", "active": True}, "offsite": {"status": "verified"}})
        if queue_fails:
            raise RuntimeError("queue unavailable")
        return Mock(workflow_run_id="actual-workflow")

    monkeypatch.setattr(source_endpoints.backup_store, "merge_backup_verification_json", merge)
    monkeypatch.setattr(source_endpoints, "release_backup_lock", lambda *_: calls.append("release"))
    monkeypatch.setattr(utility.backup_offsite_sync_wf, "aio_run_no_wait", queue)
    if queue_fails:
        with pytest.raises(RuntimeError, match="queue unavailable"):
            await source_endpoints.sync_source_backup_offsite("source", "backup-1")
        assert calls[-2:] == ["stale-write-rejected", "release"]
    else:
        response = await source_endpoints.sync_source_backup_offsite("source", "backup-1")
        assert response.task_id == "actual-workflow"
        assert "release" not in calls
    assert attempt_ids[0]
    assert state == {"activity": {"run_id": "newer-attempt", "active": True}, "offsite": {"status": "verified"}}


@pytest.mark.asyncio
async def test_duplicate_retry_does_not_queue_or_mutate_current_attempt(
    active_backup: Mock, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from fastapi import HTTPException

    from app.workflows import utility

    monkeypatch.setattr(source_endpoints, "acquire_backup_lock", lambda _source: None)
    merged = Mock()
    queued = AsyncMock()
    monkeypatch.setattr(source_endpoints.backup_store, "merge_backup_verification_json", merged)
    monkeypatch.setattr(utility.backup_offsite_sync_wf, "aio_run_no_wait", queued)
    with pytest.raises(HTTPException) as error:
        await source_endpoints.sync_source_backup_offsite("source", "backup-1")
    assert error.value.status_code == 409
    merged.assert_not_called()
    queued.assert_not_called()
