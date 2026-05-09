from __future__ import annotations

from app.services.autonomous_schedule_registry import describe_autonomous_schedule
from app.workflows.scheduled import _enabled_project_ids


def test_work_pickup_schedule_defaults_to_disabled(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.services.autonomous_schedule_registry.get_agent_config",
        lambda _project_id: {},
    )

    state = describe_autonomous_schedule("sha", "work_pickup")

    assert state["default_enabled"] is False
    assert state["enabled"] is False


def test_enabled_work_pickup_projects_require_explicit_opt_in(monkeypatch) -> None:
    projects = [
        {"id": "agent-hub"},
        {"id": "sha"},
        {"id": "portfolio-ai"},
    ]
    configs = {
        "agent-hub": {"work_pickup_enabled": True},
        "sha": {},
        "portfolio-ai": {"work_pickup_enabled": False},
    }

    monkeypatch.setattr("app.storage.projects.list_projects", lambda: projects)
    monkeypatch.setattr(
        "app.services.autonomous_schedule_registry.get_agent_config",
        lambda project_id: configs[str(project_id)],
    )

    assert _enabled_project_ids("work_pickup") == ["agent-hub"]
