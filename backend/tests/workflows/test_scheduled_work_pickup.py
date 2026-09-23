from __future__ import annotations

from contextlib import contextmanager

import pytest

from app.services.autonomous_schedule_registry import describe_autonomous_schedule
from app.workflows import scheduled
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


@pytest.mark.asyncio
async def test_old_clock_checks_local_fence_while_holding_cutover_lock(mocker) -> None:
    events: list[str] = []

    @contextmanager
    def fake_lock(project_id: str, workflow_key: str):
        events.append(f"lock:{project_id}:{workflow_key}:enter")
        yield
        events.append("lock:exit")

    mocker.patch("app.storage.automation_clock_fences.automation_clock_lock", fake_lock)
    mocker.patch(
        "app.storage.automation_clock_fences.is_agent_hub_clock_fenced",
        side_effect=lambda *_args: (events.append("fence-check") or True),
    )
    profile_lookup = mocker.patch("app.services.agent_hub_automations.legacy_clock_owns")

    result = await scheduled._run_work_pickup_for_project("agent-hub")

    assert result["reason"] == "agent_hub_clock_fence"
    assert events == ["lock:agent-hub:work_pickup:enter", "fence-check", "lock:exit"]
    profile_lookup.assert_not_called()


@pytest.mark.asyncio
async def test_old_clock_holds_shared_lock_through_admission_and_domain_work(mocker, monkeypatch) -> None:
    events: list[str] = []

    @contextmanager
    def fake_lock(_project_id: str, _workflow_key: str):
        events.append("lock-enter")
        yield
        events.append("lock-exit")

    mocker.patch("app.storage.automation_clock_fences.automation_clock_lock", fake_lock)
    mocker.patch(
        "app.storage.automation_clock_fences.is_agent_hub_clock_fenced",
        side_effect=lambda *_args: (events.append("fence-check") or False),
    )
    mocker.patch(
        "app.services.agent_hub_automations.legacy_clock_owns",
        side_effect=lambda *_args: (events.append("profile-check") or True),
    )
    monkeypatch.setattr(scheduled, "_project_schedule_enabled", lambda *_args: True)
    monkeypatch.setattr(scheduled, "_work_pickup_due", lambda *_args: True)
    mocker.patch("app.workflows.pipeline._make_dispatch_callback", return_value=object())
    pickup = mocker.patch("app.tasks.autonomous.pickup.autonomous_work_pickup")
    record = mocker.patch("app.workflows.scheduled._record_work_pickup")

    async def fake_to_thread(function, *_args, **_kwargs):
        events.append("domain" if function is pickup else "record")
        return {"dispatched": 0}

    monkeypatch.setattr(scheduled.asyncio, "to_thread", fake_to_thread)

    await scheduled._run_work_pickup_for_project("agent-hub")

    assert events == [
        "lock-enter",
        "fence-check",
        "profile-check",
        "domain",
        "record",
        "lock-exit",
    ]
    pickup.assert_not_called()
    record.assert_not_called()
