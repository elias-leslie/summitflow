"""Tests for fail-closed legacy-clock ownership lookup."""

from __future__ import annotations

from unittest.mock import Mock

from app.services import agent_hub_automations


def test_legacy_clock_requires_unique_matching_profile_with_legacy_owner(mocker, monkeypatch) -> None:
    monkeypatch.setenv("INTERNAL_SERVICE_SECRET", "shared-secret")
    response = Mock()
    response.json.return_value = {
        "items": [
            {"project_id": "project-1", "workflow_key": "summitflow/work_pickup", "clock_owner": "legacy"},
            {"project_id": "project-1", "workflow_key": "summitflow/task_generation", "clock_owner": "agent_hub"},
        ]
    }
    response.raise_for_status.return_value = None
    get = mocker.patch("app.services.agent_hub_automations.httpx.get", return_value=response)

    assert agent_hub_automations.legacy_clock_owns("project-1", "work_pickup")
    assert not agent_hub_automations.legacy_clock_owns("project-1", "task_generation")
    assert get.call_args.kwargs["headers"]["X-Agent-Hub-Internal"] == "shared-secret"


def test_legacy_clock_fails_closed_for_missing_secret_or_ambiguous_profiles(mocker, monkeypatch) -> None:
    monkeypatch.delenv("INTERNAL_SERVICE_SECRET", raising=False)
    get = mocker.patch("app.services.agent_hub_automations.httpx.get")
    assert not agent_hub_automations.legacy_clock_owns("project-1", "work_pickup")
    get.assert_not_called()

    monkeypatch.setenv("INTERNAL_SERVICE_SECRET", "shared-secret")
    response = Mock()
    response.json.return_value = [
        {"project_id": "project-1", "workflow_key": "summitflow/work_pickup", "clock_owner": "legacy"},
        {"project_id": "project-1", "workflow_key": "summitflow/work_pickup", "clock_owner": "legacy"},
    ]
    response.raise_for_status.return_value = None
    get.return_value = response
    assert not agent_hub_automations.legacy_clock_owns("project-1", "work_pickup")
