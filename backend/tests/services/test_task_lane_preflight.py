"""Tests for live lane conflict checks."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from app.services.task_lane_preflight import check_task_lane_conflicts


def _mock_response(payload: dict[str, object]) -> MagicMock:
    response = MagicMock()
    response.json.return_value = payload
    response.raise_for_status.return_value = None
    return response


class TestTaskLanePreflight:
    """Lane conflict detection."""

    @patch("app.services.task_lane_preflight.httpx.Client")
    def test_same_task_active_lane_blocks_dispatch(self, mock_client_cls: MagicMock) -> None:
        mock_client = MagicMock()
        mock_client.get.return_value = _mock_response(
            {"sessions": [{"id": "sess-1", "external_id": "task-123", "current_branch": "task-123/main"}]}
        )
        mock_client_cls.return_value.__enter__.return_value = mock_client

        result = check_task_lane_conflicts("task-123", "summitflow")

        assert result.issues
        assert "active lane" in result.issues[0]

    @patch("app.services.task_lane_preflight.httpx.Client")
    def test_other_task_active_lane_blocks_parallel_dispatch(self, mock_client_cls: MagicMock) -> None:
        mock_client = MagicMock()
        mock_client.get.return_value = _mock_response(
            {"sessions": [{"id": "sess-2", "external_id": "task-999", "current_branch": "task-999/main"}]}
        )
        mock_client_cls.return_value.__enter__.return_value = mock_client

        result = check_task_lane_conflicts("task-123", "summitflow")

        assert result.issues
        assert result.conflicting_tasks == ["task-999"]

    @patch("app.services.task_lane_preflight.httpx.Client")
    def test_retired_workstream_does_not_block_dispatch(self, mock_client_cls: MagicMock) -> None:
        mock_client = MagicMock()
        mock_client.get.return_value = _mock_response(
            {"sessions": [{"id": "sess-3", "external_id": "task-999", "workstream_status": "retired"}]}
        )
        mock_client_cls.return_value.__enter__.return_value = mock_client

        result = check_task_lane_conflicts("task-123", "summitflow")

        assert result.issues == []
