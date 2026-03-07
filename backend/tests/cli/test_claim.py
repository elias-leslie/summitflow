"""Tests for st claim command task lifecycle behavior."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
import typer

from cli.commands.claim import _claim_task


class TestClaimTask:
    """Tests for task claiming with checkpoint creation."""

    def test_claim_task_uses_api_claim_before_checkpoint(self) -> None:
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
            patch("cli.commands.claim.require_clean_tree"),
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

    def test_claim_task_releases_lock_when_snapshot_creation_fails(self) -> None:
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
            patch("cli.commands.claim.require_clean_tree"),
            patch(
                "cli.commands.claim.create_task_snapshot",
                side_effect=RuntimeError("worktree failed"),
            ),
            patch("cli.commands.claim.remove_snapshot") as mock_remove_snapshot,
            patch("cli.commands.claim.output_warning") as mock_warning,
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
        mock_warning.assert_not_called()

    def test_claim_task_warns_if_release_after_failure_also_fails(self) -> None:
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
            patch("cli.commands.claim.require_clean_tree"),
            patch(
                "cli.commands.claim.create_task_snapshot",
                side_effect=RuntimeError("worktree failed"),
            ),
            patch("cli.commands.claim.remove_snapshot"),
            patch("cli.commands.claim.output_warning") as mock_warning,
            pytest.raises(typer.Exit),
        ):
            _claim_task(client, "task-1")

        mock_warning.assert_called_once()
        assert "release failed" in mock_warning.call_args.args[0]
