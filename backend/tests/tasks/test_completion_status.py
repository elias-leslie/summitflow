"""Tests for task completion status transitions."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from app.tasks.autonomous.exec_modules.completion_status import (
    build_early_completion_verification,
    build_successful_completion_verification,
    mark_failed_with_evidence,
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
    @patch("cli.commands.done_task._accept_completed_work")
    @patch(f"{MODULE}.task_store")
    def test_completes_and_runs_cleanup(
        self,
        mock_store: MagicMock,
        mock_accept: MagicMock,
        mock_cleanup: MagicMock,
    ) -> None:
        """Status flips to completed and checkpoint cleanup runs."""
        mock_cleanup.return_value = {"status": "cleaned", "checkout_path": "/tmp/wt"}

        result = transition_to_complete("t-1", "proj", "test")

        assert result == "completed"
        mock_accept.assert_called_once_with("t-1", "proj")
        mock_store.update_task_status.assert_called_with("t-1", "completed")
        mock_cleanup.assert_called_once_with("t-1", delete_branch=False, project_id="proj")

    @patch("app.tasks.autonomous.cleanup.checkpoint_cleanup.cleanup_task_checkpoint")
    @patch("cli.commands.done_task._accept_completed_work")
    @patch(f"{MODULE}.task_store")
    def test_dispatch_argument_is_ignored(
        self,
        mock_store: MagicMock,
        _mock_accept: MagicMock,
        mock_cleanup: MagicMock,
    ) -> None:
        """The legacy `dispatch` parameter is accepted but never invoked."""
        mock_cleanup.return_value = {"status": "cleaned", "checkout_path": "/tmp/wt"}
        dispatch = MagicMock()

        result = transition_to_complete("t-1", "proj", "test", dispatch)

        assert result == "completed"
        dispatch.assert_not_called()

    @patch("app.tasks.autonomous.cleanup.checkpoint_cleanup.cleanup_task_checkpoint")
    @patch("cli.commands.done_task._accept_completed_work")
    @patch(f"{MODULE}.task_store")
    def test_acceptance_failure_blocks_completion_and_cleanup(
        self,
        mock_store: MagicMock,
        mock_accept: MagicMock,
        mock_cleanup: MagicMock,
    ) -> None:
        """A failed source-bound acceptance cannot be converted into completion."""
        mock_accept.side_effect = RuntimeError("acceptance_checks_failed")

        try:
            transition_to_complete("t-1", "proj", "test")
        except RuntimeError as exc:
            assert str(exc) == "acceptance_checks_failed"
        else:
            raise AssertionError("acceptance failure should propagate")

        mock_store.update_task_status.assert_not_called()
        mock_cleanup.assert_not_called()

    @patch("app.tasks.autonomous.cleanup.checkpoint_cleanup.cleanup_task_checkpoint")
    @patch("cli.commands.done_task._accept_completed_work")
    @patch(f"{MODULE}.task_store")
    def test_verified_external_work_skips_code_acceptance(
        self,
        mock_store: MagicMock,
        mock_accept: MagicMock,
        mock_cleanup: MagicMock,
    ) -> None:
        mock_cleanup.return_value = {"status": "cleaned"}

        result = transition_to_complete(
            "t-1",
            "proj",
            "external work verified",
            acceptance_required=False,
        )

        assert result == "completed"
        mock_accept.assert_not_called()
        mock_store.update_task_status.assert_called_once_with("t-1", "completed")

    @patch("app.tasks.autonomous.cleanup.checkpoint_cleanup.cleanup_task_checkpoint")
    @patch("cli.commands.done_task._accept_completed_work")
    @patch(f"{MODULE}.task_store")
    def test_required_completion_evidence_failure_cannot_cleanup_or_complete(
        self,
        mock_store: MagicMock,
        _mock_accept: MagicMock,
        mock_cleanup: MagicMock,
    ) -> None:
        mock_store.update_task_status.side_effect = ValueError(
            "Task acceptance remains incomplete: live_validation"
        )

        try:
            transition_to_complete("t-1", "proj", "test")
        except ValueError as exc:
            assert "live_validation" in str(exc)
        else:
            raise AssertionError("required evidence failure should propagate")

        mock_cleanup.assert_not_called()


@patch(f"{MODULE}.store_execution_verification")
@patch(f"{MODULE}.store_verification")
@patch(f"{MODULE}.task_store")
def test_failed_transition_restores_receipts_and_records_failure(
    mock_store: MagicMock,
    mock_store_receipts: MagicMock,
    mock_store_execution: MagicMock,
) -> None:
    receipts = {
        "acceptance": {"state": "success", "source_commit": "abc"},
        "deployment": {"state": "succeeded", "source_commit": "abc"},
        "live_validation": {"source_commit": "abc", "checks": []},
    }
    mock_store.get_task.return_value = {
        "verification_result": {**receipts, "publication": {"state": "pending"}}
    }

    mark_failed_with_evidence(
        "t-1",
        "proj",
        stage="status_transition",
        reason="required live validation missing",
    )

    mock_store.update_task_status.assert_called_once_with("t-1", "failed")
    mock_store_receipts.assert_called_once_with("t-1", "proj", receipts)
    failure = mock_store_execution.call_args.args[2]["autonomous_failure"]
    assert failure == {
        "state": "failed",
        "stage": "status_transition",
        "reason": "required live validation missing",
    }


@patch(f"{MODULE}.store_execution_verification")
@patch(f"{MODULE}.store_verification")
@patch(f"{MODULE}.task_store")
def test_acceptance_failure_keeps_original_receipt_artifact_detail(
    mock_store: MagicMock,
    _mock_store_receipts: MagicMock,
    mock_store_execution: MagicMock,
) -> None:
    original_failure = {
        "state": "failed",
        "stage": "acceptance",
        "reason": "acceptance_checks_failed; acceptance evidence: /tmp/receipt.json",
    }
    mock_store.get_task.return_value = {
        "verification_result": {"autonomous_failure": original_failure}
    }

    mark_failed_with_evidence(
        "t-1",
        "proj",
        stage="acceptance",
        reason="Canonical source acceptance failed",
    )

    assert (
        mock_store_execution.call_args.args[2]["autonomous_failure"]
        == original_failure
    )
