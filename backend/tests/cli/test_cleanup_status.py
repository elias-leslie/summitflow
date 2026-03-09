"""Tests for `st cleanup status` hygiene summary output."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from typer.testing import CliRunner

from cli.commands.cleanup import app, build_cleanup_status_payload
from cli.commands.cleanup_analysis import CleanupAction, analyze_worktree

runner = CliRunner()


def test_build_cleanup_status_payload_aggregates_repo_hygiene() -> None:
    repo_paths = [Path("/repos/summitflow"), Path("/repos/agent-hub")]
    summitflow_worktrees = [
        SimpleNamespace(task_id="task-1", path=Path("/wt/1"), branch="task-1/main", base_branch="main", project_id="summitflow"),
        SimpleNamespace(task_id="task-2", path=Path("/wt/2"), branch="task-2/main", base_branch="main", project_id="summitflow"),
    ]

    with (
        patch("cli.commands.cleanup._get_managed_repos", return_value=repo_paths),
        patch("cli.commands.cleanup.get_project_id", return_value=None),
        patch(
            "cli.commands.cleanup.build_repo_workspace_summary",
            side_effect=[
                SimpleNamespace(
                    active_worktrees=2,
                    orphan_branches=1,
                    prunable_branches=1,
                    worktree_task_ids=["task-1", "task-2"],
                ),
                SimpleNamespace(
                    active_worktrees=0,
                    orphan_branches=0,
                    prunable_branches=0,
                    worktree_task_ids=[],
                ),
            ],
        ),
        patch(
            "cli.commands.cleanup.get_active_worktrees",
            side_effect=[
                summitflow_worktrees,
                summitflow_worktrees,
                [],
            ],
        ),
        patch(
            "cli.commands.cleanup.has_uncommitted_changes",
            side_effect=[True, False],
        ),
        patch(
            "cli.commands.cleanup.analyze_worktree",
            side_effect=[
                SimpleNamespace(
                    worktree=summitflow_worktrees[0],
                    action=CleanupAction.NEEDS_MERGE,
                    task_status="completed",
                ),
                SimpleNamespace(
                    worktree=summitflow_worktrees[1],
                    action=CleanupAction.MANUAL_REVIEW,
                    task_status="blocked",
                ),
            ],
        ),
    ):
        payload = build_cleanup_status_payload(all_projects=True)

    assert payload["summary"] == {
        "repos": 2,
        "repos_needing_cleanup": 1,
        "active_worktrees": 2,
        "dirty_worktrees": 1,
        "orphan_task_branches": 1,
        "prunable_task_branches": 1,
    }
    assert payload["repositories"][0]["project_id"] == "summitflow"
    assert payload["repositories"][0]["needs_cleanup"] is True
    assert payload["repositories"][0]["needs_merge_tasks"] == ["task-1"]
    assert payload["repositories"][0]["review_tasks"] == ["task-2"]
    assert payload["repositories"][1]["project_id"] == "agent-hub"
    assert payload["repositories"][1]["needs_cleanup"] is False
    assert payload["total"] == 2


def test_cleanup_status_compact_reports_cross_repo_summary() -> None:
    repo_paths = [Path("/repos/summitflow"), Path("/repos/agent-hub")]
    summitflow_worktrees = [
        SimpleNamespace(task_id="task-1", path=Path("/wt/1"), branch="task-1/main", base_branch="main", project_id="summitflow"),
    ]

    with (
        patch("cli.commands.cleanup._get_managed_repos", return_value=repo_paths),
        patch("cli.commands.cleanup.get_project_id", return_value=None),
        patch(
            "cli.commands.cleanup.build_repo_workspace_summary",
            side_effect=[
                SimpleNamespace(
                    active_worktrees=1,
                    orphan_branches=1,
                    prunable_branches=0,
                    worktree_task_ids=["task-1"],
                ),
                SimpleNamespace(
                    active_worktrees=0,
                    orphan_branches=0,
                    prunable_branches=0,
                    worktree_task_ids=[],
                ),
            ],
        ),
        patch(
            "cli.commands.cleanup.get_active_worktrees",
            side_effect=[
                summitflow_worktrees,
                summitflow_worktrees,
                [],
            ],
        ),
        patch("cli.commands.cleanup.has_uncommitted_changes", return_value=False),
        patch(
            "cli.commands.cleanup.analyze_worktree",
            return_value=SimpleNamespace(
                worktree=summitflow_worktrees[0],
                action=CleanupAction.NEEDS_MERGE,
                task_status="completed",
            ),
        ),
    ):
        result = runner.invoke(app, ["status", "--all"])

    assert result.exit_code == 0
    assert "CLEANUP[all]:repos=2 needs_cleanup=1 worktrees=1 dirty=0 orphan=1 prunable=0" in result.output
    assert "summitflow worktrees:1 dirty:0 orphan:1 prunable:0 tasks:task-1 finalize:task-1" in result.output
    assert "agent-hub clean" in result.output


def test_cleanup_status_routes_missing_task_merge_candidates_to_review() -> None:
    repo_paths = [Path("/repos/agent-hub")]
    worktree = SimpleNamespace(
        task_id="task-missing",
        path=Path("/wt/missing"),
        branch="task-missing/main",
        base_branch="main",
        project_id="agent-hub",
    )

    with (
        patch("cli.commands.cleanup._get_managed_repos", return_value=repo_paths),
        patch("cli.commands.cleanup.get_project_id", return_value="agent-hub"),
        patch(
            "cli.commands.cleanup.build_repo_workspace_summary",
            return_value=SimpleNamespace(
                active_worktrees=1,
                orphan_branches=0,
                prunable_branches=0,
                worktree_task_ids=["task-missing"],
            ),
        ),
        patch(
            "cli.commands.cleanup.get_active_worktrees",
            side_effect=[[worktree], [worktree]],
        ),
        patch("cli.commands.cleanup.has_uncommitted_changes", return_value=False),
        patch(
            "cli.commands.cleanup.analyze_worktree",
            return_value=SimpleNamespace(
                worktree=worktree,
                action=CleanupAction.NEEDS_MERGE,
                task_status=None,
            ),
        ),
    ):
        payload = build_cleanup_status_payload(all_projects=False)

    assert payload["repositories"][0]["needs_merge_tasks"] == []
    assert payload["repositories"][0]["review_tasks"] == ["task-missing"]


def test_cleanup_worktrees_auto_prunes_git_residue() -> None:
    worktree = SimpleNamespace(
        task_id="task-1",
        path=Path("/wt/1"),
        branch="task-1/main",
        base_branch="main",
        project_id="agent-hub",
    )
    analysis = SimpleNamespace(
        worktree=worktree,
        action=CleanupAction.ALREADY_MERGED,
        task_status="completed",
        last_commit_age_days=1,
    )

    with (
        patch("cli.commands.cleanup.get_project_id", return_value="agent-hub"),
        patch("cli.commands.cleanup._iter_target_repos", return_value=[Path("/repos/agent-hub")]),
        patch("cli.commands.cleanup.get_active_worktrees", return_value=[worktree]),
        patch("cli.commands.cleanup._analyze_and_display", return_value=([analysis], SimpleNamespace(needs_merge=[], safe_to_delete=[analysis]))),
        patch("cli.commands.cleanup.execute_cleanup") as mock_execute,
        patch("cli.commands.cleanup.prune_worktree_registrations") as mock_prune_worktrees,
        patch("cli.commands.cleanup.prune_prunable_task_branches", return_value=["task-1/main", "task-2/main"]) as mock_prune_branches,
    ):
        mock_execute.return_value = SimpleNamespace(cleaned=1, skipped=0, errors=0)
        result = runner.invoke(app, ["worktrees", "--auto"])

    assert result.exit_code == 0
    mock_prune_worktrees.assert_called_once_with(Path("/repos/agent-hub"))
    mock_prune_branches.assert_called_once_with(Path("/repos/agent-hub"))
    assert "Pruned git worktree registrations in 1 repo(s)" in result.output
    assert "Pruned merged orphan task branches: 2" in result.output


def test_analyze_worktree_treats_clean_cancelled_conflict_as_safe_delete(tmp_path: Path) -> None:
    worktree_path = tmp_path / "task-cancelled"
    worktree_path.mkdir()
    (worktree_path / ".git").mkdir()
    worktree = SimpleNamespace(
        task_id="task-cancelled",
        path=worktree_path,
        branch="task-cancelled/main",
        base_branch="main",
        project_id="agent-hub",
    )

    with (
        patch("cli.commands.cleanup_analysis.get_task_info", return_value=("cancelled", "Cancelled task")),
        patch("cli.commands.cleanup_analysis.get_commits_ahead_behind", return_value=(2, 0)),
        patch("cli.commands.cleanup_analysis.has_uncommitted_changes", return_value=False),
        patch("cli.commands.cleanup_analysis.has_merge_conflicts", return_value=True),
        patch("cli.commands.cleanup_analysis.get_last_commit_age_days", return_value=3),
        patch("cli.commands.cleanup_analysis.is_already_merged", return_value=False),
    ):
        analysis = analyze_worktree(worktree, client=SimpleNamespace())

    assert analysis.action == CleanupAction.SAFE_DELETE
    assert analysis.task_status == "cancelled"
    assert analysis.has_conflicts is True
    assert "can be discarded" in analysis.reason


def test_analyze_worktree_treats_missing_path_as_safe_delete() -> None:
    worktree = SimpleNamespace(
        task_id="task-missing-path",
        path=Path("/wt/missing-path"),
        branch="task-missing-path/main",
        base_branch="main",
        project_id="agent-hub",
    )

    with patch("cli.commands.cleanup_analysis.get_task_info", return_value=("completed", "Missing path")):
        analysis = analyze_worktree(worktree, client=SimpleNamespace())

    assert analysis.action == CleanupAction.SAFE_DELETE
    assert analysis.commits_ahead == 0
    assert analysis.reason == "Worktree path already removed; prune stale registration"


def test_analyze_worktree_routes_blocked_unmerged_worktree_to_review(tmp_path: Path) -> None:
    worktree_path = tmp_path / "task-blocked"
    worktree_path.mkdir()
    (worktree_path / ".git").mkdir()
    worktree = SimpleNamespace(
        task_id="task-blocked",
        path=worktree_path,
        branch="task-blocked/main",
        base_branch="main",
        project_id="agent-hub",
    )

    with (
        patch("cli.commands.cleanup_analysis.get_task_info", return_value=("blocked", "Blocked task")),
        patch("cli.commands.cleanup_analysis.get_commits_ahead_behind", return_value=(2, 0)),
        patch("cli.commands.cleanup_analysis.has_uncommitted_changes", return_value=False),
        patch("cli.commands.cleanup_analysis.has_merge_conflicts", return_value=False),
        patch("cli.commands.cleanup_analysis.get_last_commit_age_days", return_value=1),
        patch("cli.commands.cleanup_analysis.is_already_merged", return_value=False),
    ):
        analysis = analyze_worktree(worktree, client=SimpleNamespace())

    assert analysis.action == CleanupAction.MANUAL_REVIEW
    assert analysis.task_status == "blocked"
    assert analysis.reason == "Blocked task has unmerged commits and requires review before cleanup"
