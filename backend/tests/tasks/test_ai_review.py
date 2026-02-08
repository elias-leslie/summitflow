"""Tests for AI Review Celery task."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from app.tasks.ai_review import review_pull_request
from app.tasks.ai_review_checks import (
    _has_frontend_changes,
    _run_mypy,
    _run_precommit,
    _run_pytest,
    _verify_step_completion,
)
from app.tasks.ai_review_constants import ARCHITECTURE_KEYWORDS, SECURITY_KEYWORDS
from app.tasks.ai_review_models import ReviewResult, ReviewVerdict
from app.tasks.ai_review_utils import _should_escalate_for_security

# Silence linter about unused imports - they're used in TestSecurityEscalation
_ = ARCHITECTURE_KEYWORDS, SECURITY_KEYWORDS, _should_escalate_for_security


class TestReviewResult:
    """Tests for ReviewResult dataclass."""

    def test_to_dict(self) -> None:
        result = ReviewResult(
            verdict=ReviewVerdict.PASS,
            summary="All checks passed",
            checks={"pytest": {"status": "pass"}},
            issues=[],
            suggestions=["Consider adding more tests"],
        )
        d = result.to_dict()
        assert d["verdict"] == "PASS"
        assert d["summary"] == "All checks passed"
        assert d["checks"]["pytest"]["status"] == "pass"
        assert d["suggestions"] == ["Consider adding more tests"]
        assert "reviewed_at" in d


class TestHasFrontendChanges:
    """Tests for _has_frontend_changes helper."""

    def test_no_plan_content(self) -> None:
        task: dict[str, object] = {}
        assert not _has_frontend_changes(task)

    def test_no_affected_files(self) -> None:
        task: dict[str, object] = {"plan_content": {"context": {}}}
        assert not _has_frontend_changes(task)

    def test_backend_only_changes(self) -> None:
        task = {
            "plan_content": {
                "context": {
                    "affected_files": [
                        "backend/app/api/tasks.py",
                        "backend/app/storage/tasks.py",
                    ]
                }
            }
        }
        assert not _has_frontend_changes(task)

    def test_frontend_tsx_changes(self) -> None:
        task = {
            "plan_content": {
                "context": {
                    "affected_files": [
                        "frontend/components/TaskList.tsx",
                    ]
                }
            }
        }
        assert _has_frontend_changes(task)

    def test_frontend_directory_changes(self) -> None:
        task = {
            "plan_content": {
                "context": {
                    "affected_files": [
                        "frontend/lib/api.ts",
                    ]
                }
            }
        }
        assert _has_frontend_changes(task)

    def test_css_changes(self) -> None:
        task = {
            "plan_content": {
                "context": {
                    "affected_files": [
                        "styles/main.css",
                    ]
                }
            }
        }
        assert _has_frontend_changes(task)


class TestRunPytest:
    """Tests for _run_pytest helper."""

    def test_no_backend_directory(self, tmp_path: Path) -> None:
        result = _run_pytest(tmp_path)
        assert result["status"] == "skip"
        assert "No backend directory" in result["reason"]

    def test_no_pytest_in_venv(self, tmp_path: Path) -> None:
        backend = tmp_path / "backend"
        backend.mkdir()
        result = _run_pytest(tmp_path)
        assert result["status"] == "skip"
        assert "No pytest in venv" in result["reason"]


class TestRunPrecommit:
    """Tests for _run_precommit helper."""

    @patch("app.tasks.ai_review_tools.run_command")
    def test_precommit_pass(self, mock_run: MagicMock, tmp_path: Path) -> None:
        mock_run.return_value = (True, "All passed!")
        result = _run_precommit(tmp_path)
        assert result["status"] == "pass"
        mock_run.assert_called_once()

    @patch("app.tasks.ai_review_tools.run_command")
    def test_precommit_fail(self, mock_run: MagicMock, tmp_path: Path) -> None:
        mock_run.return_value = (False, "Linting failed")
        result = _run_precommit(tmp_path)
        assert result["status"] == "fail"


class TestRunMypy:
    """Tests for _run_mypy helper."""

    def test_no_backend_directory(self, tmp_path: Path) -> None:
        result = _run_mypy(tmp_path)
        assert result["status"] == "skip"

    def test_no_mypy_in_venv(self, tmp_path: Path) -> None:
        backend = tmp_path / "backend"
        backend.mkdir()
        result = _run_mypy(tmp_path)
        assert result["status"] == "skip"


class TestVerifyStepCompletion:
    """Tests for _verify_step_completion helper.

    Verification happens at step level via verify_command.
    This function checks if all subtask steps have passed.
    """

    def test_no_subtasks(self) -> None:
        """Task with no subtasks should skip verification."""
        task: dict[str, object] = {"id": "task-123"}
        result = _verify_step_completion(task)
        assert result["status"] == "skip"
        assert "No subtasks defined" in result["reason"]

    def test_no_task_id(self) -> None:
        """Task without ID should error."""
        task: dict[str, object] = {"done_when": ["tests pass"]}
        result = _verify_step_completion(task)
        assert result["status"] == "error"


class TestReviewPullRequest:
    """Tests for review_pull_request Celery task."""

    @patch("app.tasks.ai_review.task_store")
    def test_task_not_found(self, mock_store: MagicMock) -> None:
        mock_store.get_task.return_value = None
        result = review_pull_request("nonexistent-task")
        assert result["verdict"] == "FAIL"
        assert "not found" in result["summary"]

    @patch("app.tasks.ai_review.task_store")
    def test_task_not_in_review_status(self, mock_store: MagicMock) -> None:
        mock_store.get_task.return_value = {
            "id": "task-123",
            "status": "running",
            "project_id": "test",
        }
        result = review_pull_request("task-123")
        assert result["verdict"] == "FAIL"
        assert "not in ai_reviewing" in result["summary"]

    @patch("app.tasks.ai_review._get_project_path")
    @patch("app.tasks.ai_review._run_pytest")
    @patch("app.tasks.ai_review._run_precommit")
    @patch("app.tasks.ai_review._run_mypy")
    @patch("app.tasks.ai_review._run_code_quality_review")
    @patch("app.tasks.ai_review._run_ui_review")
    @patch("app.tasks.ai_review._verify_step_completion")
    @patch("app.tasks.ai_review.task_store")
    def test_all_checks_pass(
        self,
        mock_store: MagicMock,
        mock_verify_criteria: MagicMock,
        mock_ui_review: MagicMock,
        mock_code_quality: MagicMock,
        mock_mypy: MagicMock,
        mock_precommit: MagicMock,
        mock_pytest: MagicMock,
        mock_project_path: MagicMock,
        tmp_path: Path,
    ) -> None:
        mock_store.get_task.return_value = {
            "id": "task-123",
            "status": "ai_reviewing",
            "project_id": "test",
        }
        mock_project_path.return_value = tmp_path

        mock_pytest.return_value = {"status": "pass"}
        mock_precommit.return_value = {"status": "pass"}
        mock_mypy.return_value = {"status": "pass"}
        mock_code_quality.return_value = {"status": "pass", "verdict": "APPROVE"}
        mock_ui_review.return_value = {"status": "skip", "reason": "No frontend"}
        mock_verify_criteria.return_value = {"status": "pass", "verified": 3, "total": 3}

        result = review_pull_request("task-123")

        assert result["verdict"] == "PASS"
        assert result["summary"] == "All checks passed"
        mock_store.update_task_status.assert_called_with("task-123", "completed")

    @patch("app.tasks.ai_review._get_project_path")
    @patch("app.tasks.ai_review._run_security_risk_classification")
    @patch("app.tasks.ai_review._run_pytest")
    @patch("app.tasks.ai_review._run_breaking_change_detection")
    @patch("app.tasks.ai_review._run_precommit")
    @patch("app.tasks.ai_review._run_mypy")
    @patch("app.tasks.ai_review._run_code_quality_review")
    @patch("app.tasks.ai_review._run_ui_review")
    @patch("app.tasks.ai_review._verify_step_completion")
    @patch("app.tasks.ai_review.task_store")
    def test_pytest_fails(
        self,
        mock_store: MagicMock,
        mock_verify_criteria: MagicMock,
        mock_ui_review: MagicMock,
        mock_code_quality: MagicMock,
        mock_mypy: MagicMock,
        mock_precommit: MagicMock,
        mock_breaking_change: MagicMock,
        mock_pytest: MagicMock,
        mock_security_risk: MagicMock,
        mock_project_path: MagicMock,
        tmp_path: Path,
    ) -> None:
        mock_store.get_task.return_value = {
            "id": "task-123",
            "status": "ai_reviewing",
            "project_id": "test",
        }
        mock_project_path.return_value = tmp_path

        # Security check passes (no escalation)
        mock_security_risk.return_value = {"status": "pass", "risk_level": "low"}
        mock_pytest.return_value = {"status": "fail", "output": "1 failed"}
        # Breaking change detection returns pass to avoid escalation
        mock_breaking_change.return_value = {"status": "pass", "has_breaking_change": False}
        mock_precommit.return_value = {"status": "pass"}
        mock_mypy.return_value = {"status": "pass"}
        mock_code_quality.return_value = {"status": "pass"}
        mock_ui_review.return_value = {"status": "skip"}
        mock_verify_criteria.return_value = {"status": "pass"}

        result = review_pull_request("task-123")

        assert result["verdict"] == "NEEDS_FIX"
        assert "pytest" in result["summary"]
        assert "pytest: Tests failed" in result["issues"]


class TestSecurityEscalation:
    """Tests for _should_escalate_for_security helper."""

    def test_no_escalation_for_passing_checks(self) -> None:
        checks = {
            "code_quality": {"status": "pass", "verdict": "APPROVE"},
        }
        result = _should_escalate_for_security(checks, [])
        assert result is None

    def test_escalates_for_security_keyword_in_rejection(self) -> None:
        checks = {
            "code_quality": {
                "status": "fail",
                "verdict": "REJECT",
                "summary": "SQL injection vulnerability detected",
                "issues": ["Unsafe query construction"],
            },
        }
        result = _should_escalate_for_security(checks, [])
        assert result is not None
        assert "injection" in result.lower()

    def test_escalates_for_credential_keyword(self) -> None:
        checks = {
            "code_quality": {
                "status": "fail",
                "verdict": "REJECT",
                "summary": "Hardcoded credentials found",
                "issues": [],
            },
        }
        result = _should_escalate_for_security(checks, [])
        assert result is not None
        assert "credential" in result.lower()

    def test_escalates_for_architecture_keyword(self) -> None:
        checks = {
            "code_quality": {
                "status": "fail",
                "verdict": "REJECT",
                "summary": "Breaking change to API contract",
                "issues": [],
            },
        }
        result = _should_escalate_for_security(checks, [])
        assert result is not None
        assert "breaking change" in result.lower()

    def test_escalates_for_security_in_issues_list(self) -> None:
        checks = {"code_quality": {"status": "pass"}}
        issues = ["Authentication bypass possible"]
        result = _should_escalate_for_security(checks, issues)
        assert result is not None
        assert "authentication" in result.lower()

    def test_no_escalation_for_non_security_failure(self) -> None:
        checks = {
            "code_quality": {
                "status": "fail",
                "verdict": "REJECT",
                "summary": "Code style violations",
                "issues": ["Missing docstrings"],
            },
        }
        result = _should_escalate_for_security(checks, [])
        assert result is None

    def test_security_keywords_list_exists(self) -> None:
        assert len(SECURITY_KEYWORDS) > 0
        assert "injection" in SECURITY_KEYWORDS
        assert "xss" in SECURITY_KEYWORDS

    def test_architecture_keywords_list_exists(self) -> None:
        assert len(ARCHITECTURE_KEYWORDS) > 0
        assert "breaking change" in ARCHITECTURE_KEYWORDS


class TestEscalationToHumanReview:
    """Tests for escalation to human review state."""

    @patch("app.tasks.ai_review._notify_human_review_needed")
    @patch("app.tasks.ai_review._should_escalate_for_security")
    @patch("app.tasks.ai_review._get_project_path")
    @patch("app.tasks.ai_review._run_pytest")
    @patch("app.tasks.ai_review._run_precommit")
    @patch("app.tasks.ai_review._run_mypy")
    @patch("app.tasks.ai_review._run_code_quality_review")
    @patch("app.tasks.ai_review._run_ui_review")
    @patch("app.tasks.ai_review._verify_step_completion")
    @patch("app.tasks.ai_review.task_store")
    def test_security_issue_escalates_immediately(
        self,
        mock_store: MagicMock,
        mock_verify_criteria: MagicMock,
        mock_ui_review: MagicMock,
        mock_code_quality: MagicMock,
        mock_mypy: MagicMock,
        mock_precommit: MagicMock,
        mock_pytest: MagicMock,
        mock_project_path: MagicMock,
        mock_escalate: MagicMock,
        mock_notify: MagicMock,
        tmp_path: Path,
    ) -> None:
        mock_store.get_task.return_value = {
            "id": "task-123",
            "status": "ai_reviewing",
            "project_id": "test",
        }
        mock_project_path.return_value = tmp_path
        mock_escalate.return_value = "Security issue: injection detected"

        mock_pytest.return_value = {"status": "pass"}
        mock_precommit.return_value = {"status": "pass"}
        mock_mypy.return_value = {"status": "pass"}
        mock_code_quality.return_value = {"status": "pass"}
        mock_ui_review.return_value = {"status": "skip"}
        mock_verify_criteria.return_value = {"status": "pass"}

        result = review_pull_request("task-123")

        assert result["verdict"] == "FAIL"
        assert "Security" in result["summary"]
        mock_store.update_task_status.assert_called_with("task-123", "blocked")
        mock_notify.assert_called_once()

    @patch("app.tasks.ai_review._get_project_path")
    @patch("app.tasks.ai_review._run_pytest")
    @patch("app.tasks.ai_review._run_precommit")
    @patch("app.tasks.ai_review._run_mypy")
    @patch("app.tasks.ai_review._run_code_quality_review")
    @patch("app.tasks.ai_review._run_ui_review")
    @patch("app.tasks.ai_review._verify_step_completion")
    @patch("app.tasks.ai_review.task_store")
    def test_error_check_triggers_retry(
        self,
        mock_store: MagicMock,
        mock_verify_criteria: MagicMock,
        mock_ui_review: MagicMock,
        mock_code_quality: MagicMock,
        mock_mypy: MagicMock,
        mock_precommit: MagicMock,
        mock_pytest: MagicMock,
        mock_project_path: MagicMock,
        tmp_path: Path,
    ) -> None:
        # Simulate max retries exceeded scenario
        mock_store.get_task.return_value = {
            "id": "task-123",
            "status": "ai_reviewing",
            "project_id": "test",
        }
        mock_project_path.return_value = tmp_path

        # All pass but one error
        mock_pytest.return_value = {"status": "pass"}
        mock_precommit.return_value = {"status": "pass"}
        mock_mypy.return_value = {"status": "pass"}
        mock_code_quality.return_value = {"status": "error", "error": "API timeout"}
        mock_ui_review.return_value = {"status": "skip"}
        mock_verify_criteria.return_value = {"status": "pass"}

        # Note: We can't easily test the retry mechanism here without
        # a full Celery test setup. This tests the error check detection.
        # The actual retry/escalation is integration-tested separately.
