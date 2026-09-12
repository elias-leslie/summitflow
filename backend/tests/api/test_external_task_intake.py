"""External delivery reconciles a single canonical task without repeating writes."""
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import uuid4

import pytest

from app.access_control import AccessPrincipal
from app.storage import tasks
from app.storage.task_spirit import get_task_spirit


def payload(**changes):
    return {
        "title": "External intake contract",
        "external_origin": "test-client",
        "external_request_key": str(uuid4()),
        "objective": "Persist a generic development request",
        "constraints": ["Preserve existing ownership"],
        "references": ["task-context"],
        "done_when": ["One durable task exists"],
        **changes,
    }


def test_concurrent_delivery_and_lost_ack_reuse(client, test_project_id, cleanup_task):
    body = payload()
    route = f"/api/projects/{test_project_id}/tasks"
    start = Barrier(4)

    def deliver(_index):
        start.wait()
        return client.post(route, json=body)

    with ThreadPoolExecutor(max_workers=4) as workers:
        responses = list(workers.map(deliver, range(4)))
    assert [response.status_code for response in responses] == [200] * 4
    ids = {response.json()["id"] for response in responses}
    assert len(ids) == 1
    task_id = ids.pop()
    cleanup_task(task_id)
    spirit = get_task_spirit(task_id)
    assert spirit is not None
    assert spirit["context"]["references"] == ["task-context"]
    # Explicit defaults/key order normalize identically, and a replay cannot
    # overwrite subsequent ordinary task edits or repeat creation side effects.
    tasks.update_task(task_id, title="Implementation now in progress")
    replay = client.post(route, json={"priority": 2, **dict(reversed(list(body.items())))})
    assert replay.status_code == 200
    assert replay.json()["id"] == task_id
    assert replay.json()["title"] == "Implementation now in progress"
    assert replay.json()["external_origin"] == body["external_origin"]
    assert len(replay.json()["external_payload_digest"]) == 64
    context = client.get(f"{route}/{task_id}/context?format=json").json()["task"]
    assert context["external_request_key"] == body["external_request_key"]
    assert context["merge_sha"] is None
    assert context["verification_result"] is None


def test_changed_payload_conflicts_without_mutation(client, test_project_id, cleanup_task):
    body = payload()
    route = f"/api/projects/{test_project_id}/tasks"
    first = client.post(route, json=body).json()
    cleanup_task(first["id"])
    for changes in ({"title": "Changed"}, {"references": ["Changed"]}, {"auto_dispatch": True}):
        conflict = client.post(route, json={**body, **changes})
        assert conflict.status_code == 409
    unchanged = tasks.get_task(first["id"])
    spirit = get_task_spirit(first["id"])
    assert unchanged is not None and spirit is not None
    assert unchanged["title"] == body["title"]
    assert spirit["context"]["references"] == ["task-context"]
    # The request key is not a grant to create the same request in another project.
    conflict = client.post("/api/projects/nonexistent-scope/tasks", json=body)
    assert conflict.status_code == 409


def test_archived_identity_does_not_create_new_task(client, test_project_id):
    body = payload()
    route = f"/api/projects/{test_project_id}/tasks"
    first = client.post(route, json=body).json()
    tasks.delete_task(first["id"])
    replay = client.post(route, json=body)
    assert replay.status_code == 200
    assert replay.json()["id"] == first["id"]
    assert replay.json()["archived"] is True
    assert tasks.get_task(first["id"]) is None


def test_external_identity_is_complete_and_legacy_intake_is_unchanged(client, test_project_id, cleanup_task):
    route = f"/api/projects/{test_project_id}/tasks"
    for changes in ({"external_request_key": None}, {"external_origin": " "}):
        assert client.post(route, json=payload(**changes)).status_code == 422
    legacy = client.post(route, json={"title": "Legacy intake"})
    assert legacy.status_code == 200
    cleanup_task(legacy.json()["id"])
    assert legacy.json()["external_origin"] is None
    assert legacy.json()["merge_sha"] is None


def test_principal_scopes_are_derived_from_authenticated_identity(client, test_project_id, cleanup_task, monkeypatch):
    body = payload()
    route = f"/api/projects/{test_project_id}/tasks"
    ids = set()
    for email in ("first@example.invalid", "second@example.invalid"):
        monkeypatch.setattr("app.access_control.resolve_principal", lambda _request, email=email: AccessPrincipal(email, "owner", True))
        response = client.post(route, json=body)
        assert response.status_code == 200
        ids.add(response.json()["id"])
        cleanup_task(response.json()["id"])
    assert len(ids) == 2


def test_spirit_failure_rolls_back_task_and_identity(client, test_project_id, cleanup_task, monkeypatch):
    from app.storage.tasks import core
    body = payload()
    route = f"/api/projects/{test_project_id}/tasks"
    original = core.insert_task_spirit

    def fail(*_args, **_kwargs):
        raise RuntimeError("simulated transaction interruption")

    monkeypatch.setattr(core, "insert_task_spirit", fail)
    with pytest.raises(RuntimeError, match="simulated transaction interruption"):
        client.post(route, json=body)
    monkeypatch.setattr(core, "insert_task_spirit", original)
    response = client.post(route, json=body)
    assert response.status_code == 200
    cleanup_task(response.json()["id"])
    spirit = get_task_spirit(response.json()["id"])
    assert spirit is not None
    assert spirit["done_when"] == body["done_when"]
