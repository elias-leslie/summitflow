"""Tests for st claim command task lifecycle behavior."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
import typer

from cli.commands.claim import _claim_task, adopt_command
from cli.commands.claim_helpers import require_claim_safe_tree


class TestClaimTask:
    """Tests for task claiming with checkpoint creation."""

    def test_claim_task_success_claims_before_snapshot(self) -> None:
        """Task claim should acquire the backend claim lock before snapshot creation."""
        client = MagicMock()
        client.get_task.return_value = {"id": "task-1", "project_id": "summitflow"}
        client.claim_task.return_value = {
            "id": "task-1",
            "status": "running",
            "claimed_by": "worker-1",
        }

        with (
            patch("cli.commands.claim.get_snapshot_info", return_value=None),
            patch("cli.commands.claim.require_claim_safe_tree"),
            patch(
                "cli.commands.claim.create_task_snapshot",
                return_value=SimpleNamespace(
                    base_branch="main",
                    worktree_path="/tmp/task-1",
                    backend_port=8127,
                    frontend_port=3127,
                ),
            ) as mock_snapshot,
        ):
            result = _claim_task(client, "task-1")

        client.claim_task.assert_called_once_with("task-1")
        client.update_status.assert_not_called()
        mock_snapshot.assert_called_once_with("task-1", "summitflow")
        assert result["action"] == "claimed"
        assert result["worktree_path"] == "/tmp/task-1"

    def test_claim_task_normalizes_short_id_before_local_checkpoint_ops(self) -> None:
        client = MagicMock()
        client.get_task.return_value = {"id": "task-1", "project_id": "summitflow"}
        client.claim_task.return_value = {
            "id": "task-1",
            "status": "running",
            "claimed_by": "worker-1",
        }

        with (
            patch("cli.commands.claim.get_snapshot_info", return_value=None),
            patch("cli.commands.claim.require_claim_safe_tree"),
            patch(
                "cli.commands.claim.create_task_snapshot",
                return_value=SimpleNamespace(
                    base_branch="main",
                    worktree_path="/tmp/task-1",
                    backend_port=8127,
                    frontend_port=3127,
                ),
            ) as mock_snapshot,
        ):
            _claim_task(client, "1")

        client.get_task.assert_called_once_with("task-1")
        mock_snapshot.assert_called_once_with("task-1", "summitflow")

    def test_claim_task_snapshot_failure_releases_lock(self) -> None:
        """A failed snapshot/worktree creation should release the claimed task lock."""
        client = MagicMock()
        client.get_task.return_value = {"id": "task-1", "project_id": "summitflow"}
        client.claim_task.return_value = {
            "id": "task-1",
            "status": "running",
            "claimed_by": "worker-1",
        }

        with (
            patch("cli.commands.claim.get_snapshot_info", return_value=None),
            patch("cli.commands.claim.require_claim_safe_tree"),
            patch(
                "cli.commands.claim.create_task_snapshot",
                side_effect=RuntimeError("worktree failed"),
            ),
            patch("cli.commands.claim.remove_snapshot") as mock_remove_snapshot,
            patch("cli.commands.claim.output_warning"),
            pytest.raises(typer.Exit) as exc_info,
        ):
            _claim_task(client, "task-1")

        assert exc_info.value.exit_code == 1
        client.release_task.assert_called_once_with("task-1")
        mock_remove_snapshot.assert_called_once_with(
            "task-1",
            remove_worktree=True,
            project_id="summitflow",
        )


class TestAdoptCommand:
    def test_adopt_command_updates_existing_worktree(self) -> None:
        with (
            patch("cli.commands.claim.get_snapshot_info", return_value={"worktree_path": "/tmp/task-1"}),
            patch("cli.commands.claim.adopt_dirty_changes_to_worktree", return_value=2) as mock_adopt,
            patch("cli.commands.claim.output_success") as mock_success,
        ):
            adopt_command("task-1")

        mock_adopt.assert_called_once_with("/tmp/task-1")
        assert "task-1" in mock_success.call_args.args[0]

    def test_adopt_command_requires_existing_checkpoint(self) -> None:
        with pytest.raises(typer.Exit) as exc_info, patch(
            "cli.commands.claim.get_snapshot_info", return_value=None
        ):
            adopt_command("task-1")

        assert exc_info.value.exit_code == 1


class TestClaimTaskErrorsAndAdoption:
    def test_claim_task_release_failure_warns_user(self) -> None:
        """Release failure after snapshot error should be surfaced as a warning."""
        client = MagicMock()
        client.get_task.return_value = {"id": "task-1", "project_id": "summitflow"}
        client.claim_task.return_value = {
            "id": "task-1",
            "status": "running",
            "claimed_by": "worker-1",
        }
        client.release_task.side_effect = RuntimeError("release failed")

        with (
            patch("cli.commands.claim.get_snapshot_info", return_value=None),
            patch("cli.commands.claim.require_claim_safe_tree"),
            patch(
                "cli.commands.claim.create_task_snapshot",
                side_effect=RuntimeError("worktree failed"),
            ),
            patch("cli.commands.claim.remove_snapshot"),
            patch("cli.commands.claim.output_warning") as mock_warning,
            pytest.raises(typer.Exit) as exc_info,
        ):
            _claim_task(client, "task-1")

        assert exc_info.value.exit_code == 1
        mock_warning.assert_called_once()
        assert "release failed" in mock_warning.call_args.args[0]

    def test_claim_task_adopts_dirty_changes_into_worktree(self) -> None:
        client = MagicMock()
        client.get_task.return_value = {"id": "task-1", "project_id": "summitflow"}

        with (
            patch("cli.commands.claim.get_snapshot_info", return_value=None),
            patch("cli.commands.claim.require_claim_safe_tree"),
            patch(
                "cli.commands.claim.create_task_snapshot",
                return_value=SimpleNamespace(
                    base_branch="main",
                    worktree_path="/tmp/task-1",
                    backend_port=8127,
                    frontend_port=3127,
                ),
            ),
            patch("cli.commands.claim.adopt_dirty_changes_to_worktree") as mock_adopt,
        ):
            _claim_task(client, "task-1")

        mock_adopt.assert_called_once_with("/tmp/task-1")

    def test_claim_task_adoption_failure_releases_lock(self) -> None:
        client = MagicMock()
        client.get_task.return_value = {"id": "task-1", "project_id": "summitflow"}
        client.claim_task.return_value = {
            "id": "task-1",
            "status": "running",
            "claimed_by": "worker-1",
        }

        with (
            patch("cli.commands.claim.get_snapshot_info", return_value=None),
            patch("cli.commands.claim.require_claim_safe_tree"),
            patch(
                "cli.commands.claim.create_task_snapshot",
                return_value=SimpleNamespace(
                    base_branch="main",
                    worktree_path="/tmp/task-1",
                    backend_port=8127,
                    frontend_port=3127,
                ),
            ),
            patch(
                "cli.commands.claim.adopt_dirty_changes_to_worktree",
                side_effect=RuntimeError("copy failed"),
            ),
            patch("cli.commands.claim.remove_snapshot") as mock_remove_snapshot,
            pytest.raises(typer.Exit) as exc_info,
        ):
            _claim_task(client, "task-1")

        assert exc_info.value.exit_code == 1
        client.release_task.assert_called_once_with("task-1")
        mock_remove_snapshot.assert_called_once_with(
            "task-1",
            remove_worktree=True,
            project_id="summitflow",
        )


class TestClaimTreeSafety:
    def test_require_claim_safe_tree_allows_dirty_without_hazards(self) -> None:
        with (
            patch("cli.commands.claim_helpers._git_status_lines", return_value=[" M backend/app/main.py"]),
            patch("cli.commands.claim_helpers.output_warning") as mock_warning,
        ):
            require_claim_safe_tree()

        mock_warning.assert_called_once()

    def test_require_claim_safe_tree_blocks_unmerged_conflicts(self) -> None:
        with (
            patch("cli.commands.claim_helpers._git_status_lines", return_value=["UU backend/app/main.py"]),
            patch("cli.commands.claim_helpers.output_error") as mock_error,
            pytest.raises(typer.Exit) as exc_info,
        ):
            require_claim_safe_tree()

        assert exc_info.value.exit_code == 1
        assert "unresolved merge conflicts" in mock_error.call_args.args[0]

    def test_require_claim_safe_tree_blocks_merge_in_progress(self, tmp_path: Path) -> None:
        git_dir = tmp_path / ".git"
        git_dir.mkdir()
        (git_dir / "MERGE_HEAD").write_text("merge", encoding="utf-8")

        with (
            patch("cli.commands.claim_helpers._git_status_lines", return_value=[]),
            patch("cli.commands.claim_helpers.Path", return_value=git_dir),
            patch("cli.commands.claim_helpers.output_error") as mock_error,
            pytest.raises(typer.Exit) as exc_info,
        ):
            require_claim_safe_tree()

        assert exc_info.value.exit_code == 1
        assert "merge in progress" in mock_error.call_args.args[0]

    def test_adopt_dirty_changes_to_worktree_copies_modified_and_untracked_files(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from cli.commands.claim_helpers import adopt_dirty_changes_to_worktree

        repo_root = tmp_path / "repo"
        worktree_root = tmp_path / "worktree"
        repo_root.mkdir()
        worktree_root.mkdir()
        (repo_root / "backend").mkdir()
        (repo_root / "backend" / "app.py").write_text("print('new')\n", encoding="utf-8")
        (repo_root / "new.txt").write_text("hello\n", encoding="utf-8")
        (worktree_root / "backend").mkdir()
        (worktree_root / "backend" / "app.py").write_text("print('old')\n", encoding="utf-8")

        monkeypatch.chdir(repo_root)

        with (
            patch(
                "cli.commands.claim_helpers._git_status_lines",
                return_value=[" M backend/app.py", "?? new.txt"],
            ),
            patch("cli.commands.claim_helpers.get_repo_root", return_value=repo_root),
            patch("cli.commands.claim_helpers.output_success"),
        ):
            adopted = adopt_dirty_changes_to_worktree(str(worktree_root))

        assert adopted == 2
        assert (worktree_root / "backend" / "app.py").read_text(encoding="utf-8") == "print('new')\n"
        assert (worktree_root / "new.txt").read_text(encoding="utf-8") == "hello\n"
