from __future__ import annotations

import os
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

from cli.commands.hygiene import app
from cli.output_context import OutputContext

runner = CliRunner()


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
        env={
            **os.environ,
            "GIT_AUTHOR_NAME": "Test",
            "GIT_AUTHOR_EMAIL": "t@example.test",
            "GIT_COMMITTER_NAME": "Test",
            "GIT_COMMITTER_EMAIL": "t@example.test",
        },
    )


def _init_repo(repo: Path) -> None:
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    (repo / "README.md").write_text("hello\n", encoding="utf-8")
    _git(repo, "add", "README.md")
    _git(repo, "commit", "-m", "initial")


def _clean_payload(repo: Path) -> dict[str, object]:
    entry = {
        "project_id": repo.name,
        "path": str(repo),
        "active_checkpoints": 0,
        "dirty_checkpoints": 0,
        "dirty_main_repo": False,
        "stale_checkpoints": 0,
        "snapshot_residue": 0,
        "orphan_task_branches": 0,
        "prunable_task_branches": 0,
        "checkpoint_task_ids": [],
        "orphan_branch_names": [],
        "prunable_branch_names": [],
        "salvage_task_ids": [],
        "review_orphan_task_ids": [],
        "orphan_details": [],
        "needs_merge_count": 0,
        "conflict_count": 0,
        "review_count": 0,
        "needs_merge_tasks": [],
        "conflict_tasks": [],
        "review_tasks": [],
        "needs_cleanup": False,
    }
    return {
        "summary": {
            "repos": 1,
            "repos_needing_cleanup": 0,
            "active_checkpoints": 0,
            "dirty_checkpoints": 0,
            "stale_checkpoints": 0,
            "snapshot_residue": 0,
            "orphan_task_branches": 0,
            "prunable_task_branches": 0,
        },
        "repositories": [entry],
        "checkpoints": [],
        "total": 0,
    }


def test_hygiene_gate_self_heals_safe_residue_before_passing(tmp_path: Path) -> None:
    repo = tmp_path / "summitflow"
    _init_repo(repo)

    with (
        patch("cli.commands.hygiene._iter_target_repos", return_value=[repo]),
        patch("cli.commands.hygiene.build_cleanup_status_payload", return_value=_clean_payload(repo)),
        patch("cli.commands.hygiene.cleanup_safe_git_residue", return_value=(1, 2, 3, 4)) as mock_cleanup,
    ):
        result = runner.invoke(app, ["gate"], obj=OutputContext(compact=True))

    assert result.exit_code == 0
    mock_cleanup.assert_called_once_with([repo], dry_run=False)
    assert "HYGIENE[current]:ok=1 issues=0 fixed=10" in result.output


def test_hygiene_gate_blocks_stashes_and_extra_local_branches(tmp_path: Path) -> None:
    repo = tmp_path / "summitflow"
    _init_repo(repo)
    _git(repo, "branch", "backup/pnpm-store-pre-rewrite")
    (repo / "README.md").write_text("changed\n", encoding="utf-8")
    _git(repo, "stash", "push", "-m", "old work")

    with (
        patch("cli.commands.hygiene._iter_target_repos", return_value=[repo]),
        patch("cli.commands.hygiene.build_cleanup_status_payload", return_value=_clean_payload(repo)),
        patch("cli.commands.hygiene.cleanup_safe_git_residue", return_value=(0, 0, 0, 0)),
    ):
        result = runner.invoke(app, ["gate"], obj=OutputContext(compact=True))

    assert result.exit_code == 2
    assert "extra_local_branches:backup/pnpm-store-pre-rewrite" in result.output
    assert "stash_entries:stash@{0}:On main: old work" in result.output


def test_claim_task_runs_hygiene_gate_before_checkpoint_creation() -> None:
    from cli.commands import claim

    client = MagicMock()
    client.get_task.return_value = {"id": "task-1", "status": "pending", "project_id": "summitflow"}
    with (
        patch.object(claim, "get_snapshot_info", return_value=None),
        patch.object(claim, "require_hygiene_gate") as mock_gate,
        patch.object(claim, "require_claim_safe_tree") as mock_safe,
        patch.object(claim, "create_task_snapshot") as mock_snapshot,
    ):
        mock_snapshot.return_value = MagicMock(base_branch="main")
        result = claim._claim_task(client, "task-1")

    mock_gate.assert_called_once_with(project_id="summitflow")
    mock_safe.assert_called_once()
    assert result["action"] == "claimed"
