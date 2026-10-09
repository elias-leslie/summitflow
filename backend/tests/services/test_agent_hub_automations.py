"""Tests for fail-closed legacy-clock ownership lookup."""

from __future__ import annotations

from unittest.mock import MagicMock

from app.services import agent_hub_automations


def _client(mocker, profiles: object) -> MagicMock:
    client = MagicMock()
    client.__enter__.return_value = client
    client.list_automation_profiles.return_value = profiles
    mocker.patch.object(agent_hub_automations, "get_sync_client", return_value=client)
    return client


def test_legacy_clock_requires_unique_matching_profile_with_legacy_owner(mocker, monkeypatch) -> None:
    monkeypatch.setenv("INTERNAL_SERVICE_SECRET", "shared-secret")
    client = _client(mocker, [
        {"project_id": "project-1", "workflow_key": "summitflow/work_pickup", "clock_owner": "legacy"},
        {"project_id": "project-1", "workflow_key": "summitflow/task_generation", "clock_owner": "agent_hub"},
    ])

    assert agent_hub_automations.legacy_clock_owns("project-1", "work_pickup")
    assert not agent_hub_automations.legacy_clock_owns("project-1", "task_generation")
    assert client.list_automation_profiles.call_args.args == ("project-1",)
    assert client.list_automation_profiles.call_args.kwargs["internal_secret"] == "shared-secret"


def test_legacy_clock_fails_closed_for_missing_secret_or_ambiguous_profiles(mocker, monkeypatch) -> None:
    monkeypatch.delenv("INTERNAL_SERVICE_SECRET", raising=False)
    client = _client(mocker, [])
    assert not agent_hub_automations.legacy_clock_owns("project-1", "work_pickup")
    client.list_automation_profiles.assert_not_called()

    monkeypatch.setenv("INTERNAL_SERVICE_SECRET", "shared-secret")
    client.list_automation_profiles.return_value = [
        {"project_id": "project-1", "workflow_key": "summitflow/work_pickup", "clock_owner": "legacy"},
        {"project_id": "project-1", "workflow_key": "summitflow/work_pickup", "clock_owner": "legacy"},
    ]
    assert not agent_hub_automations.legacy_clock_owns("project-1", "work_pickup")

    client.list_automation_profiles.side_effect = RuntimeError("agent hub down")
    assert not agent_hub_automations.legacy_clock_owns("project-1", "work_pickup")
