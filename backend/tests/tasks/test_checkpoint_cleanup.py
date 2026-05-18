"""Tests for autonomous checkpoint cleanup safety."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from app.tasks.autonomous.cleanup.checkpoint_cleanup import cleanup_task_checkpoint


@patch("cli.lib.checkpoint_metadata.get_meta_path")
def test_cleanup_task_checkpoint_skips_when_metadata_missing(
    mock_meta_path: MagicMock,
    tmp_path: Path,
) -> None:
    missing = tmp_path / "missing.meta.json"
    mock_meta_path.return_value = missing

    result = cleanup_task_checkpoint("task-1", project_id="proj")

    assert result == {"task_id": "task-1", "status": "skipped", "reason": "no_checkpoint"}
    assert not missing.exists()


@patch("cli.lib.checkpoint_metadata.get_meta_path")
def test_cleanup_task_checkpoint_removes_metadata_when_present(
    mock_meta_path: MagicMock,
    tmp_path: Path,
) -> None:
    meta_path = tmp_path / "task-1.meta.json"
    meta_path.write_text("{}")
    mock_meta_path.return_value = meta_path

    result = cleanup_task_checkpoint("task-1", project_id="proj")

    assert result == {"task_id": "task-1", "status": "cleaned"}
    assert not meta_path.exists()


def test_cleanup_task_checkpoint_skips_when_project_id_missing() -> None:
    result = cleanup_task_checkpoint("task-1", project_id=None)
    assert result == {
        "task_id": "task-1",
        "status": "skipped",
        "reason": "missing_project_id",
    }
