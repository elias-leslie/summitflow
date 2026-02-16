"""Tests for st done command smart closure and stash behavior.

Tests the smart auto-verify/auto-close default, strict mode,
stash-merge-pop, and helper functions.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
import typer

from cli.commands.done import (
    _auto_close_subtasks,
    _complete_task,
    _git_stash_pop,
    _git_stash_push,
    _is_subtask_id,
)


class TestIsSubtaskId:
    def test_valid_subtask_ids(self):
        assert _is_subtask_id("1.1") is True
        assert _is_subtask_id("2.3") is True
        assert _is_subtask_id("10.20") is True

    def test_invalid_subtask_ids(self):
        assert _is_subtask_id("task-abc") is False
        assert _is_subtask_id("1.2.3") is False
        assert _is_subtask_id("abc") is False
        assert _is_subtask_id("a.b") is False


class TestAutoCloseSubtasks:
    """Tests for _auto_close_subtasks smart closure logic."""

    def _make_client(self):
        client = MagicMock()
        client._global_url = MagicMock(side_effect=lambda p: f"http://test{p}")
        return client

    def test_skips_already_passed_subtasks(self):
        """Already-passed subtasks are skipped entirely."""
        client = self._make_client()
        client.get_subtasks.return_value = {
            "subtasks": [
                {"subtask_id": "1.1", "passes": True, "steps": []},
            ]
        }

        _auto_close_subtasks(client, "task-123", None)

        # Should NOT call update_step, update_subtask, or merge for passed subtasks
        client.update_step.assert_not_called()
        client.update_subtask.assert_not_called()

    def test_verifies_unpassed_steps(self):
        """Unpassed steps get verified via update_step."""
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
        client.update_step.return_value = {"passes": True}
        client.update_subtask.return_value = {"passes": True}

        with patch("cli.commands.done.merge_subtask_branch"):
            _auto_close_subtasks(client, "task-123", None)

        # Only step 1 should be verified (step 2 already passed)
        client.update_step.assert_called_once_with("task-123", "1.1", 1, passes=True)
        client.update_subtask.assert_called_once_with("task-123", "1.1", passes=True)

    def test_skips_plan_defect_steps(self):
        """Plan_defect steps are skipped (they have fix steps)."""
        client = self._make_client()
        client.get_subtasks.return_value = {
            "subtasks": [
                {
                    "subtask_id": "1.1",
                    "passes": False,
                    "steps": [
                        {"step_number": 1, "passes": True, "status": "pending"},
                        {"step_number": 2, "passes": False, "status": "plan_defect"},
                        {"step_number": 3, "passes": True, "status": "pending"},
                    ],
                },
            ]
        }
        client.update_subtask.return_value = {"passes": True}

        with patch("cli.commands.done.merge_subtask_branch"):
            _auto_close_subtasks(client, "task-123", None)

        # Step 2 (plan_defect) should NOT be verified
        client.update_step.assert_not_called()

    def test_aborts_on_step_failure(self):
        """If step verification returns passes=False, abort immediately."""
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
        client.update_step.return_value = {"passes": False}

        with pytest.raises(typer.Exit):
            _auto_close_subtasks(client, "task-123", None)

        # Subtask should NOT be closed
        client.update_subtask.assert_not_called()

    def test_acknowledges_citations(self):
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

        with patch("cli.commands.done.merge_subtask_branch"):
            _auto_close_subtasks(client, "task-123", None)

        client.acknowledge_no_citations.assert_called_once_with("task-123", "1.1")

    def test_skips_acknowledged_citations(self):
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

        with patch("cli.commands.done.merge_subtask_branch"):
            _auto_close_subtasks(client, "task-123", None)

        client.acknowledge_no_citations.assert_not_called()

    def test_merges_subtask_branch(self):
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
            _auto_close_subtasks(client, "task-123", "test-project")

        mock_merge.assert_called_once_with("task-123", "1.1", project_id="test-project")


class TestCompleteTaskSmart:
    """Tests for _complete_task smart default behavior."""

    def _setup_mocks(self):
        """Set up common mocks for _complete_task tests."""
        client = MagicMock()
        client._global_url = MagicMock(side_effect=lambda p: f"http://test{p}")
        client.get.return_value = {"ready": True, "gates": []}
        client.post.return_value = {"verdict": "APPROVED"}
        client.update_status.return_value = {"status": "completed"}
        return client

    @patch("cli.commands.done_task.remove_snapshot")
    @patch("cli.commands.done_task.merge_task_branch")
    @patch("cli.commands.done_task.auto_close_subtasks")
    @patch("cli.commands.done_task.is_working_tree_clean", return_value=True)
    @patch("cli.commands.done_task._validate_snapshot")
    def test_calls_auto_close_by_default(
        self, mock_snap, mock_clean, mock_auto, mock_merge, mock_remove
    ):
        """Smart mode calls _auto_close_subtasks by default."""
        mock_snap.return_value = {"worktree_path": None, "project_id": "test"}
        client = self._setup_mocks()

        _complete_task(client, "task-123")

        mock_auto.assert_called_once_with(client, "task-123", "test")

    @patch("cli.commands.done_task.remove_snapshot")
    @patch("cli.commands.done_task.merge_task_branch")
    @patch("cli.commands.done_task.auto_close_subtasks")
    @patch("cli.commands.done_task.is_working_tree_clean", return_value=True)
    @patch("cli.commands.done_task._validate_snapshot")
    def test_strict_skips_auto_close(
        self, mock_snap, mock_clean, mock_auto, mock_merge, mock_remove
    ):
        """Strict mode does NOT call _auto_close_subtasks."""
        mock_snap.return_value = {"worktree_path": None, "project_id": "test"}
        client = self._setup_mocks()

        _complete_task(client, "task-123", strict=True)

        mock_auto.assert_not_called()

    @patch("cli.commands.done_task.remove_snapshot")
    @patch("cli.commands.done_task.merge_task_branch")
    @patch("cli.commands.done_task.auto_close_subtasks")
    @patch("cli.commands.done_task.git_stash_pop")
    @patch("cli.commands.done_task.git_stash_push", return_value=True)
    @patch("cli.commands.done_task.is_working_tree_clean")
    @patch("cli.commands.done_task._validate_snapshot")
    def test_stash_merge_pop_on_dirty_main(
        self, mock_snap, mock_clean, mock_stash_push, mock_stash_pop,
        mock_auto, mock_merge, mock_remove
    ):
        """Dirty main gets stashed before merge, popped after."""
        # worktree_path=None means worktree clean check is skipped,
        # only main dirty check runs (returns False = dirty)
        mock_snap.return_value = {"worktree_path": None, "project_id": "test"}
        mock_clean.return_value = False
        client = self._setup_mocks()

        _complete_task(client, "task-123")

        mock_stash_push.assert_called_once()
        mock_stash_pop.assert_called_once()

    @patch("cli.commands.done._is_working_tree_clean")
    @patch("cli.commands.done.get_snapshot_info")
    def test_strict_errors_on_dirty_main(self, mock_snap, mock_clean):
        """Strict mode errors instead of stashing on dirty main."""
        mock_snap.return_value = {"worktree_path": None, "project_id": "test"}
        # First call: worktree check (skipped, no path), Second call: main dirty (False)
        mock_clean.return_value = False
        client = self._setup_mocks()

        with pytest.raises(typer.Exit):
            _complete_task(client, "task-123", strict=True)

    @patch("cli.commands.done_task.remove_snapshot")
    @patch("cli.commands.done_task.merge_task_branch")
    @patch("cli.commands.done_task.auto_close_subtasks")
    @patch("cli.commands.done_task.git_stash_pop")
    @patch("cli.commands.done_task.git_stash_push", return_value=True)
    @patch("cli.commands.done_task.is_working_tree_clean")
    @patch("cli.commands.done_task._validate_snapshot")
    def test_stash_popped_on_failure(
        self, mock_snap, mock_clean, mock_stash_push, mock_stash_pop,
        mock_auto, mock_merge, mock_remove
    ):
        """Stash is popped even when merge fails (via finally block)."""
        # worktree_path=None skips worktree check, main check returns False (dirty)
        mock_snap.return_value = {"worktree_path": None, "project_id": "test"}
        mock_clean.return_value = False
        mock_merge.side_effect = SystemExit(1)
        client = self._setup_mocks()

        with pytest.raises(typer.Exit):
            _complete_task(client, "task-123")

        # Stash should still be popped despite failure
        mock_stash_pop.assert_called_once()

    @patch("cli.commands.done_task.remove_snapshot")
    @patch("cli.commands.done_task.merge_task_branch")
    @patch("cli.commands.done_task.auto_close_subtasks")
    @patch("cli.commands.done_task.is_working_tree_clean", return_value=True)
    @patch("cli.commands.done_task._validate_snapshot")
    def test_no_stash_when_main_clean(
        self, mock_snap, mock_clean, mock_auto, mock_merge, mock_remove
    ):
        """Clean main does not trigger stash."""
        mock_snap.return_value = {"worktree_path": None, "project_id": "test"}
        client = self._setup_mocks()

        with patch("cli.commands.done_task.git_stash_push") as mock_push:
            _complete_task(client, "task-123")
            mock_push.assert_not_called()


class TestGitStashHelpers:
    """Tests for _git_stash_push and _git_stash_pop."""

    @patch("subprocess.run")
    def test_stash_push_returns_true_on_new_entry(self, mock_run):
        """Returns True when a stash entry is created."""
        # stash list before (0 entries), stash push, stash list after (1 entry)
        mock_run.side_effect = [
            MagicMock(stdout="", returncode=0),
            MagicMock(stdout="", returncode=0),
            MagicMock(stdout="stash@{0}: WIP on main: st-done-auto\n", returncode=0),
        ]
        assert _git_stash_push() is True

    @patch("subprocess.run")
    def test_stash_push_returns_false_on_nothing_to_stash(self, mock_run):
        """Returns False when nothing was stashed."""
        mock_run.side_effect = [
            MagicMock(stdout="", returncode=0),
            MagicMock(stdout="", returncode=0),
            MagicMock(stdout="", returncode=0),
        ]
        assert _git_stash_push() is False

    @patch("subprocess.run")
    def test_stash_pop_handles_failure_gracefully(self, mock_run):
        """Pop failure is a warning, not a crash."""
        import subprocess as sp
        mock_run.side_effect = sp.CalledProcessError(1, "git", stderr="conflict")

        # Should not raise
        _git_stash_pop()
