from __future__ import annotations

import importlib
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock

from app.hatchet_app import DEFAULT_TASK_EXECUTION_TIMEOUT, DEFAULT_TASK_SCHEDULE_TIMEOUT
from app.tasks.autonomous import planning as planning_mod
from app.workflows import pipeline as pipeline_mod


class _FakePlannerClient:
    def complete(self, **_kwargs):
        return SimpleNamespace(content='{"objective": "Keep running", "subtasks": [], "constraints": []}')


def test_planning_uses_open_ended_agent_hub_client(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_get_sync_client(*, timeout=None, **_kwargs):
        captured["timeout"] = timeout
        return _FakePlannerClient()

    monkeypatch.setattr(planning_mod, "get_sync_client", fake_get_sync_client)
    monkeypatch.setattr(planning_mod, "_fetch_task_for_planning", lambda _task_id: {"title": "Audit", "description": "Timeouts"})
    monkeypatch.setattr(
        planning_mod,
        "collect_precision_code_search_context",
        lambda *_args, **_kwargs: SimpleNamespace(prompt_context=""),
    )
    monkeypatch.setattr(planning_mod, "_planning_feedback_payload", lambda _task_id: {})
    monkeypatch.setattr(
        planning_mod,
        "_process_plan_result",
        lambda task_id, project_id, title, description, plan_data: {
            "task_id": task_id,
            "project_id": project_id,
            "title": title,
            "description": description,
            "plan_data": plan_data,
            "status": "completed",
        },
    )

    result = planning_mod.create_plan("task-1", "summitflow")

    assert result["status"] == "completed"
    assert captured["timeout"] is None


def test_hatchet_defaults_remain_nonrestrictive() -> None:
    assert timedelta(days=7) == DEFAULT_TASK_SCHEDULE_TIMEOUT
    assert timedelta(days=7) == DEFAULT_TASK_EXECUTION_TIMEOUT


def test_pipeline_open_ended_stages_inherit_hatchet_defaults(monkeypatch) -> None:
    import app.hatchet_app as hatchet_app_mod

    recorded: list[dict[str, object]] = []

    def fake_task(*_args, **kwargs):
        recorded.append(dict(kwargs))

        def decorator(fn):
            return fn

        return decorator

    mock_hatchet = MagicMock()
    mock_hatchet.task.side_effect = fake_task

    monkeypatch.setattr(hatchet_app_mod, "get_hatchet", lambda: mock_hatchet)
    importlib.reload(pipeline_mod)
    try:
        registered = {kwargs["name"]: kwargs for kwargs in recorded}
    finally:
        importlib.reload(pipeline_mod)

    for task_name in (
        "summitflow-dispatch",
        "summitflow-ideate",
        "summitflow-triage",
        "summitflow-plan",
        "summitflow-critique",
        "summitflow-execute",
        "summitflow-review",
        "summitflow-escalation",
    ):
        assert registered[task_name]["execution_timeout"] == DEFAULT_TASK_EXECUTION_TIMEOUT
        assert registered[task_name]["schedule_timeout"] == DEFAULT_TASK_SCHEDULE_TIMEOUT
