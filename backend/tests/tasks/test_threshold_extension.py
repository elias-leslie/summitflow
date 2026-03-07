"""Tests for threshold autonomy and supervisor-gated extensions.

Covers:
- detect_progress(): progress detection from step results, git diff, defected steps
- request_extension(): supervisor LLM call for extension approval
- Heal loop extension: run_self_healing_loop extension behavior
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

from app.workflows._model_constants import DEFAULT_PROJECT_ID


class TestDetectProgress:
    """detect_progress returns evidence dict when agent made measurable progress."""

    def test_returns_none_when_no_progress(self, tmp_path: Path) -> None:
        from app.tasks.autonomous.exec_modules.agent_routing import detect_progress

        step_results = [
            {"step_number": 1, "passed": False, "output": "error", "reason": "failed"},
        ]
        steps: list[dict[str, Any]] = [{"step_number": 1, "status": "pending"}]

        with patch("app.tasks.autonomous.exec_modules.agent_routing.subprocess") as mock_sub:
            mock_result = MagicMock()
            mock_result.stdout = ""
            mock_sub.run.return_value = mock_result
            result = detect_progress("sub-1", steps, step_results, str(tmp_path))

        assert result is None

    def test_detects_passed_steps(self, tmp_path: Path) -> None:
        from app.tasks.autonomous.exec_modules.agent_routing import detect_progress

        step_results = [
            {"step_number": 1, "passed": True, "output": "ok"},
            {"step_number": 2, "passed": False, "output": "error", "reason": "failed"},
        ]
        steps: list[dict[str, Any]] = []

        with patch("app.tasks.autonomous.exec_modules.agent_routing.subprocess") as mock_sub:
            mock_result = MagicMock()
            mock_result.stdout = ""
            mock_sub.run.return_value = mock_result
            result = detect_progress("sub-1", steps, step_results, str(tmp_path))

        assert result is not None
        assert result["steps_passed"] == "1/2"

    def test_detects_code_changes(self, tmp_path: Path) -> None:
        from app.tasks.autonomous.exec_modules.agent_routing import detect_progress

        step_results = [
            {"step_number": 1, "passed": False, "output": "error", "reason": "failed"},
        ]
        steps: list[dict[str, Any]] = []

        with patch("app.tasks.autonomous.exec_modules.agent_routing.subprocess") as mock_sub:
            mock_result = MagicMock()
            mock_result.stdout = " 3 files changed, 50 insertions(+), 10 deletions(-)"
            mock_sub.run.return_value = mock_result
            result = detect_progress("sub-1", steps, step_results, str(tmp_path))

        assert result is not None
        assert result["has_code_changes"] is True
        assert "3 files changed" in result["diff_summary"]

    def test_detects_defected_steps(self, tmp_path: Path) -> None:
        from app.tasks.autonomous.exec_modules.agent_routing import detect_progress

        step_results = [
            {"step_number": 1, "passed": False, "output": "error", "reason": "failed"},
        ]
        steps = [
            {"step_number": 1, "status": "plan_defect"},
            {"step_number": 2, "status": "pending"},
        ]

        with patch("app.tasks.autonomous.exec_modules.agent_routing.subprocess") as mock_sub:
            mock_result = MagicMock()
            mock_result.stdout = ""
            mock_sub.run.return_value = mock_result
            result = detect_progress("sub-1", steps, step_results, str(tmp_path))

        assert result is not None
        assert result["adjusted_steps"] == 1

    def test_handles_subprocess_timeout(self, tmp_path: Path) -> None:
        """Git diff timeout should not crash, just skip that evidence."""
        import subprocess as real_subprocess

        from app.tasks.autonomous.exec_modules.agent_routing import detect_progress

        step_results = [
            {"step_number": 1, "passed": True, "output": "ok"},
        ]
        steps: list[dict[str, Any]] = []

        with patch("app.tasks.autonomous.exec_modules.agent_routing.subprocess") as mock_sub:
            mock_sub.run.side_effect = real_subprocess.TimeoutExpired("git", 10)
            mock_sub.TimeoutExpired = real_subprocess.TimeoutExpired
            result = detect_progress("sub-1", steps, step_results, str(tmp_path))

        assert result is not None
        assert result["steps_passed"] == "1/1"
        assert "has_code_changes" not in result

    def test_combines_all_evidence(self, tmp_path: Path) -> None:
        from app.tasks.autonomous.exec_modules.agent_routing import detect_progress

        step_results = [
            {"step_number": 1, "passed": True, "output": "ok"},
            {"step_number": 2, "passed": False, "output": "error", "reason": "failed"},
        ]
        steps = [
            {"step_number": 1, "status": "plan_defect"},
        ]

        with patch("app.tasks.autonomous.exec_modules.agent_routing.subprocess") as mock_sub:
            mock_result = MagicMock()
            mock_result.stdout = " 1 file changed"
            mock_sub.run.return_value = mock_result
            result = detect_progress("sub-1", steps, step_results, str(tmp_path))

        assert result is not None
        assert result["steps_passed"] == "1/2"
        assert result["has_code_changes"] is True
        assert result["adjusted_steps"] == 1


class TestRequestExtension:
    """request_extension asks supervisor LLM for more attempts."""

    @patch("app.tasks.autonomous.exec_modules.agent_routing.log_task_event")
    @patch("app.tasks.autonomous.exec_modules.agent_routing.get_sync_client")
    def test_approved_returns_true_with_guidance(
        self,
        mock_client_factory: MagicMock,
        mock_log_event: MagicMock,
    ) -> None:
        from app.tasks.autonomous.exec_modules.agent_routing import request_extension

        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.content = "APPROVED. Try using a different approach to reduce line count."
        mock_client.complete.return_value = mock_response
        mock_client_factory.return_value = mock_client

        step_results = [
            {"step_number": 1, "passed": False, "reason": "threshold exceeded"},
        ]
        progress = {"steps_passed": "2/3", "has_code_changes": True}

        approved, guidance = request_extension(
            "task-1", "1.1", step_results, progress, project_id="test-project",
        )

        assert approved is True
        assert guidance is not None
        assert "APPROVED" in guidance
        mock_client.complete.assert_called_once()
        call_kwargs = mock_client.complete.call_args
        assert call_kwargs.kwargs["agent_slug"] == "supervisor"

    @patch("app.tasks.autonomous.exec_modules.agent_routing.log_task_event")
    @patch("app.tasks.autonomous.exec_modules.agent_routing.get_sync_client")
    def test_denied_returns_false_no_guidance(
        self,
        mock_client_factory: MagicMock,
        mock_log_event: MagicMock,
    ) -> None:
        from app.tasks.autonomous.exec_modules.agent_routing import request_extension

        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.content = "DENIED. No meaningful progress detected."
        mock_client.complete.return_value = mock_response
        mock_client_factory.return_value = mock_client

        step_results = [
            {"step_number": 1, "passed": False, "reason": "failed"},
        ]
        progress = {"has_code_changes": True}

        approved, guidance = request_extension(
            "task-1", "1.1", step_results, progress, project_id="test-project",
        )

        assert approved is False
        assert guidance is None

    @patch("app.tasks.autonomous.exec_modules.agent_routing.log_task_event")
    @patch("app.tasks.autonomous.exec_modules.agent_routing.get_sync_client")
    def test_exception_defaults_to_approved(
        self,
        mock_client_factory: MagicMock,
        mock_log_event: MagicMock,
    ) -> None:
        """On exception, autonomous-first policy defaults to APPROVED."""
        from app.tasks.autonomous.exec_modules.agent_routing import request_extension

        mock_client = MagicMock()
        mock_client.complete.side_effect = ConnectionError("Agent Hub down")
        mock_client_factory.return_value = mock_client

        step_results = [{"step_number": 1, "passed": False, "reason": "failed"}]
        progress = {"steps_passed": "1/2"}

        approved, guidance = request_extension(
            "task-1", "1.1", step_results, progress, project_id="test-project",
        )

        assert approved is True
        assert guidance is None

    @patch("app.tasks.autonomous.exec_modules.agent_routing.log_task_event")
    @patch("app.tasks.autonomous.exec_modules.agent_routing.get_sync_client")
    def test_logs_task_event_on_decision(
        self,
        mock_client_factory: MagicMock,
        mock_log_event: MagicMock,
    ) -> None:
        from app.tasks.autonomous.exec_modules.agent_routing import request_extension

        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.content = "APPROVED. Use st step defect to relax the threshold."
        mock_client.complete.return_value = mock_response
        mock_client_factory.return_value = mock_client

        request_extension(
            "task-1", "1.1",
            [{"step_number": 1, "passed": False, "reason": "failed"}],
            {"steps_passed": "1/2"},
            project_id="test-project",
        )

        mock_log_event.assert_called_once()
        logged_msg = mock_log_event.call_args[0][1]
        assert "approved" in logged_msg.lower()

    @patch("app.tasks.autonomous.exec_modules.agent_routing.log_task_event")
    @patch("app.tasks.autonomous.exec_modules.agent_routing.task_store")
    @patch("app.tasks.autonomous.exec_modules.agent_routing.get_sync_client")
    def test_uses_task_project_when_project_id_not_passed(
        self,
        mock_client_factory: MagicMock,
        mock_task_store: MagicMock,
        mock_log_event: MagicMock,
    ) -> None:
        from app.tasks.autonomous.exec_modules.agent_routing import request_extension

        mock_task_store.get_task.return_value = {"id": "task-1", "project_id": "agent-hub"}
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.content = "APPROVED. Try a different approach."
        mock_client.complete.return_value = mock_response
        mock_client_factory.return_value = mock_client

        approved, guidance = request_extension(
            "task-1",
            "1.1",
            [{"step_number": 1, "passed": False, "reason": "failed"}],
            {"steps_passed": "1/2"},
        )

        assert approved is True
        assert guidance is not None
        assert mock_client.complete.call_args.kwargs["project_id"] == "agent-hub"

    @patch("app.tasks.autonomous.exec_modules.agent_routing.log_task_event")
    @patch("app.tasks.autonomous.exec_modules.agent_routing.task_store")
    @patch("app.tasks.autonomous.exec_modules.agent_routing.get_sync_client")
    def test_falls_back_to_default_project_when_task_missing(
        self,
        mock_client_factory: MagicMock,
        mock_task_store: MagicMock,
        mock_log_event: MagicMock,
    ) -> None:
        from app.tasks.autonomous.exec_modules.agent_routing import request_extension

        mock_task_store.get_task.return_value = None
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.content = "APPROVED. Continue."
        mock_client.complete.return_value = mock_response
        mock_client_factory.return_value = mock_client

        request_extension(
            "task-1",
            "1.1",
            [{"step_number": 1, "passed": False, "reason": "failed"}],
            {"steps_passed": "1/2"},
        )

        assert mock_client.complete.call_args.kwargs["project_id"] == DEFAULT_PROJECT_ID


class TestHealLoopExtension:
    """Heal loop grants extension when supervisor approves and progress detected."""

    @patch("app.tasks.autonomous.exec_modules.retry_loop.execute_fix_attempt")
    @patch("app.tasks.autonomous.exec_modules.retry_loop.determine_fix_prompt")
    @patch("app.tasks.autonomous.exec_modules.retry_loop.handle_infrastructure_failures")
    @patch("app.tasks.autonomous.exec_modules.retry_loop.check_and_request_extension")
    @patch("app.tasks.autonomous.exec_modules.retry_loop.run_execution_quality_check")
    @patch("app.tasks.autonomous.exec_modules.retry_loop.check_worktree_health")
    @patch("app.tasks.autonomous.exec_modules.retry_loop.get_steps_for_subtask")
    @patch("app.tasks.autonomous.exec_modules.retry_loop.assert_task_runnable")
    @patch("app.tasks.autonomous.exec_modules.retry_loop.agent_configs")
    def test_extension_granted_adds_attempts(
        self,
        mock_agent_configs: MagicMock,
        mock_assert_task_runnable: MagicMock,
        mock_get_steps: MagicMock,
        mock_worktree_health: MagicMock,
        mock_verify: MagicMock,
        mock_check_ext: MagicMock,
        mock_handle_infra: MagicMock,
        mock_determine_fix: MagicMock,
        mock_execute_fix: MagicMock,
    ) -> None:
        """When extension is approved, agent gets more attempts and eventually passes."""
        from app.constants import SELF_HEAL_MAX_ATTEMPTS, SUPERVISOR_GUIDED_MAX_ATTEMPTS
        from app.tasks.autonomous.exec_modules.retry_loop import run_self_healing_loop

        # Configure agent_configs to return 0 (fall back to constants)
        mock_agent_configs.get_max_self_fix_attempts.return_value = 0
        mock_agent_configs.get_max_supervisor_attempts.return_value = 0

        mock_worktree_health.return_value = True
        mock_get_steps.return_value = [
            {"step_number": 1, "description": "test"},
        ]

        total_normal = SELF_HEAL_MAX_ATTEMPTS + SUPERVISOR_GUIDED_MAX_ATTEMPTS
        fail_result = [{"step_number": 1, "passed": False, "output": "error", "reason": "threshold", "returncode": 1}]
        pass_result = [{"step_number": 1, "passed": True, "output": "ok", "reason": "", "returncode": 0}]

        # Fail for all normal attempts + initial verify, then pass on first extension attempt
        verify_results = [(False, fail_result)] * (total_normal + 1) + [(True, pass_result)]
        mock_verify.side_effect = verify_results

        # handle_infrastructure_failures just passes through the failed steps
        mock_handle_infra.side_effect = lambda failed, sub_id, task_id, proj_id: failed

        # determine_fix_prompt returns a prompt and no guidance
        mock_determine_fix.return_value = ("fix prompt", None)

        # execute_fix_attempt returns content and session_id
        mock_execute_fix.return_value = ("fixed", "session-1")

        # Extension approved on first call
        mock_check_ext.return_value = (True, 1, "Try adjusting the threshold with st step defect")

        subtask = {
            "id": "sub-1",
            "subtask_id": "1.1",
            "description": "test subtask",
            "steps_from_table": [{"step_number": 1, "description": "test"}],
        }

        steps = [{"step_number": 1, "description": "test"}]

        all_passed, _step_results, _self_fix, _supervisor_guided, extensions_granted, _session_id = (
            run_self_healing_loop(
                task_id="task-1",
                subtask_id="sub-1",
                subtask_short_id="1.1",
                subtask=subtask,
                steps=steps,
                project_path="/tmp/test-worktree",
                project_id="test-project",
                agent_slug="coder",
                agent_session_id="session-0",
                initial_response_content="initial response",
            )
        )

        assert all_passed is True
        assert extensions_granted == 1
        mock_check_ext.assert_called_once()

    @patch("app.tasks.autonomous.exec_modules.retry_loop.execute_fix_attempt")
    @patch("app.tasks.autonomous.exec_modules.retry_loop.determine_fix_prompt")
    @patch("app.tasks.autonomous.exec_modules.retry_loop.handle_infrastructure_failures")
    @patch("app.tasks.autonomous.exec_modules.retry_loop.check_and_request_extension")
    @patch("app.tasks.autonomous.exec_modules.retry_loop.run_execution_quality_check")
    @patch("app.tasks.autonomous.exec_modules.retry_loop.check_worktree_health")
    @patch("app.tasks.autonomous.exec_modules.retry_loop.get_steps_for_subtask")
    @patch("app.tasks.autonomous.exec_modules.retry_loop.assert_task_runnable")
    @patch("app.tasks.autonomous.exec_modules.retry_loop.agent_configs")
    def test_extension_denied_fails_subtask(
        self,
        mock_agent_configs: MagicMock,
        mock_assert_task_runnable: MagicMock,
        mock_get_steps: MagicMock,
        mock_worktree_health: MagicMock,
        mock_verify: MagicMock,
        mock_check_ext: MagicMock,
        mock_handle_infra: MagicMock,
        mock_determine_fix: MagicMock,
        mock_execute_fix: MagicMock,
    ) -> None:
        """When extension is denied, subtask fails normally."""
        from app.tasks.autonomous.exec_modules.retry_loop import run_self_healing_loop

        mock_agent_configs.get_max_self_fix_attempts.return_value = 0
        mock_agent_configs.get_max_supervisor_attempts.return_value = 0

        mock_worktree_health.return_value = True
        mock_get_steps.return_value = [
            {"step_number": 1, "description": "test"},
        ]

        fail_result = [{"step_number": 1, "passed": False, "output": "error", "reason": "threshold", "returncode": 1}]
        mock_verify.return_value = (False, fail_result)

        mock_handle_infra.side_effect = lambda failed, sub_id, task_id, proj_id: failed
        mock_determine_fix.return_value = ("fix prompt", None)
        mock_execute_fix.return_value = ("tried", "session-1")

        # Extension denied
        mock_check_ext.return_value = (False, 0, None)

        subtask = {
            "id": "sub-1",
            "subtask_id": "1.1",
            "description": "test subtask",
            "steps_from_table": [{"step_number": 1, "description": "test"}],
        }
        steps = [{"step_number": 1, "description": "test"}]

        all_passed, _step_results, _self_fix, _supervisor_guided, extensions_granted, _session_id = (
            run_self_healing_loop(
                task_id="task-1",
                subtask_id="sub-1",
                subtask_short_id="1.1",
                subtask=subtask,
                steps=steps,
                project_path="/tmp/test-worktree",
                project_id="test-project",
                agent_slug="coder",
                agent_session_id="session-0",
                initial_response_content="initial response",
            )
        )

        assert all_passed is False
        assert extensions_granted == 0
        mock_check_ext.assert_called_once()

    @patch("app.tasks.autonomous.exec_modules.retry_loop.execute_fix_attempt")
    @patch("app.tasks.autonomous.exec_modules.retry_loop.determine_fix_prompt")
    @patch("app.tasks.autonomous.exec_modules.retry_loop.handle_infrastructure_failures")
    @patch("app.tasks.autonomous.exec_modules.retry_loop.check_and_request_extension")
    @patch("app.tasks.autonomous.exec_modules.retry_loop.run_execution_quality_check")
    @patch("app.tasks.autonomous.exec_modules.retry_loop.check_worktree_health")
    @patch("app.tasks.autonomous.exec_modules.retry_loop.get_steps_for_subtask")
    @patch("app.tasks.autonomous.exec_modules.retry_loop.assert_task_runnable")
    @patch("app.tasks.autonomous.exec_modules.retry_loop.agent_configs")
    def test_no_progress_skips_extension_request(
        self,
        mock_agent_configs: MagicMock,
        mock_assert_task_runnable: MagicMock,
        mock_get_steps: MagicMock,
        mock_worktree_health: MagicMock,
        mock_verify: MagicMock,
        mock_check_ext: MagicMock,
        mock_handle_infra: MagicMock,
        mock_determine_fix: MagicMock,
        mock_execute_fix: MagicMock,
    ) -> None:
        """When no progress detected, check_and_request_extension returns False
        and run_self_healing_loop breaks out of the loop."""
        from app.tasks.autonomous.exec_modules.retry_loop import run_self_healing_loop

        mock_agent_configs.get_max_self_fix_attempts.return_value = 0
        mock_agent_configs.get_max_supervisor_attempts.return_value = 0

        mock_worktree_health.return_value = True
        mock_get_steps.return_value = [
            {"step_number": 1, "description": "test"},
        ]

        fail_result = [{"step_number": 1, "passed": False, "output": "error", "reason": "failed", "returncode": 1}]
        mock_verify.return_value = (False, fail_result)

        mock_handle_infra.side_effect = lambda failed, sub_id, task_id, proj_id: failed
        mock_determine_fix.return_value = ("fix prompt", None)
        mock_execute_fix.return_value = ("tried", "session-1")

        # No progress: check_and_request_extension returns not approved
        mock_check_ext.return_value = (False, 0, None)

        subtask = {
            "id": "sub-1",
            "subtask_id": "1.1",
            "description": "test subtask",
            "steps_from_table": [{"step_number": 1, "description": "test"}],
        }
        steps = [{"step_number": 1, "description": "test"}]

        all_passed, _step_results, _self_fix, _supervisor_guided, extensions_granted, _session_id = (
            run_self_healing_loop(
                task_id="task-1",
                subtask_id="sub-1",
                subtask_short_id="1.1",
                subtask=subtask,
                steps=steps,
                project_path="/tmp/test-worktree",
                project_id="test-project",
                agent_slug="coder",
                agent_session_id="session-0",
                initial_response_content="initial response",
            )
        )

        assert all_passed is False
        assert extensions_granted == 0
        # check_and_request_extension is called (it internally handles the no-progress case)
        mock_check_ext.assert_called_once()
