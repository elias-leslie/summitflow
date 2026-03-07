"""Tests for live lane conflict checks."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch

from app.services.task_lane_preflight import check_task_lane_conflicts


def _mock_response(payload: dict[str, object]) -> MagicMock:
    response = MagicMock()
    response.json.return_value = payload
    response.raise_for_status.return_value = None
    return response


class TestTaskLanePreflight:
    """Lane conflict detection."""

    @patch("app.services.task_lane_preflight.task_store.get_task")
    @patch("app.services.task_lane_preflight.httpx.Client")
    def test_same_task_active_lane_blocks_dispatch(
        self,
        mock_client_cls: MagicMock,
        mock_get_task: MagicMock,
    ) -> None:
        mock_get_task.return_value = {"id": "task-123", "status": "running"}
        mock_client = MagicMock()
        mock_client.get.return_value = _mock_response(
            {
                "sessions": [
                    {
                        "id": "sess-1",
                        "external_id": "task-123",
                        "current_branch": "task-123/main",
                        "working_dir": "/tmp/worktrees/task-123",
                        "is_worktree": True,
                    }
                ]
            }
        )
        mock_client_cls.return_value.__enter__.return_value = mock_client

        result = check_task_lane_conflicts("task-123", "summitflow")

        assert result.issues
        assert "active lane" in result.issues[0]
        assert "/tmp/worktrees/task-123" in result.issues[0]

    @patch("app.services.task_lane_preflight.task_store.get_task")
    @patch("app.services.task_lane_preflight.httpx.Client")
    def test_other_task_active_lane_blocks_parallel_dispatch(
        self,
        mock_client_cls: MagicMock,
        mock_get_task: MagicMock,
    ) -> None:
        mock_get_task.return_value = {"id": "task-999", "status": "running"}
        mock_client = MagicMock()
        mock_client.get.return_value = _mock_response(
            {
                "sessions": [
                    {
                        "id": "sess-2",
                        "external_id": "task-999",
                        "current_branch": "task-999/main",
                        "working_dir": "/home/kasadis/summitflow",
                        "is_worktree": False,
                    }
                ]
            }
        )
        mock_client_cls.return_value.__enter__.return_value = mock_client

        result = check_task_lane_conflicts("task-123", "summitflow")

        assert result.issues
        assert result.conflicting_tasks == ["task-999"]
        assert "repo /home/kasadis/summitflow" in result.suggestions[0]

    @patch("app.services.task_lane_preflight.task_store.get_task")
    @patch("app.services.task_lane_preflight.httpx.Client")
    def test_branch_named_lane_blocks_when_external_id_missing(
        self,
        mock_client_cls: MagicMock,
        mock_get_task: MagicMock,
    ) -> None:
        mock_get_task.return_value = {"id": "task-999", "status": "running"}
        mock_client = MagicMock()
        mock_client.get.return_value = _mock_response(
            {
                "sessions": [
                    {
                        "id": "sess-4",
                        "external_id": None,
                        "current_branch": "task-999/main",
                        "working_dir": "/tmp/worktrees/task-999",
                        "is_worktree": True,
                    }
                ]
            }
        )
        mock_client_cls.return_value.__enter__.return_value = mock_client

        result = check_task_lane_conflicts("task-123", "summitflow")

        assert result.issues
        assert result.conflicting_tasks == ["task-999"]
        assert "worktree /tmp/worktrees/task-999" in result.suggestions[0]

    @patch("app.services.task_lane_preflight.httpx.Client")
    def test_retired_workstream_does_not_block_dispatch(self, mock_client_cls: MagicMock) -> None:
        mock_client = MagicMock()
        mock_client.get.return_value = _mock_response(
            {"sessions": [{"id": "sess-3", "external_id": "task-999", "workstream_status": "retired"}]}
        )
        mock_client_cls.return_value.__enter__.return_value = mock_client

        result = check_task_lane_conflicts("task-123", "summitflow")

        assert result.issues == []

    @patch("app.services.task_lane_preflight.task_store.get_task")
    @patch("app.services.task_lane_preflight.httpx.Client")
    def test_terminal_task_lane_is_ignored_even_if_session_is_active(
        self,
        mock_client_cls: MagicMock,
        mock_get_task: MagicMock,
    ) -> None:
        mock_get_task.return_value = {"id": "task-999", "status": "blocked"}
        mock_client = MagicMock()
        mock_client.get.return_value = _mock_response(
            {"sessions": [{"id": "sess-5", "external_id": "task-999", "current_branch": "task-999/main"}]}
        )
        mock_client_cls.return_value.__enter__.return_value = mock_client

        result = check_task_lane_conflicts("task-123", "summitflow")

        assert result.issues == []

    @patch("app.services.task_lane_preflight.task_store.get_task")
    @patch("app.services.task_lane_preflight.httpx.Client")
    def test_same_task_stale_lane_points_to_reconcile_guidance(
        self,
        mock_client_cls: MagicMock,
        mock_get_task: MagicMock,
    ) -> None:
        mock_get_task.return_value = {"id": "task-123", "status": "running"}
        stale_time = (datetime.now(UTC) - timedelta(hours=5)).isoformat()
        mock_client = MagicMock()
        mock_client.get.return_value = _mock_response(
            {
                "sessions": [
                    {
                        "id": "sess-stale",
                        "external_id": "task-123",
                        "current_branch": "task-123/main",
                        "working_dir": "/tmp/worktrees/task-123",
                        "is_worktree": True,
                        "updated_at": stale_time,
                    }
                ]
            }
        )
        mock_client_cls.return_value.__enter__.return_value = mock_client

        result = check_task_lane_conflicts("task-123", "summitflow")

        assert "likely stale active lane" in result.issues[0]
        assert "st sessions list --status active --project summitflow" in result.suggestions[0]

    @patch("app.services.task_lane_preflight.task_store.get_task")
    @patch("app.services.task_lane_preflight.httpx.Client")
    def test_other_task_stale_lane_updates_project_guidance(
        self,
        mock_client_cls: MagicMock,
        mock_get_task: MagicMock,
    ) -> None:
        mock_get_task.return_value = {"id": "task-999", "status": "running"}
        stale_time = (datetime.now(UTC) - timedelta(hours=5)).isoformat()
        mock_client = MagicMock()
        mock_client.get.return_value = _mock_response(
            {
                "sessions": [
                    {
                        "id": "sess-stale-other",
                        "external_id": "task-999",
                        "current_branch": "task-999/main",
                        "working_dir": "/tmp/worktrees/task-999",
                        "is_worktree": True,
                        "updated_at": stale_time,
                    }
                ]
            }
        )
        mock_client_cls.return_value.__enter__.return_value = mock_client

        result = check_task_lane_conflicts("task-123", "summitflow")

        assert "likely stale active coding lane" in result.issues[0]
        assert result.conflicting_tasks == ["task-999"]
        assert "retire or reconcile it" in result.suggestions[1]
