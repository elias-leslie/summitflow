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
        patch("cli.commands.cleanup.get_stale_checkpoints", side_effect=[[], []]),
        patch(
            "cli.commands.cleanup.build_repo_workspace_summary",
            side_effect=[
                SimpleNamespace(
                    active_worktrees=2,
                    orphan_branches=1,
                    prunable_branches=1,
                    worktree_task_ids=["task-1", "task-2"],
                    orphan_branch_names=["task-3/main"],
                    prunable_branch_names=["task-4/main"],
                    salvage_task_ids=["task-3"],
                    review_orphan_task_ids=[],
                ),
                SimpleNamespace(
                    active_worktrees=0,
                    orphan_branches=0,
                    prunable_branches=0,
                    worktree_task_ids=[],
                    orphan_branch_names=[],
                    prunable_branch_names=[],
                    salvage_task_ids=[],
                    review_orphan_task_ids=[],
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
        "stale_checkpoints": 0,
        "orphan_task_branches": 1,
        "prunable_task_branches": 1,
    }
    assert payload["repositories"][0]["project_id"] == "summitflow"
    assert payload["repositories"][0]["needs_cleanup"]
    assert payload["repositories"][0]["needs_merge_tasks"] == ["task-1"]
    assert payload["repositories"][0]["review_tasks"] == ["task-2"]
    assert payload["repositories"][0]["orphan_branch_names"] == ["task-3/main"]
    assert payload["repositories"][0]["prunable_branch_names"] == ["task-4/main"]
    assert payload["repositories"][0]["salvage_task_ids"] == ["task-3"]
    assert payload["repositories"][1]["project_id"] == "agent-hub"
    assert not payload["repositories"][1]["needs_cleanup"]
    assert payload["total"] == 2


def test_cleanup_status_compact_reports_cross_repo_summary() -> None:
    repo_paths = [Path("/repos/summitflow"), Path("/repos/agent-hub")]
    summitflow_worktrees = [
        SimpleNamespace(task_id="task-1", path=Path("/wt/1"), branch="task-1/main", base_branch="main", project_id="summitflow"),
    ]

    with (
        patch("cli.commands.cleanup._get_managed_repos", return_value=repo_paths),
        patch("cli.commands.cleanup.get_project_id", return_value=None),
        patch("cli.commands.cleanup.get_stale_checkpoints", side_effect=[[], []]),
        patch(
            "cli.commands.cleanup.build_repo_workspace_summary",
            side_effect=[
                SimpleNamespace(
                    active_worktrees=1,
                    orphan_branches=1,
                    prunable_branches=0,
                    worktree_task_ids=["task-1"],
                    orphan_branch_names=["task-3/main"],
                    prunable_branch_names=[],
                    salvage_task_ids=["task-3"],
                    review_orphan_task_ids=[],
                ),
                SimpleNamespace(
                    active_worktrees=0,
                    orphan_branches=0,
                    prunable_branches=0,
                    worktree_task_ids=[],
                    orphan_branch_names=[],
                    prunable_branch_names=[],
                    salvage_task_ids=[],
                    review_orphan_task_ids=[],
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
    assert "CLEANUP[all]:repos=2 needs_cleanup=1 worktrees=1 dirty=0 stale_cp=0 orphan=1 prunable=0" in result.output
    assert (
        "summitflow worktrees:1 dirty:0 orphan:1 prunable:0 tasks:task-1 "
        "finalize:task-1 salvage:task-3 orphan_branches:task-3/main"
    ) in result.output
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
        patch("cli.commands.cleanup.get_stale_checkpoints", return_value=[]),
        patch(
            "cli.commands.cleanup.build_repo_workspace_summary",
            return_value=SimpleNamespace(
                active_worktrees=1,
                orphan_branches=0,
                prunable_branches=0,
                worktree_task_ids=["task-missing"],
                orphan_branch_names=[],
                prunable_branch_names=[],
                salvage_task_ids=[],
                review_orphan_task_ids=[],
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


def test_cleanup_status_fail_on_residue_returns_nonzero() -> None:
    with patch(
        "cli.commands.cleanup.build_cleanup_status_payload",
        return_value={
            "summary": {
                "repos": 1,
                "repos_needing_cleanup": 1,
                "active_worktrees": 2,
                "dirty_worktrees": 1,
                "stale_checkpoints": 0,
                "orphan_task_branches": 0,
                "prunable_task_branches": 0,
            },
            "repositories": [
                {
                    "project_id": "summitflow",
                    "needs_cleanup": True,
                    "active_worktrees": 2,
                    "dirty_worktrees": 1,
                    "stale_checkpoints": 0,
                    "orphan_task_branches": 0,
                    "prunable_task_branches": 0,
                    "worktree_task_ids": ["task-1", "task-2"],
                    "needs_merge_tasks": ["task-1"],
                    "conflict_tasks": [],
                    "review_tasks": [],
                    "salvage_task_ids": [],
                    "review_orphan_task_ids": [],
                    "orphan_branch_names": [],
                    "prunable_branch_names": [],
                }
            ],
            "worktrees": [],
            "total": 2,
        },
    ):
        result = runner.invoke(app, ["status", "--fail-on-residue"])

    assert result.exit_code == 2
    assert "CLEANUP[current]:repos=1 needs_cleanup=1 worktrees=2 dirty=1 stale_cp=0 orphan=0 prunable=0" in result.output


def test_cleanup_status_fail_on_residue_succeeds_when_clean() -> None:
    with patch(
        "cli.commands.cleanup.build_cleanup_status_payload",
        return_value={
            "summary": {
                "repos": 1,
                "repos_needing_cleanup": 0,
                "active_worktrees": 0,
                "dirty_worktrees": 0,
                "stale_checkpoints": 0,
                "orphan_task_branches": 0,
                "prunable_task_branches": 0,
            },
            "repositories": [
                {
                    "project_id": "summitflow",
                    "needs_cleanup": False,
                    "active_worktrees": 0,
                    "dirty_worktrees": 0,
                    "stale_checkpoints": 0,
                    "orphan_task_branches": 0,
                    "prunable_task_branches": 0,
                    "worktree_task_ids": [],
                    "needs_merge_tasks": [],
                    "conflict_tasks": [],
                    "review_tasks": [],
                    "salvage_task_ids": [],
                    "review_orphan_task_ids": [],
                    "orphan_branch_names": [],
                    "prunable_branch_names": [],
                }
            ],
            "worktrees": [],
            "total": 0,
        },
    ):
        result = runner.invoke(app, ["status", "--fail-on-residue"])

    assert result.exit_code == 0
    assert "summitflow clean" in result.output


def test_cleanup_status_counts_stale_checkpoints_as_residue() -> None:
    repo_paths = [Path("/repos/summitflow")]
    with (
        patch("cli.commands.cleanup._get_managed_repos", return_value=repo_paths),
        patch("cli.commands.cleanup.get_project_id", return_value="summitflow"),
        patch("cli.commands.cleanup.get_stale_checkpoints", return_value=[SimpleNamespace(task_id="task-stale")]),
        patch(
            "cli.commands.cleanup.build_repo_workspace_summary",
            return_value=SimpleNamespace(
                active_worktrees=0,
                orphan_branches=0,
                prunable_branches=0,
                worktree_task_ids=[],
                orphan_branch_names=[],
                prunable_branch_names=[],
                salvage_task_ids=[],
                review_orphan_task_ids=[],
            ),
        ),
        patch("cli.commands.cleanup.get_active_worktrees", side_effect=[[], []]),
    ):
        result = runner.invoke(app, ["status"])

    assert result.exit_code == 0
    assert "CLEANUP[current]:repos=1 needs_cleanup=1 worktrees=0 dirty=0 stale_cp=1 orphan=0 prunable=0" in result.output
    assert "summitflow worktrees:0 dirty:0 stale_cp:1 orphan:0 prunable:0" in result.output


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
        patch("cli.commands.cleanup.prune_equivalent_orphan_task_branches", return_value=["task-3/main"]) as mock_prune_equivalent,
        patch("cli.commands.cleanup.prune_closed_orphan_task_branches", return_value=["task-3/main"]) as mock_prune_closed,
    ):
        mock_execute.return_value = SimpleNamespace(cleaned=1, skipped=0, errors=0)
        result = runner.invoke(app, ["worktrees", "--auto"])

    assert result.exit_code == 0
    mock_prune_worktrees.assert_called_once_with(Path("/repos/agent-hub"))
    mock_prune_branches.assert_called_once_with(Path("/repos/agent-hub"))
    mock_prune_equivalent.assert_called_once_with(Path("/repos/agent-hub"))
    mock_prune_closed.assert_called_once_with(Path("/repos/agent-hub"))
    assert "Pruned git worktree registrations in 1 repo(s)" in result.output
    assert "Pruned merged orphan task branches: 2" in result.output
    assert "Pruned equivalent orphan task branches: 1" in result.output
    assert "Pruned closed orphan task branches: 1" in result.output


def test_cleanup_worktrees_auto_prunes_git_residue_without_worktrees() -> None:
    with (
        patch("cli.commands.cleanup.get_project_id", return_value="agent-hub"),
        patch("cli.commands.cleanup._iter_target_repos", return_value=[Path("/repos/agent-hub")]),
        patch("cli.commands.cleanup.get_active_worktrees", return_value=[]),
        patch("cli.commands.cleanup.prune_worktree_registrations") as mock_prune_regs,
        patch("cli.commands.cleanup.prune_prunable_task_branches", return_value=["task-1/main", "task-2/main"]),
        patch("cli.commands.cleanup.prune_equivalent_orphan_task_branches", return_value=["task-3/main"]),
        patch("cli.commands.cleanup.prune_closed_orphan_task_branches", return_value=["task-3/main"]),
    ):
        result = runner.invoke(app, ["worktrees", "--auto"])

    assert result.exit_code == 0
    mock_prune_regs.assert_called_once_with(Path("/repos/agent-hub"))
    assert "No worktrees found" in result.output
    assert "Pruned git worktree registrations in 1 repo(s)" in result.output
    assert "Pruned merged orphan task branches: 2" in result.output
    assert "Pruned equivalent orphan task branches: 1" in result.output
    assert "Pruned closed orphan task branches: 1" in result.output


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
    assert analysis.has_conflicts
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

    assert analysis.action == CleanupAction.NEEDS_MERGE
    assert analysis.task_status == "blocked"


def test_inspect_orphans_reports_salvage_candidates() -> None:
    with (
        patch("cli.commands.cleanup._iter_target_repos", return_value=[Path("/repos/summitflow")]),
        patch(
            "cli.commands.cleanup.assess_orphan_task_branches",
            return_value=[
                SimpleNamespace(
                    branch_name="task-24310aaf/main",
                    task_id="task-24310aaf",
                    resolution="salvage",
                    task_status=None,
                    commits_ahead=1,
                    files_changed=1,
                    has_node_modules_artifact=False,
                ),
            ],
        ),
    ):
        result = runner.invoke(app, ["inspect-orphans", "--all"])

    assert result.exit_code == 0
    assert "ORPHAN-REVIEW[all]:total=1 salvage=1 review=0" in result.output
    assert "summitflow task-24310aaf" in result.output
    assert "resolution:salvage" in result.output


def test_cleanup_salvage_recovers_missing_task_orphan_branch() -> None:
    with (
        patch("cli.commands.cleanup._iter_target_repos", return_value=[Path("/repos/summitflow")]),
        patch(
            "cli.commands.cleanup.assess_orphan_task_branches",
            return_value=[
                SimpleNamespace(
                    branch_name="task-24310aaf/main",
                    task_id="task-24310aaf",
                    resolution="salvage",
                    task_status=None,
                    commits_ahead=1,
                    files_changed=1,
                    has_node_modules_artifact=True,
                ),
            ],
        ),
        patch("cli.commands.cleanup._get_branch_subject", return_value="Refactor storage helper"),
        patch(
            "cli.commands.cleanup.task_store.create_task",
            return_value={"id": "task-24310aaf"},
        ) as mock_create_task,
        patch("cli.commands.cleanup.task_store.update_task") as mock_update_task,
        patch(
            "cli.commands.cleanup.create_worktree",
            return_value=SimpleNamespace(path=Path("/wt/task-24310aaf")),
        ) as mock_create_worktree,
    ):
        result = runner.invoke(app, ["salvage", "task-24310aaf", "--all"])

    assert result.exit_code == 0
    mock_create_task.assert_called_once_with(
        project_id="summitflow",
        title="Refactor storage helper",
        description=(
            "Recovered from orphan branch task-24310aaf/main in summitflow. "
            "Latest commit: Refactor storage helper. Resume review, salvage, or discard from the restored lane."
        ),
        task_id="task-24310aaf",
        labels=["cleanup:salvaged"],
    )
    mock_update_task.assert_called_once_with("task-24310aaf", branch_name="task-24310aaf/main")
    mock_create_worktree.assert_called_once_with("task-24310aaf", project_id="summitflow")
    assert "Recovered orphan branch task-24310aaf/main into task task-24310aaf" in result.output
    assert "note: branch includes node_modules artifact changes" in result.output


def test_cleanup_salvage_rejects_non_missing_task_candidates() -> None:
    with (
        patch("cli.commands.cleanup._iter_target_repos", return_value=[Path("/repos/summitflow")]),
        patch(
            "cli.commands.cleanup.assess_orphan_task_branches",
            return_value=[
                SimpleNamespace(
                    branch_name="task-24310aaf/main",
                    task_id="task-24310aaf",
                    resolution="review",
                    task_status="blocked",
                    commits_ahead=1,
                    files_changed=1,
                    has_node_modules_artifact=False,
                ),
            ],
        ),
    ):
        result = runner.invoke(app, ["salvage", "task-24310aaf", "--all"])

    assert result.exit_code == 1
    assert "not a missing-task salvage candidate" in result.output


def test_cleanup_salvage_rolls_back_task_if_worktree_creation_fails() -> None:
    with (
        patch("cli.commands.cleanup._iter_target_repos", return_value=[Path("/repos/summitflow")]),
        patch(
            "cli.commands.cleanup.assess_orphan_task_branches",
            return_value=[
                SimpleNamespace(
                    branch_name="task-24310aaf/main",
                    task_id="task-24310aaf",
                    resolution="salvage",
                    task_status=None,
                    commits_ahead=1,
                    files_changed=1,
                    has_node_modules_artifact=False,
                ),
            ],
        ),
        patch("cli.commands.cleanup._get_branch_subject", return_value="Refactor storage helper"),
        patch(
            "cli.commands.cleanup.task_store.create_task",
            return_value={"id": "task-24310aaf"},
        ),
        patch("cli.commands.cleanup.task_store.update_task"),
        patch(
            "cli.commands.cleanup.create_worktree",
            side_effect=RuntimeError("worktree add failed"),
        ),
        patch("cli.commands.cleanup.task_store.delete_task") as mock_delete_task,
    ):
        result = runner.invoke(app, ["salvage", "task-24310aaf", "--all"])

    assert result.exit_code == 1
    mock_delete_task.assert_called_once_with("task-24310aaf")
    assert "failed to create worktree" in result.output
