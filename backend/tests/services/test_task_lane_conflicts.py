"""Tests for active lane blocking and conflict detection."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
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
    mock_client_cls = mocker.patch("app.services._lane_inventory.httpx.Client")
    mock_client_cls.return_value.__enter__.return_value = mock_client
    return mock_client


class TestTaskLaneConflicts:
    """Active lane blocking and stale lane conflict detection."""

    @patch("app.services.task_lane_preflight.task_store.get_task")
    def test_same_task_active_lane_blocks_dispatch(
        self,
        mock_get_task: MagicMock,
        mock_httpx_client: MagicMock,
    ) -> None:
        mock_get_task.return_value = {"id": "task-123", "status": "running"}
        mock_httpx_client.get.return_value = _mock_response(
            {
                "sessions": [
                    {
                        "id": "sess-1",
                        "external_id": "task-123",
                        "current_branch": "task-123/main",
                        "working_dir": "/tmp/lanes/task-123",
                    }
                ]
            }
        )

        result = check_task_lane_conflicts("task-123", "summitflow")

        assert result.issues
        assert result.overlap_kind == "same_task"
        assert result.disposition == "block"
        assert "Task already has an active session" in result.issues[0]
        assert result.owner_location == "sess-1 in checkout /tmp/lanes/task-123 on task-123/main"

    @patch("app.services.task_lane_preflight.task_store.get_task")
    def test_other_task_active_lane_blocks_parallel_dispatch(
        self,
        mock_get_task: MagicMock,
        mock_httpx_client: MagicMock,
    ) -> None:
        mock_get_task.return_value = {"id": "task-999", "status": "running"}
        mock_httpx_client.get.return_value = _mock_response(
            {
                "sessions": [
                    {
                        "id": "sess-2",
                        "external_id": "task-999",
                        "current_branch": "task-999/main",
                        "working_dir": "/home/testuser/summitflow",
                    }
                ]
            }
        )

        result = check_task_lane_conflicts("task-123", "summitflow")

        assert result.issues
        assert result.overlap_kind == "unscoped_target"
        assert result.conflicting_tasks == ["task-999"]
        assert result.owner_location == "sess-2 in checkout /home/testuser/summitflow on task-999/main"
        assert "Target task scope unavailable" in result.suggestions[-1]

    @patch("app.services.task_lane_preflight.task_store.get_task")
    def test_branch_named_lane_blocks_when_external_id_missing(
        self,
        mock_get_task: MagicMock,
        mock_httpx_client: MagicMock,
    ) -> None:
        mock_get_task.return_value = {"id": "task-999", "status": "running"}
        mock_httpx_client.get.return_value = _mock_response(
            {
                "sessions": [
                    {
                        "id": "sess-4",
                        "external_id": None,
                        "current_branch": "task-999/main",
                        "working_dir": "/tmp/lanes/task-999",
                    }
                ]
            }
        )

        result = check_task_lane_conflicts("task-123", "summitflow")

        assert result.issues
        assert result.overlap_kind == "unscoped_target"
        assert result.conflicting_tasks == ["task-999"]
        assert result.owner_location == "sess-4 in checkout /tmp/lanes/task-999 on task-999/main"

    def test_retired_workstream_does_not_block_dispatch(
        self,
        mock_httpx_client: MagicMock,
    ) -> None:
        mock_httpx_client.get.return_value = _mock_response(
            {"sessions": [{"id": "sess-3", "external_id": "task-999", "workstream_status": "retired"}]}
        )

        result = check_task_lane_conflicts("task-123", "summitflow")

        assert result.issues == []

    @patch("app.services.task_lane_preflight.task_store.get_task")
    def test_terminal_task_lane_is_ignored_even_if_session_is_active(
        self,
        mock_get_task: MagicMock,
        mock_httpx_client: MagicMock,
    ) -> None:
        mock_get_task.return_value = {"id": "task-999", "status": "cancelled"}
        mock_httpx_client.get.return_value = _mock_response(
            {"sessions": [{"id": "sess-5", "external_id": "task-999", "current_branch": "task-999/main"}]}
        )

        result = check_task_lane_conflicts("task-123", "summitflow")

        assert result.issues == []

    @patch("app.services.task_lane_preflight.task_store.get_task")
    def test_other_task_unscoped_planner_session_without_checkout_or_scope_does_not_block(
        self,
        mock_get_task: MagicMock,
        mock_httpx_client: MagicMock,
    ) -> None:
        mock_get_task.return_value = {"id": "task-999", "status": "pending"}
        mock_httpx_client.get.return_value = _mock_response(
            {
                "sessions": [
                    {
                        "id": "sess-planner",
                        "agent_slug": "planner",
                        "external_id": "task-999",
                        "current_branch": None,
                        "working_dir": None,
                        "observed_read_paths": [],
                        "observed_write_paths": [],
                    }
                ]
            }
        )

        result = check_task_lane_conflicts("task-123", "summitflow")

        assert result.issues == []

    @patch("app.services.task_lane_preflight.task_store.get_task")
    def test_same_task_stale_lane_points_to_reconcile_guidance(
        self,
        mock_get_task: MagicMock,
        mock_httpx_client: MagicMock,
    ) -> None:
        mock_get_task.return_value = {"id": "task-123", "status": "running"}
        stale_time = (datetime.now(UTC) - timedelta(minutes=31)).isoformat()
        mock_httpx_client.get.return_value = _mock_response(
            {
                "sessions": [
                    {
                        "id": "sess-stale",
                        "external_id": "task-123",
                        "current_branch": "task-123/main",
                        "working_dir": "/tmp/lanes/task-123",
                        "updated_at": stale_time,
                    }
                ]
            }
        )

        result = check_task_lane_conflicts("task-123", "summitflow")

        assert "likely stale active session" in result.issues[0]
        assert "st sessions list --status active --project summitflow" in result.suggestions[0]

    @patch("app.services.task_lane_preflight.task_store.get_task")
    def test_same_task_terminal_status_surfaces_leftover_lane_for_reconcile(
        self,
        mock_get_task: MagicMock,
        mock_httpx_client: MagicMock,
    ) -> None:
        mock_get_task.return_value = {"id": "task-123", "status": "cancelled"}
        mock_httpx_client.get.return_value = _mock_response(
            {
                "sessions": [
                    {
                        "id": "sess-leftover",
                        "external_id": "task-123",
                        "current_branch": "task-123/main",
                        "working_dir": "/tmp/lanes/task-123",
                    }
                ]
            }
        )

        result = check_task_lane_conflicts("task-123", "summitflow")

        assert result.overlap_kind == "stale_same_task"
        assert result.disposition == "reconcile"
        assert "Task status is cancelled but it still has a leftover live session" in result.issues[0]
        assert "Reconcile or retire the leftover same-task session" in result.suggestions[0]

    @patch("app.services.task_lane_preflight.task_store.get_task")
    def test_other_task_stale_lane_updates_project_guidance(
        self,
        mock_get_task: MagicMock,
        mock_httpx_client: MagicMock,
    ) -> None:
        mock_get_task.return_value = {"id": "task-999", "status": "running"}
        stale_time = (datetime.now(UTC) - timedelta(minutes=31)).isoformat()
        mock_httpx_client.get.return_value = _mock_response(
            {
                "sessions": [
                    {
                        "id": "sess-stale-other",
                        "external_id": "task-999",
                        "current_branch": "task-999/main",
                        "working_dir": "/tmp/lanes/task-999",
                        "updated_at": stale_time,
                    }
                ]
            }
        )

        result = check_task_lane_conflicts("task-123", "summitflow")

        assert result.overlap_kind == "stale_lane"
        assert "likely stale active coding session" in result.issues[0]
        assert result.conflicting_tasks == ["task-999"]
        assert "retire or reconcile it" in result.suggestions[1]
