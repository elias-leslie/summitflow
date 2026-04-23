from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from app.services.task_checkout.operations import create_task_checkout


@patch("app.services.task_checkout.operations.create_checkpoint_metadata")
@patch("app.services.task_checkout.operations._resolve_base_branch", return_value="main")
@patch("app.services.task_checkout.operations._current_branch", return_value="task-1/main")
@patch("app.services.task_checkout.operations._branch_exists", return_value=True)
@patch("app.services.task_checkout.operations._project_root")
def test_reused_branch_recreates_checkpoint_metadata(
    mock_project_root: MagicMock,
    mock_branch_exists: MagicMock,
    mock_current_branch: MagicMock,
    mock_resolve_base: MagicMock,
    mock_checkpoint: MagicMock,
) -> None:
    project_root = Path("/tmp/summitflow")
    mock_project_root.return_value = project_root

    checkout = create_task_checkout("task-1", "summitflow")

    assert checkout is not None
    assert checkout.path == project_root
    assert checkout.branch == "task-1/main"
    assert checkout.base_branch == "main"
    mock_branch_exists.assert_called_once_with("task-1/main", project_root)
    mock_current_branch.assert_called_once_with(project_root)
    mock_resolve_base.assert_called_once_with("task-1", "summitflow")
    mock_checkpoint.assert_called_once_with(
        task_id="task-1",
        project_id="summitflow",
        base_branch="main",
    )
