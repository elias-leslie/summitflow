"""Tests for task completion status transitions."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from app.tasks.autonomous.exec_modules.completion_status import (
    build_early_completion_verification,
    build_successful_completion_verification,
    transition_to_complete,
)

MODULE = "app.tasks.autonomous.exec_modules.completion_status"


class TestCompletionVerificationEvidence:
    def test_successful_pipeline_marks_quality_gate_evidence(self) -> None:
        result = build_successful_completion_verification(
            [
                {
                    "self_fix_attempts": 0,
                    "supervisor_guided_attempts": 0,
                    "extensions_granted": 0,
                }
            ]
        )

        assert result["evidence_verified"] is True
        assert result["verification_source"] == "autonomous_quality_gate"
        assert result["execution_clean"] is True

    def test_early_pipeline_marks_preverified_subtask_evidence(self) -> None:
        result = build_early_completion_verification(2)

        assert result["evidence_verified"] is True
        assert result["verification_source"] == "autonomous_preverified_subtasks"
        assert result["subtask_count"] == 2


class TestTransitionToComplete:
    """Tests for transition_to_complete.

    The AI-Review tier and auto-merge arm have been removed; the function now
    always sets status=completed and runs checkpoint cleanup.
    """

    @patch("app.tasks.autonomous.cleanup.checkpoint_cleanup.cleanup_task_checkpoint")
    @patch(f"{MODULE}.task_store")
    def test_completes_and_runs_cleanup(
        self, mock_store: MagicMock, mock_cleanup: MagicMock
    ) -> None:
        """Status flips to completed and checkpoint cleanup runs."""
        mock_cleanup.return_value = {"status": "cleaned", "checkout_path": "/tmp/wt"}

        result = transition_to_complete("t-1", "proj", "test")

        assert result == "completed"
        mock_store.update_task_status.assert_called_with("t-1", "completed")
        mock_cleanup.assert_called_once_with("t-1", delete_branch=False, project_id="proj")

    @patch("app.tasks.autonomous.cleanup.checkpoint_cleanup.cleanup_task_checkpoint")
    @patch(f"{MODULE}.task_store")
    def test_dispatch_argument_is_ignored(
        self, mock_store: MagicMock, mock_cleanup: MagicMock
    ) -> None:
        """The legacy `dispatch` parameter is accepted but never invoked."""
        mock_cleanup.return_value = {"status": "cleaned", "checkout_path": "/tmp/wt"}
        dispatch = MagicMock()

        result = transition_to_complete("t-1", "proj", "test", dispatch)

        assert result == "completed"
        dispatch.assert_not_called()
