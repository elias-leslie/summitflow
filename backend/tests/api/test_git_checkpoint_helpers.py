"""Tests for git checkpoint helper utilities."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from app.api.git_helpers.checkpoint_helpers import enrich_snapshots
from app.api.models.git_models import SnapshotInfo


def _snapshot(task_id: str) -> SnapshotInfo:
    return SnapshotInfo(
        task_id=task_id,
        task_title="",
        sha="abcdef1234567890",
        short_sha="abcdef1",
        created_at="2026-03-01T00:00:00+00:00",
        project_id="",
        repo_name="summitflow",
        is_current=False,
        commits_ahead=0,
    )


@patch("app.api.git_helpers.checkpoint_helpers.get_cursor")
def test_enrich_snapshots_updates_matching_task_metadata(mock_get_cursor: MagicMock) -> None:
    mock_cursor = MagicMock()
    mock_get_cursor.return_value.__enter__.return_value = mock_cursor
    mock_cursor.fetchall.return_value = [("task-1", "Fix sidebar bug", "proj-1")]

    first = _snapshot("task-1")
    second = _snapshot("task-2")

    enrich_snapshots([first, second])

    query, params = mock_cursor.execute.call_args.args
    assert not isinstance(query, str)
    assert params == ("task-1", "task-2")
    assert first.task_title == "Fix sidebar bug"
    assert first.project_id == "proj-1"
    assert second.task_title == ""
    assert second.project_id == ""


@patch("app.api.git_helpers.checkpoint_helpers.get_cursor")
def test_enrich_snapshots_skips_database_when_empty(mock_get_cursor: MagicMock) -> None:
    enrich_snapshots([])

    mock_get_cursor.assert_not_called()
