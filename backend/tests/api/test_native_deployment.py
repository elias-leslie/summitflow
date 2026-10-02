"""Observation API requests cannot import results or select deployment targets."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import Mock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.tasks import helpers
from app.api.tasks import native_deployment_endpoints as endpoints
from app.services.native_deployment import NativeDeploymentError


@pytest.fixture
def isolated_client(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> TestClient:
    monkeypatch.setenv("SUMMITFLOW_SERVICE_STATE_ROOT", str(tmp_path / "private-state"))
    app = FastAPI()
    app.include_router(endpoints.router, prefix="/api")
    monkeypatch.setattr(helpers.task_store, "get_task", lambda task_id: {
        "id": task_id, "project_id": "fixture-owner", "status": "running",
    } if task_id == "task-fixture" else None)
    return TestClient(app)


@pytest.mark.parametrize("extra", ["host", "target_id", "ssh_arguments", "observer", "importer", "results",
                                  "observation", "deployment", "live_validation", "runtime_exclusions"])
def test_post_rejects_caller_targets_importers_and_results_before_issuing(
    isolated_client: TestClient, monkeypatch: pytest.MonkeyPatch, extra: str,
) -> None:
    issuer = Mock(side_effect=AssertionError("caller results must never reach issuer"))
    monkeypatch.setattr(endpoints, "issue_native_evidence", issuer)
    response = isolated_client.post("/api/projects/fixture-owner/tasks/task-fixture/deployment-observations",
                                    json={"acceptance_receipt": "/fixture/acceptance.json", extra: "untrusted"})
    assert response.status_code == 422
    issuer.assert_not_called()


@pytest.mark.parametrize("body", [{}, {"acceptance_receipt": 1}, {"acceptance_receipt": None}, {"acceptance_receipt": []}])
def test_post_requires_a_strict_acceptance_path(isolated_client: TestClient, monkeypatch: pytest.MonkeyPatch, body: dict) -> None:
    issuer = Mock(side_effect=AssertionError("invalid body must never reach issuer"))
    monkeypatch.setattr(endpoints, "issue_native_evidence", issuer)
    assert isolated_client.post("/api/projects/fixture-owner/tasks/task-fixture/deployment-observations", json=body).status_code == 422
    issuer.assert_not_called()


@pytest.mark.parametrize(("project", "task"), [("unknown-owner", "task-fixture"), ("fixture-owner", "unknown-task")])
def test_post_rejects_unknown_or_mismatched_task_project_before_observation(
    isolated_client: TestClient, monkeypatch: pytest.MonkeyPatch, project: str, task: str,
) -> None:
    root_lookup = Mock(side_effect=AssertionError("unknown task must not resolve a target"))
    issuer = Mock(side_effect=AssertionError("unknown task must not observe"))
    monkeypatch.setattr(endpoints, "get_project_root_path", root_lookup)
    monkeypatch.setattr(endpoints, "issue_native_evidence", issuer)
    response = isolated_client.post(f"/api/projects/{project}/tasks/{task}/deployment-observations",
                                    json={"acceptance_receipt": "/fixture/acceptance.json"})
    assert response.status_code == 404
    root_lookup.assert_not_called()
    issuer.assert_not_called()


def test_post_requires_registered_project_checkout(isolated_client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(endpoints, "get_project_root_path", lambda _project: None)
    issuer = Mock(side_effect=AssertionError("no arbitrary fallback project root"))
    monkeypatch.setattr(endpoints, "issue_native_evidence", issuer)
    response = isolated_client.post("/api/projects/fixture-owner/tasks/task-fixture/deployment-observations",
                                    json={"acceptance_receipt": "/fixture/acceptance.json"})
    assert response.status_code == 422
    issuer.assert_not_called()


def test_post_passes_verified_task_and_registered_root_only(isolated_client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root_lookup = Mock(return_value=str(tmp_path / "registered-project"))
    evidence = {"deployment": {"receipt_id": "server-issued"}, "live_validation": {"checks": []}}
    issuer = Mock(return_value=evidence)
    monkeypatch.setattr(endpoints, "get_project_root_path", root_lookup)
    monkeypatch.setattr(endpoints, "issue_native_evidence", issuer)
    artifact = tmp_path / "canonical-acceptance.json"
    response = isolated_client.post("/api/projects/fixture-owner/tasks/task-fixture/deployment-observations",
                                    json={"acceptance_receipt": str(artifact)})
    assert response.status_code == 200
    assert response.json() == evidence
    root_lookup.assert_called_once_with("fixture-owner")
    issuer.assert_called_once_with({"id": "task-fixture", "project_id": "fixture-owner", "status": "running"},
                                  tmp_path / "registered-project", artifact)


def test_post_rejects_noncanonical_acceptance_without_launching_observer(
    isolated_client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services import native_deployment

    root = tmp_path / "registered-project"
    root.mkdir()
    monkeypatch.setattr(endpoints, "get_project_root_path", lambda _project: str(root))
    observer = Mock(side_effect=AssertionError("bad acceptance must not launch observer"))
    monkeypatch.setattr(native_deployment, "_observe", observer)
    response = isolated_client.post("/api/projects/fixture-owner/tasks/task-fixture/deployment-observations",
                                    json={"acceptance_receipt": str(tmp_path / "missing.json")})
    assert response.status_code == 422
    observer.assert_not_called()


@pytest.mark.parametrize("project", ["fixture-owner", "unknown-owner"])
def test_get_requires_server_receipt_lookup_scoped_to_project(
    isolated_client: TestClient, monkeypatch: pytest.MonkeyPatch, project: str,
) -> None:
    reader = Mock(side_effect=NativeDeploymentError("unknown or wrong-project receipt"))
    monkeypatch.setattr(endpoints, "read_native_evidence", reader)
    response = isolated_client.get(f"/api/projects/{project}/deployment-observations/{'a' * 32}")
    assert response.status_code == 422
    reader.assert_called_once_with("a" * 32, project=project)


def test_get_returns_only_descriptors_for_server_lookup(isolated_client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    record = {"receipt_id": "a" * 32}
    reader = Mock(return_value=record)
    descriptor = {"deployment": {"receipt_id": record["receipt_id"]}, "live_validation": {"checks": []}}
    render = Mock(return_value=descriptor)
    monkeypatch.setattr(endpoints, "read_native_evidence", reader)
    monkeypatch.setattr(endpoints, "_descriptors", render)
    response = isolated_client.get(f"/api/projects/fixture-owner/deployment-observations/{'a' * 32}")
    assert response.status_code == 200
    assert response.json() == descriptor
    reader.assert_called_once_with("a" * 32, project="fixture-owner")
    render.assert_called_once_with(record)
