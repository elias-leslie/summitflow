"""Tests for `st cleanup status` hygiene summary output."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from typer.testing import CliRunner

from cli.commands.cleanup import app, build_cleanup_status_payload
from cli.commands.cleanup_analysis import CleanupAction, analyze_worktree, cleanup_worktree

runner = CliRunner()


def _make_existing_worktree(tmp_path: Path, task_id: str, project_id: str) -> SimpleNamespace:
    path = tmp_path / task_id
    path.mkdir()
    return SimpleNamespace(
        task_id=task_id,
        path=path,
        branch=f"{task_id}/main",
        base_branch="main",
        project_id=project_id,
    )


def test_build_cleanup_status_payload_aggregates_repo_hygiene(tmp_path: Path) -> None:
    repo_paths = [Path("/repos/summitflow"), Path("/repos/agent-hub")]
    summitflow_worktrees = [
        _make_existing_worktree(tmp_path, "task-1", "summitflow"),
        _make_existing_worktree(tmp_path, "task-2", "summitflow"),
    ]

    with (
        patch("cli.commands.cleanup._get_managed_repos", return_value=repo_paths),
        patch("cli.commands.cleanup.get_project_id", return_value=None),
        patch("cli.commands.cleanup.get_stale_checkpoints", side_effect=[[], []]),
        patch("cli.commands.cleanup.find_snapshot_residue", return_value=[]),
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
        "snapshot_residue": 0,
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


def test_cleanup_status_compact_reports_cross_repo_summary(tmp_path: Path) -> None:
    repo_paths = [Path("/repos/summitflow"), Path("/repos/agent-hub")]
    summitflow_worktrees = [
        _make_existing_worktree(tmp_path, "task-1", "summitflow"),
    ]

    with (
        patch("cli.commands.cleanup._get_managed_repos", return_value=repo_paths),
        patch("cli.commands.cleanup.get_project_id", return_value=None),
        patch("cli.commands.cleanup.get_stale_checkpoints", side_effect=[[], []]),
        patch("cli.commands.cleanup.find_snapshot_residue", return_value=[]),
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
    assert "CLEANUP[all]:repos=2 needs_cleanup=1 worktrees=1 dirty=0 stale_cp=0 snap=0 orphan=1 prunable=0" in result.output
    assert (
        "summitflow worktrees:1 dirty:0 orphan:1 prunable:0 tasks:task-1 "
        "finalize:task-1 salvage:task-3 orphan_branches:task-3/main"
    ) in result.output
    assert "agent-hub clean" in result.output


def test_cleanup_status_routes_missing_task_merge_candidates_to_review(tmp_path: Path) -> None:
    repo_paths = [Path("/repos/agent-hub")]
    worktree = _make_existing_worktree(tmp_path, "task-missing", "agent-hub")

    with (
        patch("cli.commands.cleanup._get_managed_repos", return_value=repo_paths),
        patch("cli.commands.cleanup.get_project_id", return_value="agent-hub"),
        patch("cli.commands.cleanup.get_stale_checkpoints", return_value=[]),
        patch("cli.commands.cleanup.find_snapshot_residue", return_value=[]),
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




def test_cleanup_status_treats_reconciled_or_authoritative_lanes_as_cleanup_only_residue(tmp_path: Path) -> None:
    repo_paths = [Path("/repos/terminal")]
    worktree = _make_existing_worktree(tmp_path, "task-reconciled", "terminal")

    with (
        patch("cli.commands.cleanup._get_managed_repos", return_value=repo_paths),
        patch("cli.commands.cleanup.get_project_id", return_value="terminal"),
        patch("cli.commands.cleanup.get_stale_checkpoints", return_value=[]),
        patch("cli.commands.cleanup.find_snapshot_residue", return_value=[]),
        patch(
            "cli.commands.cleanup.build_repo_workspace_summary",
            return_value=SimpleNamespace(
                active_worktrees=1,
                orphan_branches=0,
                prunable_branches=0,
                worktree_task_ids=["task-reconciled"],
                orphan_branch_names=[],
                prunable_branch_names=[],
                salvage_task_ids=[],
                review_orphan_task_ids=[],
                dirty_main_repo=False,
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
                action=CleanupAction.SAFE_DELETE,
                task_status="reconciled",
            ),
        ),
    ):
        payload = build_cleanup_status_payload(all_projects=False)

    assert payload["repositories"][0]["needs_merge_tasks"] == []
    assert payload["repositories"][0]["review_tasks"] == []
    assert payload["repositories"][0]["needs_cleanup"] is False


def test_cleanup_worktree_uses_task_id_cleanup_api(tmp_path: Path) -> None:
    worktree = _make_existing_worktree(tmp_path, "task-safe", "terminal")
    analysis = SimpleNamespace(
        worktree=worktree,
        action=CleanupAction.SAFE_DELETE,
        reason="Already merged",
    )

    with patch("cli.commands.cleanup_analysis.remove_worktree", return_value=True) as mock_remove:
        result = cleanup_worktree(analysis)

    assert result == (True, "Removed task-safe")
    mock_remove.assert_called_once_with(
        "task-safe",
        delete_branch=True,
        project_id="terminal",
    )

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
                "snapshot_residue": 0,
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
                    "snapshot_residue": 0,
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
    assert "CLEANUP[current]:repos=1 needs_cleanup=1 worktrees=2 dirty=1 stale_cp=0 snap=0 orphan=0 prunable=0" in result.output


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
                "snapshot_residue": 0,
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
                    "snapshot_residue": 0,
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
        patch("cli.commands.cleanup.find_snapshot_residue", return_value=[]),
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
    assert "CLEANUP[current]:repos=1 needs_cleanup=1 worktrees=0 dirty=0 stale_cp=1 snap=0 orphan=0 prunable=0" in result.output
    assert "summitflow worktrees:0 dirty:0 stale_cp:1 orphan:0 prunable:0" in result.output


def test_cleanup_status_counts_snapshot_residue() -> None:
    repo_paths = [Path("/repos/summitflow")]
    with (
        patch("cli.commands.cleanup._get_managed_repos", return_value=repo_paths),
        patch("cli.commands.cleanup.get_project_id", return_value="summitflow"),
        patch("cli.commands.cleanup.get_stale_checkpoints", return_value=[]),
        patch("cli.commands.cleanup.find_snapshot_residue", return_value=[SimpleNamespace(), SimpleNamespace()]),
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
    assert "CLEANUP[current]:repos=1 needs_cleanup=1 worktrees=0 dirty=0 stale_cp=0 snap=2 orphan=0 prunable=0" in result.output
    assert "summitflow worktrees:0 dirty:0 snap:2 orphan:0 prunable:0" in result.output


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
        patch(
            "cli.commands.cleanup.analyze_and_display",
            return_value=([analysis], SimpleNamespace(needs_merge=[], safe_to_delete=[analysis])),
        ),
        patch(
            "cli.commands.cleanup_handlers.execute_cleanup",
            return_value=SimpleNamespace(cleaned=1, skipped=0, errors=0),
        ),
        patch(
            "cli.commands.cleanup_handlers.cleanup_safe_git_residue",
            return_value=(1, 2, 1, 1),
        ) as mock_cleanup_residue,
    ):
        result = runner.invoke(app, ["worktrees", "--auto"])

    assert result.exit_code == 0
    mock_cleanup_residue.assert_called_once_with([Path("/repos/agent-hub")], False)
    assert "Pruned git worktree registrations in 1 repo(s)" in result.output
    assert "Pruned merged orphan task branches: 2" in result.output
    assert "Pruned equivalent orphan task branches: 1" in result.output
    assert "Pruned closed orphan task branches: 1" in result.output


def test_cleanup_worktrees_auto_prunes_git_residue_without_worktrees() -> None:
    with (
        patch("cli.commands.cleanup.get_project_id", return_value="agent-hub"),
        patch("cli.commands.cleanup._iter_target_repos", return_value=[Path("/repos/agent-hub")]),
        patch("cli.commands.cleanup.get_active_worktrees", return_value=[]),
        patch("cli.commands.cleanup.cleanup_safe_git_residue", return_value=(1, 2, 1, 1)) as mock_cleanup_residue,
    ):
        result = runner.invoke(app, ["worktrees", "--auto"])

    assert result.exit_code == 0
    mock_cleanup_residue.assert_called_once_with([Path("/repos/agent-hub")], False)
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
        analysis = analyze_worktree(worktree)

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
        analysis = analyze_worktree(worktree)

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
        analysis = analyze_worktree(worktree)

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
        patch("cli.commands.cleanup_salvage.get_branch_subject", return_value="Refactor storage helper"),
        patch(
            "cli.commands.cleanup_salvage.task_store.create_task",
            return_value={"id": "task-24310aaf"},
        ) as mock_create_task,
        patch("cli.commands.cleanup_salvage.task_store.update_task") as mock_update_task,
        patch(
            "cli.commands.cleanup_salvage.create_worktree",
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
        patch("cli.commands.cleanup_salvage.get_branch_subject", return_value="Refactor storage helper"),
        patch(
            "cli.commands.cleanup_salvage.task_store.create_task",
            return_value={"id": "task-24310aaf"},
        ),
        patch("cli.commands.cleanup_salvage.task_store.update_task"),
        patch(
            "cli.commands.cleanup_salvage.create_worktree",
            side_effect=RuntimeError("worktree add failed"),
        ),
        patch("cli.commands.cleanup_salvage.task_store.delete_task") as mock_delete_task,
    ):
        result = runner.invoke(app, ["salvage", "task-24310aaf", "--all"])

    assert result.exit_code == 1
    mock_delete_task.assert_called_once_with(
        "task-24310aaf",
        deletion_source="cli:cleanup.salvage_rollback",
    )
    assert "failed to create worktree" in result.output


def test_build_cleanup_status_payload_respects_project_override() -> None:
    repo_paths = [Path("/repos/summitflow"), Path("/repos/agent-hub")]

    with (
        patch("cli.commands.cleanup._get_managed_repos", return_value=repo_paths),
        patch("cli.commands.cleanup.get_stale_checkpoints", return_value=[]),
        patch("cli.commands.cleanup.find_snapshot_residue", return_value=[]),
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
        payload = build_cleanup_status_payload(all_projects=False, project_id_override="agent-hub")

    assert payload["summary"]["repos"] == 1
    assert payload["repositories"][0]["project_id"] == "agent-hub"


def test_build_cleanup_status_payload_skips_missing_worktrees(tmp_path) -> None:
    repo_path = Path("/repos/terminal")
    existing_path = tmp_path / "task-live"
    existing_path.mkdir()
    existing_worktree = SimpleNamespace(
        task_id="task-live",
        path=existing_path,
        branch="task-live/main",
        base_branch="main",
        project_id="terminal",
    )
    missing_worktree = SimpleNamespace(
        task_id="task-missing",
        path=tmp_path / "task-missing",
        branch="task-missing/main",
        base_branch="main",
        project_id="terminal",
    )

    with (
        patch("cli.commands.cleanup._get_managed_repos", return_value=[repo_path]),
        patch("cli.commands.cleanup.get_project_id", return_value="terminal"),
        patch("cli.commands.cleanup.get_stale_checkpoints", return_value=[]),
        patch("cli.commands.cleanup.find_snapshot_residue", return_value=[]),
        patch(
            "cli.commands.cleanup.build_repo_workspace_summary",
            return_value=SimpleNamespace(
                active_worktrees=1,
                orphan_branches=0,
                prunable_branches=0,
                worktree_task_ids=["task-live"],
                orphan_branch_names=[],
                prunable_branch_names=[],
                salvage_task_ids=[],
                review_orphan_task_ids=[],
            ),
        ),
        patch(
            "cli.commands.cleanup.get_active_worktrees",
            side_effect=[
                [existing_worktree, missing_worktree],
                [existing_worktree, missing_worktree],
            ],
        ),
        patch("cli.commands.cleanup.has_uncommitted_changes", return_value=False),
        patch(
            "cli.commands.cleanup.analyze_worktree",
            return_value=SimpleNamespace(
                worktree=existing_worktree,
                action=CleanupAction.SAFE_DELETE,
                task_status="pending",
            ),
        ) as mock_analyze,
    ):
        payload = build_cleanup_status_payload(all_projects=False)

    assert payload["total"] == 1
    assert payload["worktrees"] == [
        {
            "task_id": "task-live",
            "path": str(existing_path),
            "branch": "task-live/main",
            "base_branch": "main",
            "project_id": "terminal",
        }
    ]
    assert mock_analyze.call_count == 1
