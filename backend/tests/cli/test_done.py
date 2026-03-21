"""Tests for st done command smart closure and stash behavior.

Tests the smart auto-verify/auto-close default, strict mode,
stash-merge-pop, and helper functions.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
import typer

from cli.client import STClient
from cli.commands.done_git import git_stash_pop, git_stash_push
from cli.commands.done_subtask import auto_close_subtasks
from cli.commands.done_task import (
    _auto_verify_readiness,
    _publish_completed_work,
    complete_task,
)
from cli.commands.done_validators import is_subtask_id


class TestIsSubtaskId:
    def test_valid_subtask_ids(self) -> None:
        assert is_subtask_id("1.1")
        assert is_subtask_id("2.3")
        assert is_subtask_id("10.20")

    def test_invalid_subtask_ids(self) -> None:
        assert not is_subtask_id("task-abc")
        assert not is_subtask_id("1.2.3")
        assert not is_subtask_id("abc")
        assert not is_subtask_id("a.b")


class TestAutoCloseSubtasks:
    """Tests for auto_close_subtasks smart closure logic."""

    def _make_client(self) -> MagicMock:
        client = MagicMock()
        client._global_url = MagicMock(side_effect=lambda p: f"http://test{p}")
        return client

    def test_skips_already_passed_subtasks(self) -> None:
        """Already-passed subtasks are skipped entirely."""
        client = self._make_client()
        client.get_subtasks.return_value = {
            "subtasks": [
                {"subtask_id": "1.1", "passes": True, "steps": []},
            ]
        }

        auto_close_subtasks(client, "task-123", None)

        # Should NOT call update_step, update_subtask, or merge for passed subtasks
        client.update_step.assert_not_called()
        client.update_subtask.assert_not_called()

    def test_verifies_unpassed_steps(self) -> None:
        """Unpassed subtask is closed directly (steps layer removed)."""
        client = self._make_client()
        client.get_subtasks.return_value = {
            "subtasks": [
                {
                    "subtask_id": "1.1",
                    "passes": False,
                    "steps": [
                        {"step_number": 1, "passes": False, "status": "pending"},
                        {"step_number": 2, "passes": True, "status": "pending"},
                    ],
                },
            ]
        }
        client.update_subtask.return_value = {"passes": True}

        with patch("cli.commands.done_subtask.merge_subtask_branch"):
            auto_close_subtasks(client, "task-123", None)

        # Steps layer removed — update_step is no longer called
        client.update_step.assert_not_called()
        client.update_subtask.assert_called_once_with("task-123", "1.1", passes=True)

    def test_aborts_on_step_failure(self) -> None:
        """If subtask update fails, abort immediately (steps layer removed)."""
        client = self._make_client()
        client.get_subtasks.return_value = {
            "subtasks": [
                {
                    "subtask_id": "1.1",
                    "passes": False,
                    "steps": [
                        {"step_number": 1, "passes": False, "status": "pending"},
                    ],
                },
            ]
        }
        from cli._client_base import APIError
        client.update_subtask.side_effect = APIError(400, "Cannot close subtask")

        with pytest.raises(typer.Exit):
            auto_close_subtasks(client, "task-123", None)

        # update_step should not be called (steps layer removed)
        client.update_step.assert_not_called()

    def test_acknowledges_citations(self) -> None:
        """Citations are acknowledged before subtask close."""
        client = self._make_client()
        client.get_subtasks.return_value = {
            "subtasks": [
                {
                    "subtask_id": "1.1",
                    "passes": False,
                    "citations_status": None,
                    "steps": [
                        {"step_number": 1, "passes": True, "status": "pending"},
                    ],
                },
            ]
        }
        client.update_subtask.return_value = {"passes": True}

        with patch("cli.commands.done_subtask.merge_subtask_branch"):
            auto_close_subtasks(client, "task-123", None)

        client.acknowledge_no_citations.assert_called_once_with("task-123", "1.1")

    def test_skips_acknowledged_citations(self) -> None:
        """Already-acknowledged citations are not re-acknowledged."""
        client = self._make_client()
        client.get_subtasks.return_value = {
            "subtasks": [
                {
                    "subtask_id": "1.1",
                    "passes": False,
                    "citations_status": "acknowledged",
                    "steps": [
                        {"step_number": 1, "passes": True, "status": "pending"},
                    ],
                },
            ]
        }
        client.update_subtask.return_value = {"passes": True}

        with patch("cli.commands.done_subtask.merge_subtask_branch"):
            auto_close_subtasks(client, "task-123", None)

        client.acknowledge_no_citations.assert_not_called()

    def test_merges_subtask_branch(self) -> None:
        """After closing subtask, its branch is merged."""
        client = self._make_client()
        client.get_subtasks.return_value = {
            "subtasks": [
                {
                    "subtask_id": "1.1",
                    "passes": False,
                    "steps": [
                        {"step_number": 1, "passes": True, "status": "pending"},
                    ],
                },
            ]
        }
        client.update_subtask.return_value = {"passes": True}

        with patch("cli.commands.done_subtask.merge_subtask_branch") as mock_merge:
            auto_close_subtasks(client, "task-123", "test-project")

        mock_merge.assert_called_once_with("task-123", "1.1", project_id="test-project")


class TestCompleteTaskSmart:
    """Tests for complete_task smart default behavior."""

    def _setup_mocks(self) -> MagicMock:
        """Set up common mocks for complete_task tests."""
        client = MagicMock()
        client.get_task_completion_readiness.return_value = {"ready": True, "gates": []}
        client.post.return_value = {"verdict": "APPROVED"}
        client.update_status.return_value = {"status": "completed"}
        client.close_task.return_value = {"status": "completed"}
        return client

    @patch("cli.commands.done_task.output_error")
    def test_readiness_uses_task_completion_client_helper(self, mock_error: MagicMock) -> None:
        """Completion readiness should use the task client helper instead of global URL."""
        client = self._setup_mocks()

        complete_task(client, "task-123", strict=False, admin=True, message="skip")
        client.get_task_completion_readiness.assert_not_called()

        mock_snapshot = {"worktree_path": None, "project_id": "test"}
        with patch("cli.commands.done_task.get_snapshot_info", return_value=mock_snapshot), \
             patch("cli.commands.done_task.remove_snapshot"), \
             patch("cli.commands.done_task.merge_task_branch"), \
             patch("cli.commands.done_task.auto_close_subtasks"), \
             patch("cli.commands.done_task.is_working_tree_clean", return_value=True):
            complete_task(client, "task-123")

        client.get_task_completion_readiness.assert_called_once_with("task-123")
        mock_error.assert_not_called()

    @patch("cli.commands.done_task.get_snapshot_info")
    @patch("cli.commands.done_task.capture_lifecycle_baseline")
    @patch("cli.commands.done_task.remove_snapshot")
    @patch("cli.commands.done_task.merge_task_branch")
    @patch("cli.commands.done_task.auto_close_subtasks")
    @patch("cli.commands.done_task.sync_completed_subtasks")
    @patch("cli.commands.done_task.is_working_tree_clean", return_value=True)
    @patch("cli.commands.done_task._publish_completed_work")
    def test_calls_auto_close_by_default(
        self, mock_publish: MagicMock, mock_clean: MagicMock, mock_sync: MagicMock, mock_auto: MagicMock, mock_merge: MagicMock,
        mock_remove: MagicMock, mock_capture: MagicMock, mock_snapshot: MagicMock
    ) -> None:
        """Smart mode calls auto_close_subtasks by default."""
        mock_snapshot.return_value = {"worktree_path": "/tmp/task-123", "project_id": "test"}
        client = self._setup_mocks()
        client.get_subtasks.return_value = {"subtasks": []}
        mock_sync.return_value = MagicMock(synced=[], syncable=[], skipped=[])

        complete_task(client, "task-123")

        mock_sync.assert_called_once()
        mock_auto.assert_called_once_with(client, "task-123", "test")
        mock_capture.assert_called_once_with(project_id="test", cwd="/tmp/task-123")
        mock_publish.assert_called_once_with("task-123", "test")
        client.post.assert_not_called()

    @patch("cli.commands.done_task.get_snapshot_info")
    @patch("cli.commands.done_task.remove_snapshot")
    @patch("cli.commands.done_task.merge_task_branch")
    @patch("cli.commands.done_task.auto_close_subtasks")
    @patch("cli.commands.done_task.sync_completed_subtasks")
    @patch("cli.commands.done_task.is_working_tree_clean", return_value=True)
    @patch("cli.commands.done_task._publish_completed_work")
    def test_completion_pre_syncs_objectively_done_subtasks(
        self,
        mock_publish: MagicMock,
        mock_clean: MagicMock,
        mock_sync: MagicMock,
        mock_auto: MagicMock,
        mock_merge: MagicMock,
        mock_remove: MagicMock,
        mock_snapshot: MagicMock,
    ) -> None:
        mock_snapshot.return_value = {"worktree_path": None, "project_id": "test"}
        client = self._setup_mocks()
        client.get_subtasks.return_value = {"subtasks": [{"subtask_id": "1.1"}]}
        mock_sync.return_value = MagicMock(synced=["1.1"], syncable=[], skipped=[])

        with patch("cli.commands.done_task.output_success") as mock_success:
            complete_task(client, "task-123")

        assert any("Pre-synced subtasks before completion: 1.1" in call.args[0] for call in mock_success.call_args_list)

    @patch("cli.commands.done_task.get_snapshot_info", return_value=None)
    @patch("cli.commands.done_task._publish_completed_work")
    def test_admin_mode_closes_task_without_snapshot(
        self,
        mock_publish: MagicMock,
        mock_snapshot: MagicMock,
    ) -> None:
        """Admin mode should allow closing non-code tasks without a checkpoint."""
        client = self._setup_mocks()

        complete_task(client, "task-123", strict=False, admin=True, message="phase shipped")

        client.close_task.assert_called_once_with("task-123", reason="phase shipped", skip_gates=True)
        client.update_status.assert_not_called()
        mock_publish.assert_not_called()

    @patch("cli.commands.done_task.get_snapshot_info", return_value=None)
    @patch("cli.commands.done_task._reconstruct_snapshot_info", return_value=None)
    def test_missing_snapshot_without_admin_still_fails(
        self, mock_reconstruct: MagicMock, mock_snapshot: MagicMock
    ) -> None:
        """Normal mode should still require a checkpoint."""
        client = self._setup_mocks()

        with pytest.raises(typer.Exit):
            complete_task(client, "task-123")

    @patch("cli.commands.done_task.remove_snapshot")
    @patch("cli.commands.done_task.merge_task_branch")
    @patch("cli.commands.done_task.auto_close_subtasks")
    @patch("cli.commands.done_task.sync_completed_subtasks")
    @patch("cli.commands.done_task.is_working_tree_clean", return_value=True)
    @patch("cli.commands.done_task._publish_completed_work")
    @patch("cli.commands.done_task._reconstruct_snapshot_info")
    @patch("cli.commands.done_task.get_snapshot_info", return_value=None)
    def test_missing_metadata_reconstructs_from_worktree(
        self,
        mock_snapshot: MagicMock,
        mock_reconstruct: MagicMock,
        mock_publish: MagicMock,
        mock_clean: MagicMock,
        mock_sync: MagicMock,
        mock_auto: MagicMock,
        mock_merge: MagicMock,
        mock_remove: MagicMock,
    ) -> None:
        """When metadata is missing but task is claimed with a worktree, reconstruct and proceed."""
        mock_reconstruct.return_value = {
            "task_id": "task-123",
            "project_id": "test",
            "base_branch": "main",
            "worktree_path": "/tmp/wt/task-123",
        }
        client = self._setup_mocks()
        client.get_subtasks.return_value = {"subtasks": []}
        mock_sync.return_value = MagicMock(synced=[], syncable=[], skipped=[])

        result = complete_task(client, "task-123")

        mock_reconstruct.assert_called_once_with(client, "task-123")
        assert result["merged"]
        mock_merge.assert_called_once()
        mock_publish.assert_called_once_with("task-123", "test")

    @patch("cli.commands.done_task.get_snapshot_info", return_value=None)
    @patch("cli.commands.done_task.output_error")
    def test_missing_snapshot_allows_already_completed_task(
        self,
        mock_error: MagicMock,
        mock_snapshot: MagicMock,
    ) -> None:
        """Already-completed tasks should be idempotent without a checkpoint."""
        client = self._setup_mocks()
        client.get_task.return_value = {"id": "task-123", "status": "completed"}

        result = complete_task(client, "task-123")

        assert not result["merged"]
        assert not result["snapshot_removed"]
        client.get_task.assert_called_once_with("task-123")
        client.close_task.assert_not_called()
        client.update_status.assert_not_called()
        mock_error.assert_not_called()

    @patch("cli.commands.done_task.get_snapshot_info")
    @patch("cli.commands.done_task.capture_lifecycle_baseline")
    @patch("cli.commands.done_task.remove_snapshot")
    @patch("cli.commands.done_task.merge_task_branch")
    @patch("cli.commands.done_task.auto_close_subtasks")
    @patch("cli.commands.done_task.is_working_tree_clean", return_value=True)
    @patch("cli.commands.done_task._publish_completed_work")
    def test_admin_mode_closes_claimed_task_without_merge(
        self,
        mock_publish: MagicMock,
        mock_clean: MagicMock,
        mock_auto: MagicMock,
        mock_merge: MagicMock,
        mock_remove: MagicMock,
        mock_capture: MagicMock,
        mock_snapshot: MagicMock,
    ) -> None:
        """Admin mode should close stale claimed tasks without merge/review gates."""
        mock_snapshot.return_value = {
            "worktree_path": "/tmp/task-123",
            "project_id": "test",
            "base_branch": "main",
        }
        client = self._setup_mocks()

        result = complete_task(client, "task-123", strict=False, admin=True, message="stale state")

        assert not result["merged"]
        assert result["snapshot_removed"]
        client.close_task.assert_called_once_with("task-123", reason="stale state", skip_gates=True)
        mock_capture.assert_called_once_with(project_id="test", cwd="/tmp/task-123")
        mock_remove.assert_called_once_with("task-123", project_id="test")
        mock_merge.assert_not_called()
        mock_publish.assert_not_called()
        client.post.assert_not_called()

    @patch("cli.commands.done_task.output_error")
    def test_readiness_surfaces_gate_names(self, mock_error: MagicMock) -> None:
        client = self._setup_mocks()
        client.get_task_completion_readiness.return_value = {
            "ready": False,
            "gates": [{"gate": "subtasks"}, {"gate": "steps"}],
        }

        with pytest.raises(typer.Exit):
            _auto_verify_readiness(client, "task-123")

        mock_error.assert_called_once_with("Task not ready to complete: subtasks, steps")

    @patch("cli.commands.done_task.get_snapshot_info")
    @patch("cli.commands.done_task.remove_snapshot")
    @patch("cli.commands.done_task.merge_task_branch")
    @patch("cli.commands.done_task.auto_close_subtasks")
    @patch("cli.commands.done_task.is_working_tree_clean", return_value=True)
    @patch("cli.commands.done_task._publish_completed_work")
    def test_strict_skips_auto_close(
        self, mock_publish: MagicMock, mock_clean: MagicMock, mock_auto: MagicMock, mock_merge: MagicMock,
        mock_remove: MagicMock, mock_snapshot: MagicMock
    ) -> None:
        """Strict mode does NOT call auto_close_subtasks."""
        mock_snapshot.return_value = {"worktree_path": None, "project_id": "test"}
        client = self._setup_mocks()

        complete_task(client, "task-123", strict=True)

        mock_auto.assert_not_called()
        mock_publish.assert_called_once_with("task-123", "test")
        client.post.assert_not_called()

    @patch("cli.commands.done_task.get_snapshot_info")
    @patch("cli.commands.done_task.remove_snapshot")
    @patch("cli.commands.done_task.merge_task_branch")
    @patch("cli.commands.done_task.auto_close_subtasks")
    @patch("cli.commands.done_task.git_stash_pop")
    @patch("cli.commands.done_task.git_stash_push", return_value=True)
    @patch("cli.commands.done_task.is_working_tree_clean")
    @patch("cli.commands.done_task._publish_completed_work")
    def test_stash_merge_pop_on_dirty_main(
        self, mock_publish: MagicMock, mock_clean: MagicMock, mock_stash_push: MagicMock,
        mock_stash_pop: MagicMock, mock_auto: MagicMock, mock_merge: MagicMock,
        mock_remove: MagicMock, mock_snapshot: MagicMock
    ) -> None:
        """Dirty main gets stashed before merge, popped after."""
        # worktree_path=None means worktree clean check is skipped,
        # only main dirty check runs (returns False = dirty)
        mock_snapshot.return_value = {"worktree_path": None, "project_id": "test"}
        mock_clean.return_value = False
        client = self._setup_mocks()

        complete_task(client, "task-123")

        mock_stash_push.assert_called_once()
        mock_stash_pop.assert_called_once()
        mock_publish.assert_called_once_with("task-123", "test")

    @patch("cli.commands.done_task.get_snapshot_info")
    @patch("cli.commands.done_task.is_working_tree_clean")
    def test_strict_errors_on_dirty_main(
        self, mock_snap: MagicMock, mock_clean: MagicMock
    ) -> None:
        """Strict mode errors instead of stashing on dirty main."""
        mock_snap.return_value = {"worktree_path": None, "project_id": "test"}
        # First call: worktree check (skipped, no path), Second call: main dirty (False)
        mock_clean.return_value = False
        client = self._setup_mocks()

        with pytest.raises(typer.Exit):
            complete_task(client, "task-123", strict=True)

    @patch("cli.commands.done_task.get_snapshot_info")
    @patch("cli.commands.done_task.remove_snapshot")
    @patch("cli.commands.done_task.merge_task_branch")
    @patch("cli.commands.done_task.auto_close_subtasks")
    @patch("cli.commands.done_task.git_stash_pop")
    @patch("cli.commands.done_task.git_stash_push", return_value=True)
    @patch("cli.commands.done_task.is_working_tree_clean")
    def test_stash_popped_on_failure(
        self, mock_clean: MagicMock, mock_stash_push: MagicMock,
        mock_stash_pop: MagicMock, mock_auto: MagicMock, mock_merge: MagicMock,
        mock_remove: MagicMock, mock_snapshot: MagicMock
    ) -> None:
        """Stash is popped even when merge fails (via finally block)."""
        # worktree_path=None skips worktree check, main check returns False (dirty)
        mock_snapshot.return_value = {"worktree_path": None, "project_id": "test"}
        mock_clean.return_value = False
        mock_merge.side_effect = SystemExit(1)
        client = self._setup_mocks()

        with pytest.raises(typer.Exit):
            complete_task(client, "task-123")

        # Stash should still be popped despite failure
        mock_stash_pop.assert_called_once()

    @patch("cli.commands.done_task.get_snapshot_info")
    @patch("cli.commands.done_task.remove_snapshot")
    @patch("cli.commands.done_task.merge_task_branch")
    @patch("cli.commands.done_task.auto_close_subtasks")
    @patch("cli.commands.done_task.is_working_tree_clean", return_value=True)
    @patch("cli.commands.done_task._publish_completed_work")
    def test_no_stash_when_main_clean(
        self, mock_publish: MagicMock, mock_clean: MagicMock, mock_auto: MagicMock, mock_merge: MagicMock,
        mock_remove: MagicMock, mock_snapshot: MagicMock
    ) -> None:
        """Clean main does not trigger stash."""
        mock_snapshot.return_value = {"worktree_path": None, "project_id": "test"}
        client = self._setup_mocks()

        with patch("cli.commands.done_task.git_stash_push") as mock_push:
            complete_task(client, "task-123")
            mock_push.assert_not_called()
        mock_publish.assert_called_once_with("task-123", "test")

    @patch("cli.commands.done_task.get_snapshot_info")
    @patch("cli.commands.done_task.remove_snapshot")
    @patch("cli.commands.done_task.merge_task_branch")
    @patch("cli.commands.done_task.auto_close_subtasks")
    @patch("cli.commands.done_task.is_working_tree_clean", return_value=True)
    @patch("cli.commands.done_task.output_warning")
    @patch("cli.commands.done_task._publish_completed_work")
    def test_status_update_failure_after_merge_warns_and_continues(
        self, mock_publish: MagicMock, mock_warning: MagicMock, mock_clean: MagicMock, mock_auto: MagicMock,
        mock_merge: MagicMock, mock_remove: MagicMock, mock_snapshot: MagicMock
    ) -> None:
        """If status update fails after merge, warn user and still clean up snapshot."""
        from cli._client_base import APIError

        mock_snapshot.return_value = {"worktree_path": None, "project_id": "test"}
        client = self._setup_mocks()
        client.update_status.side_effect = APIError(500, "server error")

        result = complete_task(client, "task-123")

        mock_merge.assert_called_once()
        mock_warning.assert_called_once()
        assert "status update failed" in mock_warning.call_args.args[0]
        assert "st done task-123 --admin" in mock_warning.call_args.args[0]
        mock_remove.assert_called_once()
        mock_publish.assert_called_once_with("task-123", "test")
        assert result["merged"]

    @patch("cli.commands.done_task.get_snapshot_info")
    @patch("cli.commands.done_task.remove_snapshot")
    @patch("cli.commands.done_task.merge_task_branch")
    @patch("cli.commands.done_task.auto_close_subtasks")
    @patch("cli.commands.done_task.is_working_tree_clean", return_value=True)
    @patch("cli.commands.done_task._publish_completed_work")
    def test_completion_does_not_call_removed_review_approval_endpoint(
        self,
        mock_publish: MagicMock,
        mock_clean: MagicMock,
        mock_auto: MagicMock,
        mock_merge: MagicMock,
        mock_remove: MagicMock,
        mock_snapshot: MagicMock,
    ) -> None:
        mock_snapshot.return_value = {"worktree_path": None, "project_id": "test"}
        client = self._setup_mocks()

        complete_task(client, "task-123")

        mock_publish.assert_called_once_with("task-123", "test")
        client.post.assert_not_called()


class TestPublishCompletedWork:
    @patch("cli.commands.done_task.output_warning")
    @patch("subprocess.run")
    def test_publish_warns_when_commit_flow_fails(
        self,
        mock_run: MagicMock,
        mock_warning: MagicMock,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(
            "app.storage.projects.get_project_root_path",
            lambda project_id: "/repos/summitflow",
        )
        mock_run.return_value = MagicMock(
            returncode=1,
            stdout='{"status":"FAILED","repos":[{"status":"ERROR","reason":"push_failed"}]}',
            stderr="",
        )

        _publish_completed_work("task-123", "summitflow")

        mock_warning.assert_called_once()
        assert "push_failed" in mock_warning.call_args.args[0]

    @patch("cli.commands.done_task.output_warning")
    @patch("subprocess.run")
    def test_publish_skips_warning_on_success(
        self,
        mock_run: MagicMock,
        mock_warning: MagicMock,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(
            "app.storage.projects.get_project_root_path",
            lambda project_id: "/repos/summitflow",
        )
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout='{"status":"SUCCESS","repos":[{"status":"SUCCESS","pushed":true,"reason":""}]}',
            stderr="",
        )

        _publish_completed_work("task-123", "summitflow")

        mock_warning.assert_not_called()


class TestSTClientTaskHelpers:
    def test_exposes_completion_readiness_helper(self) -> None:
        client = STClient(base_url="http://localhost:8001", project_id="summitflow")

        assert hasattr(client, "get_task_completion_readiness")


class TestGitStashHelpers:
    """Tests for git_stash_push and git_stash_pop."""

    @patch("subprocess.run")
    def test_stash_push_returns_true_on_new_entry(self, mock_run: MagicMock) -> None:
        """Returns True when a stash entry is created."""
        # stash list before (0 entries), stash push, stash list after (1 entry)
        mock_run.side_effect = [
            MagicMock(stdout="", returncode=0),
            MagicMock(stdout="", returncode=0),
            MagicMock(stdout="stash@{0}: WIP on main: st-done-auto\n", returncode=0),
        ]
        assert git_stash_push()

    @patch("subprocess.run")
    def test_stash_push_returns_false_on_nothing_to_stash(self, mock_run: MagicMock) -> None:
        """Returns False when nothing was stashed."""
        mock_run.side_effect = [
            MagicMock(stdout="", returncode=0),
            MagicMock(stdout="", returncode=0),
            MagicMock(stdout="", returncode=0),
        ]
        assert not git_stash_push()

    @patch("subprocess.run")
    def test_stash_pop_handles_failure_gracefully(self, mock_run: MagicMock) -> None:
        """Pop failure is a warning, not a crash."""
        import subprocess as sp
        mock_run.side_effect = sp.CalledProcessError(1, "git", stderr="conflict")

        # Should not raise
        git_stash_pop()
