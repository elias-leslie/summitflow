"""Tests for task enrichment discussion endpoints."""

from __future__ import annotations

from types import SimpleNamespace


def test_discuss_task_returns_typed_history(client, mocker) -> None:
    task = {"id": "task-1", "project_id": "proj-1", "enrichment_status": "review"}
    mocker.patch("app.api.tasks.enrichment.verify_task_project", return_value=task)
    mocker.patch(
        "app.api.tasks.enrichment._get_discussion_history",
        return_value=[{"role": "assistant", "content": "Previous reply"}],
    )
    mocker.patch("app.api.tasks.enrichment._save_discussion_history")
    mocker.patch(
        "app.services.enrichment_service.discuss_task",
        return_value=SimpleNamespace(response="Updated response", updated_task=None),
    )

    response = client.post(
        "/api/projects/proj-1/tasks/task-1/discuss",
        json={"message": "Please refine this task"},
    )

    assert response.status_code == 200
    body = response.json()
    assert [entry["role"] for entry in body["history"]] == ["assistant", "user", "assistant"]
    assert body["history"][1]["content"] == "Please refine this task"
    assert body["history"][2]["content"] == "Updated response"
