"""Unit tests for Git workspace summary helpers."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from app.api.models.git_models import BranchInfo
from app.api.git_helpers.worktree_helpers import collect_worktrees
from app.utils._git_branches import build_repo_workspace_summary


class TestBuildRepoWorkspaceSummary:
    """Tests for per-repo branch/worktree summary counters."""

    def test_counts_active_orphan_and_prunable_task_branches(self, mocker) -> None:
        repo_path = Path("/repos/summitflow")
        mocker.patch(
            "app.utils._git_branches.get_all_branches",
            return_value=[
                BranchInfo(name="main", is_current=True, has_worktree=False),
                BranchInfo(name="task-123/main", is_current=False, has_worktree=True, task_id="task-123"),
                BranchInfo(name="task-456/main", is_current=False, has_worktree=False, task_id="task-456"),
                BranchInfo(name="task-789/main", is_current=False, has_worktree=False, task_id="task-789"),
            ],
        )
        mocker.patch(
            "app.utils._git_branches._get_active_worktrees",
            return_value=[
                SimpleNamespace(task_id="task-123", branch="task-123/main", path=Path("/wt/task-123")),
                SimpleNamespace(task_id="task-999", branch="task-999/main", path=Path("/wt/task-999")),
            ],
        )
        mocker.patch("app.utils._git_branches._detect_base_branch", return_value="main")
        mocker.patch(
            "app.utils._git_branches._get_merged_branches",
            return_value={"main", "task-456/main"},
        )

        summary = build_repo_workspace_summary(repo_path)

        assert summary.active_worktrees == 2
        assert summary.branches_with_worktrees == 1
        assert summary.task_branches == 3
        assert summary.orphan_branches == 2
        assert summary.prunable_branches == 1
        assert summary.worktree_task_ids == ["task-123", "task-999"]


class TestCollectWorktrees:
    """Tests for Git Operations worktree collection."""

    def test_uses_cli_worktree_source_of_truth(self, mocker) -> None:
        mocker.patch(
            "app.api.git_helpers.worktree_helpers.get_active_worktrees",
            return_value=[
                SimpleNamespace(
                    task_id="task-123",
                    path=Path("/tmp/worktrees/summitflow/task-123"),
                    branch="task-123/main",
                    base_branch="main",
                    is_active=True,
                    project_id="summitflow",
                ),
            ],
        )

        worktrees = collect_worktrees()

        assert len(worktrees) == 1
        assert worktrees[0].task_id == "task-123"
        assert worktrees[0].project_id == "summitflow"
        assert worktrees[0].path == "/tmp/worktrees/summitflow/task-123"
