"""Tests for ownership/inventory payload handling in lane conflict checks."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.services.task_lane_preflight import check_task_lane_conflicts


def _mock_response(payload: dict[str, object]) -> MagicMock:
    response = MagicMock()
    response.json.return_value = payload
    response.raise_for_status.return_value = None
    return response


@pytest.fixture
def mock_httpx_client(mocker):
    mock_client = MagicMock()
    mock_client_cls = mocker.patch("app.services.task_lane_preflight.httpx.Client")
    mock_client_cls.return_value.__enter__.return_value = mock_client
    return mock_client


class TestTaskLaneOwnership:
    """Ownership inventory payload mapping and fallback behaviour."""

    @patch("app.services.task_lane_preflight.task_store.get_task")
    def test_ownership_inventory_payload_maps_to_live_lane_sessions(
        self,
        mock_get_task: MagicMock,
        mock_httpx_client: MagicMock,
    ) -> None:
        mock_get_task.return_value = {"id": "task-999", "status": "running"}
        mock_httpx_client.get.return_value = _mock_response(
            {
                "project_id": "summitflow",
                "generated_at": "2026-03-07T18:00:00Z",
                "active_owners": [
                    {
                        "task_id": "task-999",
                        "session_id": "sess-ownership",
                        "branch": "task-999/main",
                        "worktree_path": "/tmp/worktrees/task-999",
                        "is_worktree": True,
                        "session_status": "active",
                        "workstream_status": "authoritative",
                        "ownership_kind": "scoped",
                        "scope_paths": ["backend/app/foo.py"],
                    }
                ],
            }
        )

        result = check_task_lane_conflicts("task-123", "summitflow")

        assert result.issues
        assert result.conflicting_tasks == ["task-999"]
        assert "worktree /tmp/worktrees/task-999" in result.suggestions[0]
        assert result.active_specialists == []

    def test_ownership_inventory_payload_summarizes_active_specialists(
        self,
        mock_httpx_client: MagicMock,
    ) -> None:
        mock_httpx_client.get.return_value = _mock_response(
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
        mock_httpx_client: MagicMock,
    ) -> None:
        mock_get_task.return_value = {"id": "task-999", "status": "running"}
        not_found = _mock_response({})
        not_found.status_code = 404
        legacy = _mock_response(
            {
                "sessions": [
                    {
                        "id": "sess-legacy",
                        "external_id": "task-999",
                        "current_branch": "task-999/main",
                        "working_dir": "/home/kasadis/summitflow",
                        "is_worktree": False,
                    }
                ]
            }
        )
        mock_httpx_client.get.side_effect = [not_found, legacy]

        result = check_task_lane_conflicts("task-123", "summitflow")

        assert result.issues
        assert result.conflicting_tasks == ["task-999"]
        assert "repo /home/kasadis/summitflow" in result.suggestions[0]
