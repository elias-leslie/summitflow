"""Unit tests for Git workspace summary helpers."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from app.api.git_helpers.worktree_helpers import collect_worktrees
from app.api.models.git_models import BranchInfo
from app.utils._git_branches import (
    assess_orphan_task_branches,
    build_repo_workspace_summary,
    prune_closed_orphan_task_branches,
)
from app.utils._git_core import _resolve_project_id


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
        mocker.patch(
            "app.utils._git_core.has_uncommitted_changes",
            side_effect=[False, False, True],
        )
        mocker.patch("app.utils._git_branches._detect_base_branch", return_value="main")
        mocker.patch(
            "app.utils._git_branches._get_merged_branches",
            return_value={"main", "task-456/main"},
        )
        mocker.patch(
            "app.utils._git_branches.list_equivalent_orphan_task_branches",
            return_value=[],
        )
        mocker.patch(
            "app.storage.tasks.get_task",
            return_value={"id": "task-789", "status": "running"},
        )
        mocker.patch(
            "app.utils._git_branches._branch_diff_paths",
            side_effect=[
                ["backend/app/example.py"],
                ["backend/app/other.py"],
            ],
        )
        mocker.patch(
            "app.utils._git_branches._branch_commits_ahead",
            side_effect=[1, 2],
        )

        summary = build_repo_workspace_summary(repo_path, project_id="summitflow")

        assert summary.active_worktrees == 2
        assert summary.dirty_worktrees == 1
        assert summary.branches_with_worktrees == 1
        assert summary.task_branches == 3
        assert summary.orphan_branches == 2
        assert summary.prunable_branches == 1
        assert summary.needs_cleanup
        assert summary.worktree_task_ids == ["task-123", "task-999"]
        assert summary.salvage_task_ids == []
        assert summary.review_orphan_task_ids == ["task-789"]

    def test_marks_dirty_main_repo_as_cleanup_even_without_worktrees(self, mocker) -> None:
        repo_path = Path("/repos/test2")
        mocker.patch(
            "app.utils._git_branches.get_all_branches",
            return_value=[BranchInfo(name="main", is_current=True, has_worktree=False)],
        )
        mocker.patch("app.utils._git_branches._get_active_worktrees", return_value=[])
        mocker.patch(
            "app.utils._git_core.has_uncommitted_changes",
            return_value=True,
        )
        mocker.patch(
            "app.utils._git_branches.list_prunable_task_branches",
            return_value=[],
        )
        mocker.patch(
            "app.utils._git_branches.assess_orphan_task_branches",
            return_value=[],
        )
        mocker.patch("app.utils._git_branches._detect_base_branch", return_value="main")

        summary = build_repo_workspace_summary(repo_path, project_id="test2")

        assert summary.active_worktrees == 0
        assert summary.dirty_worktrees == 0
        assert summary.dirty_main_repo is True
        assert summary.needs_cleanup is True

    def test_uses_explicit_project_id_for_worktree_lookup(self, mocker) -> None:
        repo_path = Path("/repos/custom-folder")
        mock_branches = mocker.patch(
            "app.utils._git_branches.get_all_branches",
            return_value=[],
        )
        mock_worktrees = mocker.patch(
            "app.utils._git_branches._get_active_worktrees",
            return_value=[],
        )
        mocker.patch(
            "app.utils._git_core.has_uncommitted_changes",
            return_value=False,
        )
        mocker.patch(
            "app.utils._git_branches.list_prunable_task_branches",
            return_value=[],
        )
        mocker.patch(
            "app.utils._git_branches.assess_orphan_task_branches",
            return_value=[],
        )
        mocker.patch("app.utils._git_branches._detect_base_branch", return_value="main")

        build_repo_workspace_summary(repo_path, project_id="project-alpha")

        mock_branches.assert_called_once_with(repo_path, "project-alpha", active_worktrees=[])
        mock_worktrees.assert_called_once_with("project-alpha")


class TestResolveProjectId:
    """Tests for repository-to-project resolution."""

    def test_returns_registered_project_id_only_for_project_roots(self, mocker) -> None:
        mocker.patch(
            "app.utils._git_core._query_db_project_roots",
            return_value=[
                ("summitflow", "/repos/summitflow"),
                ("agent-hub", "/repos/agent-hub"),
            ],
        )
        mocker.patch(
            "app.utils._git_core._query_db_extra_repos",
            return_value=[
                (".claude", "/home/kasadis/.claude"),
                ("persona-sandbox", "/home/kasadis/persona-sandbox"),
            ],
        )
        mocker.patch(
            "app.utils._git_core._load_repo_paths_from_file",
            return_value=[Path("/home/kasadis/.codex")],
        )

        assert _resolve_project_id(Path("/repos/summitflow")) == "summitflow"
        assert _resolve_project_id(Path("/home/kasadis/.claude")) is None
        assert _resolve_project_id(Path("/home/kasadis/persona-sandbox")) is None
        assert _resolve_project_id(Path("/home/kasadis/.codex")) is None


class TestCollectWorktrees:
    """Tests for Git Operations worktree collection."""

    def test_uses_cli_worktree_source_of_truth(self, mocker) -> None:
        mocker.patch(
            "cli.lib.worktree.get_active_worktrees",
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


class TestPruneClosedOrphanTaskBranches:
    """Tests for orphan branch pruning linked to closed tasks."""

    def test_prunes_only_closed_orphan_task_branches(self, mocker) -> None:
        repo_path = Path("/repos/summitflow")
        mocker.patch(
            "app.utils._git_branches.get_all_branches",
            return_value=[
                BranchInfo(name="main", is_current=True, has_worktree=False),
                BranchInfo(name="task-done/main", is_current=False, has_worktree=False, task_id="task-done"),
                BranchInfo(name="task-live/main", is_current=False, has_worktree=False, task_id="task-live"),
                BranchInfo(name="task-worktree/main", is_current=False, has_worktree=True, task_id="task-worktree"),
            ],
        )
        mocker.patch(
            "app.storage.tasks.get_task",
            side_effect=[
                {"id": "task-done", "status": "completed"},
                {"id": "task-live", "status": "running"},
            ],
        )
        mock_run_git = mocker.patch("app.utils._git_branches.run_git")
        mock_run_git.side_effect = [
            SimpleNamespace(returncode=0, stdout="main\n"),
            SimpleNamespace(returncode=0, stdout="", stderr=""),
        ]
        mocker.patch("app.utils._git_branches._detect_base_branch", return_value="main")

        removed = prune_closed_orphan_task_branches(repo_path)

        assert removed == ["task-done/main"]
        assert mock_run_git.call_args_list[1].args[0] == ["branch", "-D", "task-done/main"]


class TestAssessOrphanTaskBranches:
    """Tests for orphan branch resolution classification."""

    def test_marks_missing_task_branches_as_salvage_and_flags_node_modules(self, mocker) -> None:
        repo_path = Path("/repos/monkey-fight")
        mocker.patch(
            "app.utils._git_branches.get_all_branches",
            return_value=[
                BranchInfo(name="task-missing/main", is_current=False, has_worktree=False, task_id="task-missing"),
            ],
        )
        mocker.patch("app.utils._git_branches._detect_base_branch", return_value="main")
        mocker.patch("app.utils._git_branches._get_merged_branches", return_value={"main"})
        mocker.patch("app.utils._git_branches.list_equivalent_orphan_task_branches", return_value=[])
        mocker.patch("app.storage.tasks.get_task", return_value=None)
        mocker.patch(
            "app.utils._git_branches._branch_diff_paths",
            return_value=["node_modules", "src/scenes/game/BiomeRevealCard.ts"],
        )
        mocker.patch("app.utils._git_branches._branch_commits_ahead", return_value=2)

        items = assess_orphan_task_branches(repo_path)

        assert len(items) == 1
        assert items[0].resolution == "salvage"
        assert items[0].task_status is None
        assert items[0].has_node_modules_artifact
