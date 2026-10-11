"""Database workbench API: writable mode needs an explicit host opt-in."""

from __future__ import annotations

import pytest


@pytest.fixture
def start_workbench(mocker):
    from app.services.db_workbench import DbWorkbenchStatus

    status = DbWorkbenchStatus(
        project_id="summitflow",
        running=True,
        installed=True,
        configured=True,
        readonly=True,
        pid=None,
        port=None,
        proxy_url="/api/projects/summitflow/db-workbench/proxy/",
        direct_url=None,
        shared_with=None,
        started_at=None,
    )
    return mocker.patch("app.api.db_workbench.start_workbench", return_value=status)


def test_writable_start_is_refused_without_opt_in(client, start_workbench, monkeypatch) -> None:
    monkeypatch.delenv("SUMMITFLOW_DB_WORKBENCH_ALLOW_WRITE", raising=False)

    response = client.post("/api/projects/summitflow/db-workbench/start", json={"readonly": False})

    assert response.status_code == 403
    assert "SUMMITFLOW_DB_WORKBENCH_ALLOW_WRITE=1" in response.json()["message"]
    start_workbench.assert_not_called()


def test_writable_start_is_allowed_with_opt_in(client, start_workbench, monkeypatch) -> None:
    monkeypatch.setenv("SUMMITFLOW_DB_WORKBENCH_ALLOW_WRITE", "1")

    response = client.post("/api/projects/summitflow/db-workbench/start", json={"readonly": False})

    assert response.status_code == 200
    start_workbench.assert_called_once_with("summitflow", readonly=False)


def test_default_start_stays_read_only_without_opt_in(client, start_workbench, monkeypatch) -> None:
    monkeypatch.delenv("SUMMITFLOW_DB_WORKBENCH_ALLOW_WRITE", raising=False)

    response = client.post("/api/projects/summitflow/db-workbench/start")

    assert response.status_code == 200
    start_workbench.assert_called_once_with("summitflow", readonly=True)
