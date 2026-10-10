"""Tests for ownership/inventory payload handling in lane conflict checks."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import pytest
from agent_hub.exceptions import AgentHubError
from agent_hub.models.session import SessionListItem, SessionListResponse

from app.services.task_lane_preflight import check_task_lane_conflicts

_SESSION_TIME = datetime(2026, 3, 7, 18, tzinfo=UTC)


@pytest.fixture
def mock_agent_hub_client(mocker):
    mock_client = MagicMock()
    mock_get_client = mocker.patch("app.services._lane_inventory.get_sync_client")
    mock_get_client.return_value.__enter__.return_value = mock_client
    return mock_client


class TestTaskLaneOwnership:
    """Ownership inventory payload mapping and fallback behaviour."""

    @patch("app.services.task_lane_preflight.task_store.get_task")
    def test_ownership_inventory_payload_maps_to_live_lane_sessions(
        self,
        mock_get_task: MagicMock,
        mock_agent_hub_client: MagicMock,
    ) -> None:
        mock_get_task.return_value = {"id": "task-999", "status": "running"}
        mock_agent_hub_client.get_project_ownership.return_value = (
            {
                "project_id": "summitflow",
                "generated_at": "2026-03-07T18:00:00Z",
                "active_owners": [
                    {
                        "task_id": "task-999",
                        "session_id": "sess-ownership",
                        "branch": "task-999/main",
                        "checkout_path": "/tmp/lanes/task-999",
                        "session_status": "active",
                        "workstream_status": "authoritative",
                        "ownership_kind": "scoped",
                        "scope_paths": ["backend/app/foo.py"],
                    }
                ],
            }
        )

        result = check_task_lane_conflicts("task-123", "summitflow")

        assert result.issues == []
        assert result.conflicting_tasks == []
        assert result.owner_location is None
        assert result.active_specialists == []

    def test_ownership_inventory_payload_summarizes_active_specialists(
        self,
        mock_agent_hub_client: MagicMock,
    ) -> None:
        mock_agent_hub_client.get_project_ownership.return_value = (
            {
                "project_id": "summitflow",
                "generated_at": "2026-03-07T18:00:00Z",
                "active_owners": [],
                "active_specialists": [
                    {
                        "session_id": "spec-1",
                        "agent_slug": "reviewer",
                        "project_id": "summitflow",
                        "request_source": "dispatch",
                        "age_minutes": 2,
                    },
                    {
                        "session_id": "spec-2",
                        "agent_slug": "reviewer",
                        "project_id": "summitflow",
                        "request_source": "dispatch",
                        "age_minutes": 5,
                    },
                ],
            }
        )

        result = check_task_lane_conflicts("task-123", "summitflow")

        assert result.issues == []
        assert result.active_specialists == [
            {
                "agent_slug": "reviewer",
                "count": 2,
                "request_sources": ["dispatch"],
                "session_ids": ["spec-1", "spec-2"],
                "newest_age_minutes": 2,
                "oldest_age_minutes": 5,
            }
        ]

    @patch("app.services.task_lane_preflight.task_store.get_task")
    def test_ownership_endpoint_404_falls_back_to_legacy_sessions(
        self,
        mock_get_task: MagicMock,
        mock_agent_hub_client: MagicMock,
    ) -> None:
        mock_get_task.return_value = {"id": "task-999", "status": "running"}
        mock_agent_hub_client.get_project_ownership.side_effect = AgentHubError("Not Found", status_code=404)
        mock_agent_hub_client.list_sessions.return_value = SessionListResponse(
            sessions=[
                SessionListItem(
                    id="sess-legacy",
                    project_id="summitflow",
                    provider="claude",
                    model="claude-opus-5-5",
                    status="active",
                    message_count=0,
                    external_id="task-999",
                    current_branch="task-999/main",
                    working_dir="/home/testuser/summitflow",
                    created_at=_SESSION_TIME,
                    updated_at=_SESSION_TIME,
                )
            ],
            total=1,
            page=1,
            page_size=100,
        )

        result = check_task_lane_conflicts("task-123", "summitflow")

        assert result.issues == []
        assert result.conflicting_tasks == []
        assert result.owner_location is None
