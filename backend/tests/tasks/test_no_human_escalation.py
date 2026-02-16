"""Tests for supervisor-based escalation replacing human review gates.

Verifies the 4 new supervisor functions:
1. _supervisor_validate_plan (planning.py)
2. _supervisor_circuit_breaker_triage (execution.py)
3. _supervisor_resolve_escalation (review.py)
4. _block_with_recommendation (escalation.py)
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch


class TestSupervisorValidatePlan:
    """Test _supervisor_validate_plan in planning.py."""

    @patch("app.tasks.autonomous.planning_routing.get_sync_client")
    def test_approved_returns_true(self, mock_client: MagicMock) -> None:
        from app.tasks.autonomous.planning import _supervisor_validate_plan

        mock_client.return_value.complete.return_value = MagicMock(
            content="APPROVED - proceed with execution"
        )
        assert _supervisor_validate_plan("task-1", "complex reasoning", "test-project") is True

    @patch("app.tasks.autonomous.planning_routing.get_sync_client")
    def test_blocked_returns_false(self, mock_client: MagicMock) -> None:
        from app.tasks.autonomous.planning import _supervisor_validate_plan

        mock_client.return_value.complete.return_value = MagicMock(
            content="BLOCKED - architecture review needed first"
        )
        assert _supervisor_validate_plan("task-1", "complex reasoning", "test-project") is False

    @patch("app.tasks.autonomous.planning_routing.get_sync_client")
    def test_exception_returns_true_optimistic(self, mock_client: MagicMock) -> None:
        from app.tasks.autonomous.planning import _supervisor_validate_plan

        mock_client.return_value.complete.side_effect = RuntimeError("API down")
        assert _supervisor_validate_plan("task-1", "reasoning", "test-project") is True


class TestSupervisorCircuitBreakerTriage:
    """Test _supervisor_circuit_breaker_triage in execution.py."""

    @patch("app.tasks.autonomous.exec_modules.agent_routing.get_sync_client")
    def test_continue_returns_true(self, mock_client: MagicMock) -> None:
        from app.tasks.autonomous.execution import _supervisor_circuit_breaker_triage

        mock_client.return_value.complete.return_value = MagicMock(
            content="CONTINUE - the remaining subtasks are independent"
        )
        assert _supervisor_circuit_breaker_triage("task-1", "abc123", 2, "test-project") is True

    @patch("app.tasks.autonomous.exec_modules.agent_routing.get_sync_client")
    def test_block_returns_false(self, mock_client: MagicMock) -> None:
        from app.tasks.autonomous.execution import _supervisor_circuit_breaker_triage

        mock_client.return_value.complete.return_value = MagicMock(
            content="BLOCK - same env issue will affect all remaining subtasks"
        )
        assert _supervisor_circuit_breaker_triage("task-1", "abc123", 2, "test-project") is False

    @patch("app.tasks.autonomous.exec_modules.agent_routing.get_sync_client")
    def test_exception_returns_false_conservative(self, mock_client: MagicMock) -> None:
        from app.tasks.autonomous.execution import _supervisor_circuit_breaker_triage

        mock_client.return_value.complete.side_effect = RuntimeError("API down")
        assert _supervisor_circuit_breaker_triage("task-1", "abc123", 2, "test-project") is False


class TestSupervisorResolveEscalation:
    """Test _supervisor_resolve_escalation in review.py."""

    @patch("app.tasks.autonomous.review_modules.routing.get_sync_client")
    def test_approve_decision(self, mock_client: MagicMock) -> None:
        from app.tasks.autonomous.review import _supervisor_resolve_escalation

        mock_client.return_value.complete.return_value = MagicMock(
            content="APPROVE - the concern is minor"
        )
        assert _supervisor_resolve_escalation("task-1", "minor issue", "test-project") == "approve"

    @patch("app.tasks.autonomous.review_modules.routing.get_sync_client")
    def test_fix_decision(self, mock_client: MagicMock) -> None:
        from app.tasks.autonomous.review import _supervisor_resolve_escalation

        mock_client.return_value.complete.return_value = MagicMock(
            content="FIX - needs error handling added"
        )
        assert _supervisor_resolve_escalation("task-1", "missing error handling", "test-project") == "fix"

    @patch("app.tasks.autonomous.review_modules.routing.get_sync_client")
    def test_block_decision(self, mock_client: MagicMock) -> None:
        from app.tasks.autonomous.review import _supervisor_resolve_escalation

        mock_client.return_value.complete.return_value = MagicMock(
            content="BLOCK - fundamental design issue"
        )
        assert _supervisor_resolve_escalation("task-1", "design issue", "test-project") == "block"

    @patch("app.tasks.autonomous.review_modules.routing.get_sync_client")
    def test_exception_returns_block(self, mock_client: MagicMock) -> None:
        from app.tasks.autonomous.review import _supervisor_resolve_escalation

        mock_client.return_value.complete.side_effect = RuntimeError("API down")
        assert _supervisor_resolve_escalation("task-1", "issue", "test-project") == "block"


class TestBlockWithRecommendation:
    """Test _block_with_recommendation in escalation.py."""

    @patch("app.tasks.autonomous.escalation.log_task_event")
    @patch("app.tasks.autonomous.escalation.task_store")
    @patch("app.tasks.autonomous.escalation.get_sync_client")
    def test_sets_blocked_status(
        self,
        mock_client: MagicMock,
        mock_store: MagicMock,
        mock_log: MagicMock,
    ) -> None:
        from app.tasks.autonomous.escalation import _block_with_recommendation

        mock_client.return_value.complete.return_value = MagicMock(
            content="Recommendation: check environment config"
        )
        result = _block_with_recommendation(
            "task-1", "1.1", "step failed", 5, project_id="test-project"
        )
        assert result["status"] == "blocked"
        mock_store.update_task_status.assert_called_with("task-1", "blocked")

    @patch("app.tasks.autonomous.escalation.log_task_event")
    @patch("app.tasks.autonomous.escalation.task_store")
    @patch("app.tasks.autonomous.escalation.get_sync_client")
    def test_exception_still_blocks(
        self,
        mock_client: MagicMock,
        mock_store: MagicMock,
        mock_log: MagicMock,
    ) -> None:
        from app.tasks.autonomous.escalation import _block_with_recommendation

        mock_client.return_value.complete.side_effect = RuntimeError("API down")
        result = _block_with_recommendation(
            "task-1", "1.1", "step failed", 5, project_id="test-project"
        )
        assert result["status"] == "blocked"
        mock_store.update_task_status.assert_called_with("task-1", "blocked")


class TestNoPipelineHumanEscalation:
    """Meta-test: verify no autonomous pipeline code references needs_review or human_review."""

    def test_no_needs_review_in_autonomous_pipeline(self) -> None:
        from pathlib import Path

        autonomous_dir = Path(__file__).parent.parent.parent / "app" / "tasks" / "autonomous"
        for py_file in autonomous_dir.glob("*.py"):
            content = py_file.read_text()
            assert "needs_review" not in content, (
                f"{py_file.name} still references 'needs_review'"
            )

    def test_no_human_review_in_autonomous_pipeline(self) -> None:
        from pathlib import Path

        autonomous_dir = Path(__file__).parent.parent.parent / "app" / "tasks" / "autonomous"
        for py_file in autonomous_dir.glob("*.py"):
            content = py_file.read_text()
            assert "human_review" not in content, (
                f"{py_file.name} still references 'human_review'"
            )
