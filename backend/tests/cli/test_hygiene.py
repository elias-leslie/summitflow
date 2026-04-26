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
    assert "Lane preflight required: run st pulse before claim/edit" in result.output


def test_hygiene_triage_shows_stash_files(tmp_path: Path) -> None:
    repo = tmp_path / "summitflow"
    _init_repo(repo)
    (repo / "README.md").write_text("changed\n", encoding="utf-8")
    _git(repo, "stash", "push", "-m", "old work")

    with (
        patch("cli.commands.hygiene._iter_target_repos", return_value=[repo]),
        patch("cli.commands.hygiene.build_cleanup_status_payload", return_value=_clean_payload(repo)),
    ):
        result = runner.invoke(app, ["triage"], obj=OutputContext(compact=True))

    assert result.exit_code == 0
    assert "TRIAGE[current]:items=1 stashes=1 remote_refs=0" in result.output
    assert "summitflow REVIEW stash stash@{0} files=1" in result.output
    assert "action=inspect-apply-or-archive-before-drop" in result.output
    assert "sample=README.md" in result.output


def test_hygiene_triage_shows_remote_ref_state(tmp_path: Path) -> None:
    repo = tmp_path / "summitflow"
    _init_repo(repo)
    _git(repo, "update-ref", "refs/remotes/origin/task-merged/main", "HEAD")
    _git(repo, "checkout", "-b", "task-unique/main")
    (repo / "feature.txt").write_text("feature\n", encoding="utf-8")
    _git(repo, "add", "feature.txt")
    _git(repo, "commit", "-m", "feature")
    unique_sha = _git(repo, "rev-parse", "HEAD").stdout.strip()
    _git(repo, "checkout", "main")
    _git(repo, "update-ref", "refs/remotes/origin/task-unique/main", unique_sha)

    with (
        patch("cli.commands.hygiene._iter_target_repos", return_value=[repo]),
        patch("cli.commands.hygiene.build_cleanup_status_payload", return_value=_clean_payload(repo)),
    ):
        result = runner.invoke(app, ["triage"], obj=OutputContext(compact=True))

    assert result.exit_code == 0
    assert "TRIAGE[current]:items=2 stashes=0 remote_refs=2 merged_remote_refs=1 unique_remote_refs=1" in result.output
    assert "summitflow REVIEW remote_ref origin/task-merged/main merged action=delete-after-owner-check" in result.output
    assert "summitflow REVIEW remote_ref origin/task-unique/main unique:1 action=archive-before-delete" in result.output


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


def test_closeout_hygiene_allows_only_current_task_lane() -> None:
    from cli.commands.hygiene import _closeout_blocking_issues

    report = {
        "issues": [
            {"project_id": "summitflow", "code": "active_checkpoints", "detail": "task-1,task-2"},
            {"project_id": "summitflow", "code": "extra_local_branches", "detail": "task-1/main,work/old"},
            {"project_id": "summitflow", "code": "stash_entries", "detail": "stash@{0}:On main: parked"},
        ]
    }

    assert _closeout_blocking_issues(report, "task-1") == [
        {"project_id": "summitflow", "code": "active_checkpoints", "detail": "task-2"},
        {"project_id": "summitflow", "code": "extra_local_branches", "detail": "work/old"},
        {"project_id": "summitflow", "code": "stash_entries", "detail": "stash@{0}:On main: parked"},
    ]


def test_done_task_runs_closeout_hygiene_before_completion() -> None:
    from cli.commands import done

    events: list[str] = []
    client = MagicMock()
    client.get_task.return_value = {"id": "task-1", "project_id": "summitflow"}

    with (
        patch.object(done, "require_closeout_hygiene_gate", side_effect=lambda **_: events.append("gate")) as mock_gate,
        patch.object(
            done,
            "complete_task",
            side_effect=lambda *_args, **_kwargs: events.append("complete")
            or {"project_id": "summitflow", "merged": False},
        ) as mock_complete,
        patch.object(done, "require_hygiene_gate") as mock_final_gate,
    ):
        done._handle_task_completion(client, "task-1", None, strict=False, admin=False)

    assert events == ["gate", "complete"]
    mock_gate.assert_called_once_with(project_id="summitflow", task_id="task-1")
    mock_complete.assert_called_once()
    mock_final_gate.assert_called_once_with(project_id="summitflow")


def test_safe_git_residue_cleanup_does_not_delete_closed_unique_orphans() -> None:
    from cli.commands import cleanup_handlers

    repo = Path("/tmp/repo")
    with (
        patch.object(cleanup_handlers, "prune_checkout_registrations", return_value=1),
        patch.object(cleanup_handlers, "prune_prunable_task_branches", return_value=["task-merged/main"]),
        patch.object(cleanup_handlers, "prune_equivalent_orphan_task_branches", return_value=["task-equivalent/main"]),
    ):
        assert cleanup_handlers.cleanup_safe_git_residue([repo], dry_run=False) == (1, 1, 1, 0)


def test_autonomous_dispatch_blocks_before_claim_when_hygiene_fails(mocker) -> None:
    from app.tasks.autonomous import pickup_dispatch

    mocker.patch.object(pickup_dispatch, "_execution_hygiene_ok", return_value=False)
    claim = mocker.patch.object(pickup_dispatch, "claim_task")

    assert not pickup_dispatch.dispatch_to_execution("task-1", "summitflow", dispatch=None)
    claim.assert_not_called()
