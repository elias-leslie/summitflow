"""Tests for `st cleanup status` hygiene summary output."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from typer.testing import CliRunner

from cli.commands.cleanup import app, build_cleanup_status_payload

runner = CliRunner()


def test_build_cleanup_status_payload_aggregates_repo_hygiene() -> None:
    repo_paths = [Path("/repos/summitflow"), Path("/repos/agent-hub")]

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
                [
                    SimpleNamespace(task_id="task-1", path=Path("/wt/1"), branch="task-1/main", base_branch="main", project_id="summitflow"),
                    SimpleNamespace(task_id="task-2", path=Path("/wt/2"), branch="task-2/main", base_branch="main", project_id="summitflow"),
                ],
                [
                    SimpleNamespace(task_id="task-1", path=Path("/wt/1"), branch="task-1/main", base_branch="main", project_id="summitflow"),
                    SimpleNamespace(task_id="task-2", path=Path("/wt/2"), branch="task-2/main", base_branch="main", project_id="summitflow"),
                ],
                [],
            ],
        ),
        patch(
            "cli.commands.cleanup.has_uncommitted_changes",
            side_effect=[True, False],
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
    assert payload["repositories"][1]["project_id"] == "agent-hub"
    assert payload["repositories"][1]["needs_cleanup"] is False
    assert payload["total"] == 2


def test_cleanup_status_compact_reports_cross_repo_summary() -> None:
    repo_paths = [Path("/repos/summitflow"), Path("/repos/agent-hub")]

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
                [
                    SimpleNamespace(task_id="task-1", path=Path("/wt/1"), branch="task-1/main", base_branch="main", project_id="summitflow"),
                ],
                [
                    SimpleNamespace(task_id="task-1", path=Path("/wt/1"), branch="task-1/main", base_branch="main", project_id="summitflow"),
                ],
                [],
            ],
        ),
        patch("cli.commands.cleanup.has_uncommitted_changes", return_value=False),
    ):
        result = runner.invoke(app, ["status", "--all"])

    assert result.exit_code == 0
    assert "CLEANUP[all]:repos=2 needs_cleanup=1 worktrees=1 dirty=0 orphan=1 prunable=0" in result.output
    assert "summitflow worktrees:1 dirty:0 orphan:1 prunable:0 tasks:task-1" in result.output
    assert "agent-hub clean" in result.output
