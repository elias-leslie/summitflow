"""Tests for threshold autonomy and supervisor-gated extensions.

Covers:
- _detect_progress(): progress detection from step results, git diff, defected steps
- _request_extension(): supervisor LLM call for extension approval
- Heal loop extension: for→while conversion, extension_granted flag, max 1 extension
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch


class TestDetectProgress:
    """_detect_progress returns evidence dict when agent made measurable progress."""

    def test_returns_none_when_no_progress(self, tmp_path: Path) -> None:
        from app.tasks.autonomous.execution import _detect_progress

        step_results = [
            {"step_number": 1, "passed": False, "output": "error", "reason": "failed"},
        ]
        steps: list[dict[str, Any]] = [{"step_number": 1, "status": "pending"}]

        with patch("app.tasks.autonomous.execution.subprocess") as mock_sub:
            mock_result = MagicMock()
            mock_result.stdout = ""
            mock_sub.run.return_value = mock_result
            result = _detect_progress("sub-1", steps, step_results, str(tmp_path))

        assert result is None

    def test_detects_passed_steps(self, tmp_path: Path) -> None:
        from app.tasks.autonomous.execution import _detect_progress

        step_results = [
            {"step_number": 1, "passed": True, "output": "ok"},
            {"step_number": 2, "passed": False, "output": "error", "reason": "failed"},
        ]
        steps: list[dict[str, Any]] = []

        with patch("app.tasks.autonomous.execution.subprocess") as mock_sub:
            mock_result = MagicMock()
            mock_result.stdout = ""
            mock_sub.run.return_value = mock_result
            result = _detect_progress("sub-1", steps, step_results, str(tmp_path))

        assert result is not None
        assert result["steps_passed"] == "1/2"

    def test_detects_code_changes(self, tmp_path: Path) -> None:
        from app.tasks.autonomous.execution import _detect_progress

        step_results = [
            {"step_number": 1, "passed": False, "output": "error", "reason": "failed"},
        ]
        steps: list[dict[str, Any]] = []

        with patch("app.tasks.autonomous.execution.subprocess") as mock_sub:
            mock_result = MagicMock()
            mock_result.stdout = " 3 files changed, 50 insertions(+), 10 deletions(-)"
            mock_sub.run.return_value = mock_result
            result = _detect_progress("sub-1", steps, step_results, str(tmp_path))

        assert result is not None
        assert result["has_code_changes"] is True
        assert "3 files changed" in result["diff_summary"]

    def test_detects_defected_steps(self, tmp_path: Path) -> None:
        from app.tasks.autonomous.execution import _detect_progress

        step_results = [
            {"step_number": 1, "passed": False, "output": "error", "reason": "failed"},
        ]
        steps = [
            {"step_number": 1, "status": "plan_defect"},
            {"step_number": 2, "status": "pending"},
        ]

        with patch("app.tasks.autonomous.execution.subprocess") as mock_sub:
            mock_result = MagicMock()
            mock_result.stdout = ""
            mock_sub.run.return_value = mock_result
            result = _detect_progress("sub-1", steps, step_results, str(tmp_path))

        assert result is not None
        assert result["adjusted_steps"] == 1

    def test_handles_subprocess_timeout(self, tmp_path: Path) -> None:
        """Git diff timeout should not crash, just skip that evidence."""
        import subprocess as real_subprocess

        from app.tasks.autonomous.execution import _detect_progress

        step_results = [
            {"step_number": 1, "passed": True, "output": "ok"},
        ]
        steps: list[dict[str, Any]] = []

        with patch("app.tasks.autonomous.execution.subprocess") as mock_sub:
            mock_sub.run.side_effect = real_subprocess.TimeoutExpired("git", 10)
            mock_sub.TimeoutExpired = real_subprocess.TimeoutExpired
            result = _detect_progress("sub-1", steps, step_results, str(tmp_path))

        assert result is not None
        assert result["steps_passed"] == "1/1"
        assert "has_code_changes" not in result

    def test_combines_all_evidence(self, tmp_path: Path) -> None:
        from app.tasks.autonomous.execution import _detect_progress

        step_results = [
            {"step_number": 1, "passed": True, "output": "ok"},
            {"step_number": 2, "passed": False, "output": "error", "reason": "failed"},
        ]
        steps = [
            {"step_number": 1, "status": "plan_defect"},
        ]

        with patch("app.tasks.autonomous.execution.subprocess") as mock_sub:
            mock_result = MagicMock()
            mock_result.stdout = " 1 file changed"
            mock_sub.run.return_value = mock_result
            result = _detect_progress("sub-1", steps, step_results, str(tmp_path))

        assert result is not None
        assert result["steps_passed"] == "1/2"
        assert result["has_code_changes"] is True
        assert result["adjusted_steps"] == 1


class TestRequestExtension:
    """_request_extension asks supervisor LLM for more attempts."""

    @patch("app.tasks.autonomous.execution.log_task_event")
    @patch("app.tasks.autonomous.execution.get_sync_client")
    def test_approved_returns_true_with_guidance(
        self,
        mock_client_factory: MagicMock,
        mock_log_event: MagicMock,
    ) -> None:
        from app.tasks.autonomous.execution import _request_extension

        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.content = "APPROVED. Try using a different approach to reduce line count."
        mock_client.complete.return_value = mock_response
        mock_client_factory.return_value = mock_client

        step_results = [
            {"step_number": 1, "passed": False, "reason": "threshold exceeded"},
        ]
        progress = {"steps_passed": "2/3", "has_code_changes": True}

        approved, guidance = _request_extension(
            "task-1", "1.1", step_results, progress, project_id="test-project",
        )

        assert approved is True
        assert guidance is not None
        assert "APPROVED" in guidance
        mock_client.complete.assert_called_once()
        call_kwargs = mock_client.complete.call_args
        assert call_kwargs.kwargs["agent_slug"] == "supervisor"

    @patch("app.tasks.autonomous.execution.log_task_event")
    @patch("app.tasks.autonomous.execution.get_sync_client")
    def test_denied_returns_false_no_guidance(
        self,
        mock_client_factory: MagicMock,
        mock_log_event: MagicMock,
    ) -> None:
        from app.tasks.autonomous.execution import _request_extension

        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.content = "DENIED. No meaningful progress detected."
        mock_client.complete.return_value = mock_response
        mock_client_factory.return_value = mock_client

        step_results = [
            {"step_number": 1, "passed": False, "reason": "failed"},
        ]
        progress = {"has_code_changes": True}

        approved, guidance = _request_extension(
            "task-1", "1.1", step_results, progress, project_id="test-project",
        )

        assert approved is False
        assert guidance is None

    @patch("app.tasks.autonomous.execution.log_task_event")
    @patch("app.tasks.autonomous.execution.get_sync_client")
    def test_exception_returns_false(
        self,
        mock_client_factory: MagicMock,
        mock_log_event: MagicMock,
    ) -> None:
        from app.tasks.autonomous.execution import _request_extension

        mock_client = MagicMock()
        mock_client.complete.side_effect = ConnectionError("Agent Hub down")
        mock_client_factory.return_value = mock_client

        step_results = [{"step_number": 1, "passed": False, "reason": "failed"}]
        progress = {"steps_passed": "1/2"}

        approved, guidance = _request_extension(
            "task-1", "1.1", step_results, progress, project_id="test-project",
        )

        assert approved is False
        assert guidance is None

    @patch("app.tasks.autonomous.execution.log_task_event")
    @patch("app.tasks.autonomous.execution.get_sync_client")
    def test_logs_task_event_on_decision(
        self,
        mock_client_factory: MagicMock,
        mock_log_event: MagicMock,
    ) -> None:
        from app.tasks.autonomous.execution import _request_extension

        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.content = "APPROVED. Use st step defect to relax the threshold."
        mock_client.complete.return_value = mock_response
        mock_client_factory.return_value = mock_client

        _request_extension(
            "task-1", "1.1",
            [{"step_number": 1, "passed": False, "reason": "failed"}],
            {"steps_passed": "1/2"},
            project_id="test-project",
        )

        mock_log_event.assert_called_once()
        logged_msg = mock_log_event.call_args[0][1]
        assert "approved" in logged_msg.lower()


class TestHealLoopExtension:
    """Heal loop grants extension when supervisor approves and progress detected."""

    @patch("app.tasks.autonomous.execution._emit_log")
    @patch("app.tasks.autonomous.execution._emit_progress")
    @patch("app.tasks.autonomous.execution._emit_progress_log")
    @patch("app.tasks.autonomous.execution.run_smoke_tests")
    @patch("app.tasks.autonomous.execution.get_steps_for_subtask")
    @patch("app.tasks.autonomous.execution._verify_steps")
    @patch("app.tasks.autonomous.execution._build_fix_prompt")
    @patch("app.tasks.autonomous.execution._check_worktree_health")
    @patch("app.tasks.autonomous.execution._get_project_path")
    @patch("app.tasks.autonomous.execution._build_subtask_prompt")
    @patch("app.tasks.autonomous.execution.get_sync_client")
    @patch("app.tasks.autonomous.execution._has_uncommitted_changes")
    @patch("app.tasks.autonomous.execution._get_prompt_template")
    @patch("app.tasks.autonomous.execution.get_handoff_context")
    @patch("app.tasks.autonomous.execution.get_task_spirit")
    @patch("app.tasks.autonomous.execution._detect_progress")
    @patch("app.tasks.autonomous.execution._request_extension")
    @patch("app.tasks.autonomous.execution.acknowledge_no_citations", create=True)
    def test_extension_granted_adds_attempts(
        self,
        mock_ack_citations: MagicMock,
        mock_request_ext: MagicMock,
        mock_detect: MagicMock,
        mock_spirit: MagicMock,
        mock_handoff: MagicMock,
        mock_template: MagicMock,
        mock_uncommitted: MagicMock,
        mock_client_factory: MagicMock,
        mock_build_prompt: MagicMock,
        mock_project_path: MagicMock,
        mock_worktree_health: MagicMock,
        mock_build_fix: MagicMock,
        mock_verify: MagicMock,
        mock_get_steps: MagicMock,
        mock_smoke: MagicMock,
        mock_progress_log: MagicMock,
        mock_progress: MagicMock,
        mock_log: MagicMock,
    ) -> None:
        """When extension is approved, agent gets more attempts and eventually passes."""
        from app.constants import SELF_HEAL_MAX_ATTEMPTS, SUPERVISOR_GUIDED_MAX_ATTEMPTS
        from app.tasks.autonomous.execution import _execute_subtask

        mock_project_path.return_value = "/tmp/test-worktree"
        mock_worktree_health.return_value = True
        mock_build_prompt.return_value = "test prompt"
        mock_template.return_value = "fix {failures_block}"
        mock_build_fix.return_value = "fix prompt"
        mock_uncommitted.return_value = False
        mock_spirit.return_value = {"objective": "test", "spirit_anti": ""}
        mock_handoff.return_value = {}

        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.content = "fixed"
        mock_response.session_id = "session-1"
        mock_response.progress_log = []
        mock_response.context_usage = None
        mock_response.cited_uuids = []
        mock_client.complete.return_value = mock_response
        mock_client_factory.return_value = mock_client

        total_normal = SELF_HEAL_MAX_ATTEMPTS + SUPERVISOR_GUIDED_MAX_ATTEMPTS
        fail_result = [{"step_number": 1, "passed": False, "output": "error", "reason": "threshold", "returncode": 1}]
        pass_result = [{"step_number": 1, "passed": True, "output": "ok", "reason": "", "returncode": 0}]

        # Fail for all normal attempts + 1 initial, then pass on extension attempt
        verify_results = [fail_result] * (total_normal + 1) + [pass_result]
        mock_verify.side_effect = verify_results

        mock_get_steps.return_value = [
            {"step_number": 1, "description": "test", "verify_command": "echo ok"},
        ]

        mock_detect.return_value = {"steps_passed": "0/1", "has_code_changes": True}
        mock_request_ext.return_value = (True, "Try adjusting the threshold with st step defect")

        mock_smoke_result = MagicMock()
        mock_smoke_result.passed = True
        mock_smoke_result.files_tested = []
        mock_smoke.return_value = mock_smoke_result

        subtask = {
            "id": "sub-1",
            "subtask_id": "1.1",
            "description": "test subtask",
            "steps_from_table": [{"step_number": 1, "description": "test", "verify_command": "echo ok"}],
        }

        with patch("app.tasks.autonomous.execution.update_subtask_passes"), \
             patch("app.tasks.autonomous.execution.insert_subtask_summary"), \
             patch("app.tasks.autonomous.execution.get_supervisor_guidance_sync", return_value="guidance"), \
             patch("app.storage.tasks.core.add_agent_hub_session"):
            result = _execute_subtask("task-1", subtask, "test-project", {})

        assert result["status"] == "passed"
        assert result["extensions_granted"] == 1
        mock_detect.assert_called_once()
        mock_request_ext.assert_called_once()

    @patch("app.tasks.autonomous.execution._emit_log")
    @patch("app.tasks.autonomous.execution._emit_progress")
    @patch("app.tasks.autonomous.execution._emit_progress_log")
    @patch("app.tasks.autonomous.execution.run_smoke_tests")
    @patch("app.tasks.autonomous.execution.get_steps_for_subtask")
    @patch("app.tasks.autonomous.execution._verify_steps")
    @patch("app.tasks.autonomous.execution._build_fix_prompt")
    @patch("app.tasks.autonomous.execution._check_worktree_health")
    @patch("app.tasks.autonomous.execution._get_project_path")
    @patch("app.tasks.autonomous.execution._build_subtask_prompt")
    @patch("app.tasks.autonomous.execution.get_sync_client")
    @patch("app.tasks.autonomous.execution._has_uncommitted_changes")
    @patch("app.tasks.autonomous.execution._get_prompt_template")
    @patch("app.tasks.autonomous.execution.get_handoff_context")
    @patch("app.tasks.autonomous.execution.get_task_spirit")
    @patch("app.tasks.autonomous.execution._detect_progress")
    @patch("app.tasks.autonomous.execution._request_extension")
    @patch("app.tasks.autonomous.execution.acknowledge_no_citations", create=True)
    def test_extension_denied_fails_subtask(
        self,
        mock_ack_citations: MagicMock,
        mock_request_ext: MagicMock,
        mock_detect: MagicMock,
        mock_spirit: MagicMock,
        mock_handoff: MagicMock,
        mock_template: MagicMock,
        mock_uncommitted: MagicMock,
        mock_client_factory: MagicMock,
        mock_build_prompt: MagicMock,
        mock_project_path: MagicMock,
        mock_worktree_health: MagicMock,
        mock_build_fix: MagicMock,
        mock_verify: MagicMock,
        mock_get_steps: MagicMock,
        mock_smoke: MagicMock,
        mock_progress_log: MagicMock,
        mock_progress: MagicMock,
        mock_log: MagicMock,
    ) -> None:
        """When extension is denied, subtask fails normally."""
        from app.tasks.autonomous.execution import _execute_subtask

        mock_project_path.return_value = "/tmp/test-worktree"
        mock_worktree_health.return_value = True
        mock_build_prompt.return_value = "test prompt"
        mock_template.return_value = "fix {failures_block}"
        mock_build_fix.return_value = "fix prompt"
        mock_uncommitted.return_value = False
        mock_spirit.return_value = {"objective": "test", "spirit_anti": ""}
        mock_handoff.return_value = {}

        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.content = "tried"
        mock_response.session_id = "session-1"
        mock_response.progress_log = []
        mock_response.context_usage = None
        mock_response.cited_uuids = []
        mock_client.complete.return_value = mock_response
        mock_client_factory.return_value = mock_client

        fail_result = [{"step_number": 1, "passed": False, "output": "error", "reason": "threshold", "returncode": 1}]

        mock_verify.return_value = fail_result

        mock_get_steps.return_value = [
            {"step_number": 1, "description": "test", "verify_command": "echo ok"},
        ]

        mock_detect.return_value = {"has_code_changes": True}
        mock_request_ext.return_value = (False, None)

        subtask = {
            "id": "sub-1",
            "subtask_id": "1.1",
            "description": "test subtask",
            "steps_from_table": [{"step_number": 1, "description": "test", "verify_command": "echo ok"}],
        }

        with patch("app.tasks.autonomous.execution.get_supervisor_guidance_sync", return_value="guidance"), \
             patch("app.storage.tasks.core.add_agent_hub_session"):
            result = _execute_subtask("task-1", subtask, "test-project", {})

        assert result["status"] == "failed"
        assert result["extensions_granted"] == 0
        mock_request_ext.assert_called_once()

    @patch("app.tasks.autonomous.execution._emit_log")
    @patch("app.tasks.autonomous.execution._emit_progress")
    @patch("app.tasks.autonomous.execution._emit_progress_log")
    @patch("app.tasks.autonomous.execution.run_smoke_tests")
    @patch("app.tasks.autonomous.execution.get_steps_for_subtask")
    @patch("app.tasks.autonomous.execution._verify_steps")
    @patch("app.tasks.autonomous.execution._build_fix_prompt")
    @patch("app.tasks.autonomous.execution._check_worktree_health")
    @patch("app.tasks.autonomous.execution._get_project_path")
    @patch("app.tasks.autonomous.execution._build_subtask_prompt")
    @patch("app.tasks.autonomous.execution.get_sync_client")
    @patch("app.tasks.autonomous.execution._has_uncommitted_changes")
    @patch("app.tasks.autonomous.execution._get_prompt_template")
    @patch("app.tasks.autonomous.execution.get_handoff_context")
    @patch("app.tasks.autonomous.execution.get_task_spirit")
    @patch("app.tasks.autonomous.execution._detect_progress")
    @patch("app.tasks.autonomous.execution.acknowledge_no_citations", create=True)
    def test_no_progress_skips_extension_request(
        self,
        mock_ack_citations: MagicMock,
        mock_detect: MagicMock,
        mock_spirit: MagicMock,
        mock_handoff: MagicMock,
        mock_template: MagicMock,
        mock_uncommitted: MagicMock,
        mock_client_factory: MagicMock,
        mock_build_prompt: MagicMock,
        mock_project_path: MagicMock,
        mock_worktree_health: MagicMock,
        mock_build_fix: MagicMock,
        mock_verify: MagicMock,
        mock_get_steps: MagicMock,
        mock_smoke: MagicMock,
        mock_progress_log: MagicMock,
        mock_progress: MagicMock,
        mock_log: MagicMock,
    ) -> None:
        """When no progress detected, extension is not even requested."""
        from app.tasks.autonomous.execution import _execute_subtask

        mock_project_path.return_value = "/tmp/test-worktree"
        mock_worktree_health.return_value = True
        mock_build_prompt.return_value = "test prompt"
        mock_template.return_value = "fix {failures_block}"
        mock_build_fix.return_value = "fix prompt"
        mock_uncommitted.return_value = False
        mock_spirit.return_value = {"objective": "test", "spirit_anti": ""}
        mock_handoff.return_value = {}

        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.content = "tried"
        mock_response.session_id = "session-1"
        mock_response.progress_log = []
        mock_response.context_usage = None
        mock_response.cited_uuids = []
        mock_client.complete.return_value = mock_response
        mock_client_factory.return_value = mock_client

        fail_result = [{"step_number": 1, "passed": False, "output": "error", "reason": "failed", "returncode": 1}]
        mock_verify.return_value = fail_result

        mock_get_steps.return_value = [
            {"step_number": 1, "description": "test", "verify_command": "echo ok"},
        ]

        mock_detect.return_value = None

        subtask = {
            "id": "sub-1",
            "subtask_id": "1.1",
            "description": "test subtask",
            "steps_from_table": [{"step_number": 1, "description": "test", "verify_command": "echo ok"}],
        }

        with patch("app.tasks.autonomous.execution.get_supervisor_guidance_sync", return_value="guidance"), \
             patch("app.tasks.autonomous.execution._request_extension") as mock_ext, \
             patch("app.storage.tasks.core.add_agent_hub_session"):
            result = _execute_subtask("task-1", subtask, "test-project", {})

        assert result["status"] == "failed"
        assert result["extensions_granted"] == 0
        mock_ext.assert_not_called()
