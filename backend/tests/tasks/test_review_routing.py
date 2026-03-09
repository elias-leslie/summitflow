"""Tests for review verdict routing and QA loop."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

from app.tasks.autonomous.review_modules.actions import (
    MAX_QA_LOOP_ITERATIONS,
    RECURRING_ISSUE_ESCALATION_THRESHOLD,
    create_fix_subtask,
    handle_plan_defect,
    run_qa_loop,
)
from app.tasks.autonomous.review_modules.routing import (
    _handle_approved,
    _handle_escalation,
    _handle_needs_fix,
    route_based_on_verdict,
    supervisor_resolve_escalation,
)

# ---------------------------------------------------------------------------
# route_based_on_verdict
# ---------------------------------------------------------------------------


class TestRouteBasedOnVerdict:
    """Tests for the top-level verdict router."""

    @patch("app.tasks.autonomous.review_modules.routing._handle_approved")
    def test_approved_routes_to_approved_handler(self, mock_handler: MagicMock) -> None:
        route_based_on_verdict("task-1", "SIMPLE", {"verdict": "APPROVED"})
        mock_handler.assert_called_once_with("task-1", "SIMPLE")

    @patch("app.tasks.autonomous.review_modules.routing._handle_needs_fix")
    def test_needs_fix_routes_to_needs_fix_handler(self, mock_handler: MagicMock) -> None:
        result = {"verdict": "NEEDS_FIX", "concerns": ["x"]}
        route_based_on_verdict("task-1", "STANDARD", result)
        mock_handler.assert_called_once_with("task-1", result)

    @patch("app.tasks.autonomous.review_modules.routing._handle_needs_fix")
    def test_reject_routes_to_needs_fix_handler(self, mock_handler: MagicMock) -> None:
        result = {"verdict": "REJECT", "concerns": ["x"]}
        route_based_on_verdict("task-1", "STANDARD", result)
        mock_handler.assert_called_once_with("task-1", result)

    @patch("app.tasks.autonomous.review_modules.routing.log_task_event")
    @patch("app.tasks.autonomous.review_modules.routing.task_store")
    @patch("app.tasks.autonomous.review_modules.routing.handle_plan_defect")
    def test_plan_defect_routes_correctly(
        self, mock_handler: MagicMock, mock_store: MagicMock, mock_log: MagicMock
    ) -> None:
        result = {"verdict": "PLAN_DEFECT"}
        route_based_on_verdict("task-1", "STANDARD", result)
        mock_handler.assert_called_once_with("task-1", result)

    @patch("app.tasks.autonomous.review_modules.routing._handle_escalation")
    def test_unknown_verdict_routes_to_escalation(self, mock_handler: MagicMock) -> None:
        result = {"verdict": "UNKNOWN"}
        route_based_on_verdict("task-1", "STANDARD", result)
        mock_handler.assert_called_once_with("task-1", result)

    @patch("app.tasks.autonomous.review_modules.routing._handle_escalation")
    def test_escalate_verdict_routes_to_escalation(self, mock_handler: MagicMock) -> None:
        result = {"verdict": "ESCALATE"}
        route_based_on_verdict("task-1", "STANDARD", result)
        mock_handler.assert_called_once_with("task-1", result)


# ---------------------------------------------------------------------------
# _handle_approved
# ---------------------------------------------------------------------------


class TestHandleApproved:
    """Tests for APPROVED verdict handling."""

    @patch("app.tasks.autonomous.review_modules.routing.log_task_event")
    @patch("app.tasks.autonomous.review_modules.routing.auto_merge")
    @patch("app.tasks.autonomous.review_modules.routing.agent_configs")
    @patch("app.tasks.autonomous.review_modules.routing.task_store")
    def test_auto_merge_when_enabled(
        self, mock_store: MagicMock, mock_configs: MagicMock,
        mock_merge: MagicMock, mock_log: MagicMock,
    ) -> None:
        mock_store.get_task.return_value = {"project_id": "test-project"}
        mock_configs.get_auto_merge_enabled.return_value = True
        mock_merge.return_value = {"status": "merged", "post_merge_valid": True}

        _handle_approved("task-1", "SIMPLE")

        mock_merge.assert_called_once_with("task-1")
        mock_store.update_task_status.assert_not_called()

    @patch("app.tasks.autonomous.cleanup.worktree_cleanup.cleanup_task_worktree")
    @patch("app.tasks.autonomous.review_modules.routing.log_task_event")
    @patch("app.tasks.autonomous.review_modules.routing.auto_merge")
    @patch("app.tasks.autonomous.review_modules.routing.agent_configs")
    @patch("app.tasks.autonomous.review_modules.routing.task_store")
    def test_no_merge_when_disabled(
        self, mock_store: MagicMock, mock_configs: MagicMock,
        mock_merge: MagicMock, mock_log: MagicMock, mock_cleanup: MagicMock,
    ) -> None:
        mock_store.get_task.return_value = {"project_id": "test-project"}
        mock_configs.get_auto_merge_enabled.return_value = False
        mock_cleanup.return_value = {"status": "cleaned", "worktree_path": "/tmp/wt"}

        _handle_approved("task-1", "STANDARD")

        mock_merge.assert_not_called()
        mock_store.update_task_status.assert_called_once_with("task-1", "completed")
        mock_cleanup.assert_called_once_with("task-1", delete_branch=False, project_id="test-project")

    @patch("app.tasks.autonomous.review_modules.routing.log_task_event")
    @patch("app.tasks.autonomous.review_modules.routing.auto_merge")
    @patch("app.tasks.autonomous.review_modules.routing.agent_configs")
    @patch("app.tasks.autonomous.review_modules.routing.task_store")
    def test_auto_merge_conflict_marks_task_conflicted(
        self, mock_store: MagicMock, mock_configs: MagicMock,
        mock_merge: MagicMock, mock_log: MagicMock,
    ) -> None:
        mock_store.get_task.return_value = {"project_id": "test-project"}
        mock_configs.get_auto_merge_enabled.return_value = True
        mock_merge.return_value = {"status": "conflicted"}

        _handle_approved("task-1", "SIMPLE")

        mock_store.update_task_status.assert_not_called()


# ---------------------------------------------------------------------------
# _handle_needs_fix
# ---------------------------------------------------------------------------


class TestHandleNeedsFix:
    """Tests for NEEDS_FIX verdict handling."""

    @patch("app.tasks.autonomous.review_modules.routing.log_task_event")
    @patch("app.tasks.autonomous.review_modules.routing.auto_merge")
    @patch("app.tasks.autonomous.review_modules.routing.agent_configs")
    @patch("app.tasks.autonomous.review_modules.routing.task_store")
    def test_no_concerns_treats_as_approved(
        self, mock_store: MagicMock, mock_configs: MagicMock,
        mock_merge: MagicMock, mock_log: MagicMock,
    ) -> None:
        mock_store.get_task.return_value = {"project_id": "test-project"}
        mock_configs.get_auto_merge_enabled.return_value = True
        mock_merge.return_value = {"status": "merged", "post_merge_valid": True}

        _handle_needs_fix("task-1", {"verdict": "NEEDS_FIX", "concerns": []})

        mock_merge.assert_called_once_with("task-1")
        mock_store.update_task_status.assert_not_called()

    @patch("app.tasks.autonomous.review_modules.routing.log_task_event")
    @patch("app.tasks.autonomous.review_modules.routing.create_fix_subtask")
    @patch("app.tasks.autonomous.review_modules.routing.run_qa_loop")
    @patch("app.services.worktree.get_task_worktree")
    @patch("app.tasks.autonomous.review_modules.routing.task_store")
    def test_with_concerns_runs_qa_loop(
        self, mock_store: MagicMock, mock_worktree: MagicMock,
        mock_loop: MagicMock, mock_fix: MagicMock, mock_log: MagicMock,
    ) -> None:
        mock_store.get_task.return_value = {"project_id": "test-project", "complexity": "STANDARD"}
        mock_wt = MagicMock()
        mock_wt.path = "/tmp/worktree"
        mock_worktree.return_value = mock_wt
        mock_loop.return_value = "APPROVED"

        review = {"verdict": "NEEDS_FIX", "concerns": ["missing types"]}
        _handle_needs_fix("task-1", review)

        mock_loop.assert_called_once_with("task-1", "test-project", review, "/tmp/worktree")
        mock_fix.assert_not_called()

    @patch("app.tasks.autonomous.review_modules.routing.log_task_event")
    @patch("app.tasks.autonomous.review_modules.routing.create_fix_subtask")
    @patch("app.tasks.autonomous.review_modules.routing.run_qa_loop")
    @patch("app.services.worktree.get_task_worktree")
    @patch("app.tasks.autonomous.review_modules.routing.task_store")
    def test_qa_loop_exhausted_creates_fix_subtask(
        self, mock_store: MagicMock, mock_worktree: MagicMock,
        mock_loop: MagicMock, mock_fix: MagicMock, mock_log: MagicMock,
    ) -> None:
        mock_store.get_task.return_value = {"project_id": "test-project"}
        mock_wt = MagicMock()
        mock_wt.path = "/tmp/worktree"
        mock_worktree.return_value = mock_wt
        mock_loop.return_value = "NEEDS_FIX"

        review = {"verdict": "NEEDS_FIX", "concerns": ["security issue"]}
        _handle_needs_fix("task-1", review)

        mock_fix.assert_called_once_with("task-1", review)
        mock_store.update_task_status.assert_called_with("task-1", "running")

    @patch("app.tasks.autonomous.review_modules.routing.log_task_event")
    @patch("app.tasks.autonomous.review_modules.routing._handle_escalation")
    @patch("app.tasks.autonomous.review_modules.routing.run_qa_loop")
    @patch("app.services.worktree.get_task_worktree")
    @patch("app.tasks.autonomous.review_modules.routing.task_store")
    def test_qa_loop_escalate_routes_to_escalation(
        self, mock_store: MagicMock, mock_worktree: MagicMock,
        mock_loop: MagicMock, mock_escalate: MagicMock, mock_log: MagicMock,
    ) -> None:
        mock_store.get_task.return_value = {"project_id": "test-project"}
        mock_wt = MagicMock()
        mock_wt.path = "/tmp/worktree"
        mock_worktree.return_value = mock_wt
        mock_loop.return_value = "ESCALATE"

        review = {"verdict": "NEEDS_FIX", "concerns": ["recurring issue"]}
        _handle_needs_fix("task-1", review)

        mock_escalate.assert_called_once_with("task-1", review)

    @patch("app.tasks.autonomous.review_modules.routing.log_task_event")
    @patch("app.tasks.autonomous.review_modules.routing.create_fix_subtask")
    @patch("app.services.worktree.get_task_worktree")
    @patch("app.tasks.autonomous.review_modules.routing.task_store")
    def test_no_worktree_falls_back_to_fix_subtask(
        self, mock_store: MagicMock, mock_worktree: MagicMock,
        mock_fix: MagicMock, mock_log: MagicMock,
    ) -> None:
        mock_store.get_task.return_value = {"project_id": "test-project"}
        mock_worktree.return_value = None

        review = {"verdict": "NEEDS_FIX", "concerns": ["type error"]}
        _handle_needs_fix("task-1", review)

        mock_fix.assert_called_once_with("task-1", review)


# ---------------------------------------------------------------------------
# run_qa_loop
# ---------------------------------------------------------------------------


class TestRunQALoop:
    """Tests for the tight QA fixer-reviewer loop."""

    def _mock_client(self, review_responses: list[str]) -> MagicMock:
        """Create a mock Agent Hub client with sequential review responses."""
        client = MagicMock()
        # Fix calls return nothing meaningful, review calls return content
        responses = []
        for text in review_responses:
            fix_resp = MagicMock()
            fix_resp.content = "Fixed the issues."
            review_resp = MagicMock()
            review_resp.content = text
            responses.extend([fix_resp, review_resp])
        client.complete.side_effect = responses
        return client

    @patch("app.tasks.autonomous.review_modules.actions.save_qa_fix_pattern")
    @patch("app.tasks.autonomous.review_modules.actions.log_task_event")
    @patch("app.tasks.autonomous.review_modules.actions.get_sync_client")
    def test_approved_on_first_iteration(
        self, mock_get_client: MagicMock, mock_log: MagicMock,
        mock_save: MagicMock, tmp_path: Any,
    ) -> None:
        client = self._mock_client(['{"verdict": "APPROVED", "concerns": []}'])
        mock_get_client.return_value = client

        result = run_qa_loop(
            "task-1", "test-project",
            {"concerns": ["missing type hints"], "recommendation": "Add types"},
            str(tmp_path),
        )

        assert result == "APPROVED"
        assert client.complete.call_count == 2  # fixer + reviewer
        mock_save.assert_called_once()

    @patch("app.tasks.autonomous.review_modules.actions.save_qa_fix_pattern")
    @patch("app.tasks.autonomous.review_modules.actions.log_task_event")
    @patch("app.tasks.autonomous.review_modules.actions.get_sync_client")
    def test_approved_after_multiple_iterations(
        self, mock_get_client: MagicMock, mock_log: MagicMock,
        mock_save: MagicMock, tmp_path: Any,
    ) -> None:
        client = self._mock_client([
            '{"verdict": "NEEDS_FIX", "concerns": ["still broken"], "recommendation": "try again"}',
            '{"verdict": "APPROVED", "concerns": []}',
        ])
        mock_get_client.return_value = client

        result = run_qa_loop(
            "task-1", "test-project",
            {"concerns": ["bug"], "recommendation": "fix it"},
            str(tmp_path),
        )

        assert result == "APPROVED"
        assert client.complete.call_count == 4  # 2 iterations * (fixer + reviewer)

    @patch("app.tasks.autonomous.review_modules.actions.log_task_event")
    @patch("app.tasks.autonomous.review_modules.actions.get_sync_client")
    def test_escalate_on_recurring_issue(
        self, mock_get_client: MagicMock, mock_log: MagicMock,
        tmp_path: Any,
    ) -> None:
        # Same concern repeated RECURRING_ISSUE_ESCALATION_THRESHOLD times
        same_concern = "missing error handling in foo()"
        responses = [
            f'{{"verdict": "NEEDS_FIX", "concerns": ["{same_concern}"], "recommendation": "fix"}}',
        ] * RECURRING_ISSUE_ESCALATION_THRESHOLD
        client = self._mock_client(responses)
        mock_get_client.return_value = client

        result = run_qa_loop(
            "task-1", "test-project",
            {"concerns": [same_concern], "recommendation": "fix"},
            str(tmp_path),
        )

        assert result == "ESCALATE"

    @patch("app.tasks.autonomous.review_modules.actions.log_task_event")
    @patch("app.tasks.autonomous.review_modules.actions.get_sync_client")
    def test_needs_fix_after_max_iterations(
        self, mock_get_client: MagicMock, mock_log: MagicMock,
        tmp_path: Any,
    ) -> None:
        # Each iteration returns a DIFFERENT concern so recurring threshold isn't hit
        responses = [
            f'{{"verdict": "NEEDS_FIX", "concerns": ["issue_{i}"], "recommendation": "fix {i}"}}'
            for i in range(MAX_QA_LOOP_ITERATIONS)
        ]
        client = self._mock_client(responses)
        mock_get_client.return_value = client

        result = run_qa_loop(
            "task-1", "test-project",
            {"concerns": ["initial issue"], "recommendation": "fix it"},
            str(tmp_path),
        )

        assert result == "NEEDS_FIX"
        # MAX_QA_LOOP_ITERATIONS * 2 calls (fixer + reviewer each)
        assert client.complete.call_count == MAX_QA_LOOP_ITERATIONS * 2

    @patch("app.tasks.autonomous.review_modules.actions.log_task_event")
    @patch("app.tasks.autonomous.review_modules.actions.get_sync_client")
    def test_fixer_exception_escalates(
        self, mock_get_client: MagicMock, mock_log: MagicMock,
        tmp_path: Any,
    ) -> None:
        client = MagicMock()
        client.complete.side_effect = RuntimeError("Agent Hub connection failed")
        mock_get_client.return_value = client

        result = run_qa_loop(
            "task-1", "test-project",
            {"concerns": ["bug"], "recommendation": "fix"},
            str(tmp_path),
        )

        assert result == "ESCALATE"

    @patch("app.tasks.autonomous.review_modules.actions.log_task_event")
    @patch("app.tasks.autonomous.review_modules.actions.get_sync_client")
    def test_reviewer_exception_escalates(
        self, mock_get_client: MagicMock, mock_log: MagicMock,
        tmp_path: Any,
    ) -> None:
        client = MagicMock()
        # Fixer succeeds, reviewer throws
        fix_resp = MagicMock()
        fix_resp.content = "Fixed."
        client.complete.side_effect = [fix_resp, RuntimeError("Reviewer failed")]
        mock_get_client.return_value = client

        result = run_qa_loop(
            "task-1", "test-project",
            {"concerns": ["bug"], "recommendation": "fix"},
            str(tmp_path),
        )

        assert result == "ESCALATE"

    @patch("app.tasks.autonomous.review_modules.actions.log_task_event")
    @patch("app.tasks.autonomous.review_modules.actions.get_sync_client")
    def test_escalate_verdict_from_reviewer(
        self, mock_get_client: MagicMock, mock_log: MagicMock,
        tmp_path: Any,
    ) -> None:
        client = self._mock_client([
            '{"verdict": "ESCALATE", "concerns": ["security risk"], "recommendation": "needs human review"}',
        ])
        mock_get_client.return_value = client

        result = run_qa_loop(
            "task-1", "test-project",
            {"concerns": ["security risk"], "recommendation": "review"},
            str(tmp_path),
        )

        assert result == "ESCALATE"


# ---------------------------------------------------------------------------
# supervisor_resolve_escalation
# ---------------------------------------------------------------------------


class TestSupervisorResolveEscalation:
    """Tests for supervisor escalation resolution."""

    @patch("app.tasks.autonomous.review_modules.routing.get_sync_client")
    def test_approve_decision(self, mock_get_client: MagicMock) -> None:
        client = MagicMock()
        response = MagicMock()
        response.content = "APPROVE - the changes look fine"
        client.complete.return_value = response
        mock_get_client.return_value = client

        decision = supervisor_resolve_escalation("task-1", "minor issue", "test-project")
        assert decision == "approve"

    @patch("app.tasks.autonomous.review_modules.routing.get_sync_client")
    def test_fix_decision(self, mock_get_client: MagicMock) -> None:
        client = MagicMock()
        response = MagicMock()
        response.content = "FIX - needs error handling"
        client.complete.return_value = response
        mock_get_client.return_value = client

        decision = supervisor_resolve_escalation("task-1", "missing handlers", "test-project")
        assert decision == "fix"

    @patch("app.tasks.autonomous.review_modules.routing.get_sync_client")
    def test_block_decision(self, mock_get_client: MagicMock) -> None:
        client = MagicMock()
        response = MagicMock()
        response.content = "BLOCK - too risky"
        client.complete.return_value = response
        mock_get_client.return_value = client

        decision = supervisor_resolve_escalation("task-1", "risky change", "test-project")
        assert decision == "block"

    @patch("app.tasks.autonomous.review_modules.routing.get_sync_client")
    def test_exception_defaults_to_block(self, mock_get_client: MagicMock) -> None:
        client = MagicMock()
        client.complete.side_effect = RuntimeError("connection failed")
        mock_get_client.return_value = client

        decision = supervisor_resolve_escalation("task-1", "issue", "test-project")
        assert decision == "block"


# ---------------------------------------------------------------------------
# create_fix_subtask
# ---------------------------------------------------------------------------


class TestCreateFixSubtask:
    """Tests for fix subtask creation."""

    @patch("app.tasks.autonomous.review_modules.actions.log_task_event")
    @patch("app.storage.subtasks.create_subtask")
    def test_creates_subtask_with_concerns(
        self, mock_create: MagicMock, mock_log: MagicMock,
    ) -> None:
        review = {
            "concerns": ["missing types", "no tests"],
            "recommendation": "Add type hints and tests",
        }
        create_fix_subtask("task-1", review)

        mock_create.assert_called_once()
        call_kwargs = mock_create.call_args
        assert call_kwargs.kwargs["task_id"] == "task-1"
        assert call_kwargs.kwargs["subtask_id"] == "99.1"
        assert "missing types" in call_kwargs.kwargs["description"]


# ---------------------------------------------------------------------------
# handle_plan_defect
# ---------------------------------------------------------------------------


class TestHandlePlanDefect:
    """Tests for plan defect handling."""

    @patch("app.tasks.autonomous.review_modules.actions.log_task_event")
    @patch("app.storage.subtasks.create_subtask")
    def test_creates_subtask_with_fix_steps(
        self, mock_create: MagicMock, mock_log: MagicMock,
    ) -> None:
        review = {
            "recommendation": "step checks wrong file",
            "fix_steps": ["Check correct file path"],
        }
        handle_plan_defect("task-1", review)

        mock_create.assert_called_once()
        call_kwargs = mock_create.call_args
        assert call_kwargs.kwargs["subtask_id"] == "98.1"
        assert "Plan Defect Fix" in call_kwargs.kwargs["description"]

    @patch("app.tasks.autonomous.review_modules.actions.log_task_event")
    @patch("app.storage.subtasks.create_subtask")
    def test_creates_default_step_when_no_fix_steps(
        self, mock_create: MagicMock, mock_log: MagicMock,
    ) -> None:
        review = {"recommendation": "something wrong"}
        handle_plan_defect("task-1", review)

        mock_create.assert_called_once()
        steps = mock_create.call_args.kwargs["steps"]
        assert len(steps) == 1
        assert "Verify correct implementation" in steps[0]["description"]


# ---------------------------------------------------------------------------
# _handle_escalation
# ---------------------------------------------------------------------------


class TestHandleEscalation:
    """Tests for escalation handling."""

    @patch("app.tasks.autonomous.review_modules.routing.log_task_event")
    @patch("app.tasks.autonomous.review_modules.routing.auto_merge")
    @patch("app.tasks.autonomous.review_modules.routing.agent_configs")
    @patch("app.tasks.autonomous.review_modules.routing.supervisor_resolve_escalation")
    @patch("app.tasks.autonomous.review_modules.routing.task_store")
    def test_supervisor_approve_merges(
        self, mock_store: MagicMock, mock_resolve: MagicMock,
        mock_configs: MagicMock, mock_merge: MagicMock, mock_log: MagicMock,
    ) -> None:
        mock_store.get_task.return_value = {"project_id": "test-project"}
        mock_resolve.return_value = "approve"
        mock_configs.get_auto_merge_enabled.return_value = True
        mock_merge.return_value = {"status": "merged", "post_merge_valid": True}

        _handle_escalation("task-1", {"summary": "minor issue"})

        mock_merge.assert_called_once_with("task-1")
        mock_store.update_task_status.assert_not_called()

    @patch("app.tasks.autonomous.review_modules.routing.log_task_event")
    @patch("app.tasks.autonomous.review_modules.routing.create_fix_subtask")
    @patch("app.tasks.autonomous.review_modules.routing.supervisor_resolve_escalation")
    @patch("app.tasks.autonomous.review_modules.routing.task_store")
    def test_supervisor_fix_creates_subtask(
        self, mock_store: MagicMock, mock_resolve: MagicMock,
        mock_fix: MagicMock, mock_log: MagicMock,
    ) -> None:
        mock_store.get_task.return_value = {"project_id": "test-project"}
        mock_resolve.return_value = "fix"

        _handle_escalation("task-1", {"summary": "needs work"})

        mock_fix.assert_called_once()
        mock_store.update_task_status.assert_called_with("task-1", "running")

    @patch("app.tasks.autonomous.review_modules.routing.log_task_event")
    @patch("app.tasks.autonomous.review_modules.routing.supervisor_resolve_escalation")
    @patch("app.tasks.autonomous.review_modules.routing.task_store")
    def test_supervisor_block_sets_blocked_status(
        self, mock_store: MagicMock, mock_resolve: MagicMock,
        mock_log: MagicMock,
    ) -> None:
        mock_store.get_task.return_value = {"project_id": "test-project"}
        mock_resolve.return_value = "block"

        _handle_escalation("task-1", {"summary": "critical issue"})

        mock_store.update_task_status.assert_called_once_with("task-1", "blocked")
