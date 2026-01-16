"""Unit tests for code health Celery tasks helper functions."""

from unittest.mock import MagicMock, patch

from app.services.code_health.classifier import (
    ClassificationResult,
    ClassificationVerdict,
    Finding,
)
from app.tasks.code_health import _create_health_task, _extract_context


class TestExtractContext:
    """Test _extract_context helper function."""

    def test_returns_first_500_chars(self) -> None:
        """Test context extraction limits to 500 chars."""
        content = "x" * 1000
        context = _extract_context(content, "test")
        assert len(context) == 500

    def test_handles_empty_content(self) -> None:
        """Test context extraction handles empty content."""
        context = _extract_context("", "test")
        assert context == ""

    def test_returns_full_content_if_short(self) -> None:
        """Test returns full content if under 500 chars."""
        content = "short content"
        context = _extract_context(content, "test")
        assert context == "short content"


class TestCreateHealthTask:
    """Test _create_health_task helper function."""

    @patch("app.storage.tasks.create_task")
    def test_creates_task_with_correct_fields(self, mock_create: MagicMock) -> None:
        """Test creating a task for a finding."""
        finding = Finding(
            file_path="app/test.py",
            category="compat_comments",
            pattern="legacy compat",
        )
        result = ClassificationResult(
            verdict=ClassificationVerdict.TRUE_POSITIVE,
            confidence=0.9,
            reason="Real issue",
            suggested_action="Fix it",
        )

        _create_health_task("test-project", finding, result)

        mock_create.assert_called_once()
        call_kwargs = mock_create.call_args.kwargs
        assert call_kwargs["project_id"] == "test-project"
        assert "compat_comments" in call_kwargs["title"]
        assert "app/test.py" in call_kwargs["title"]
        assert call_kwargs["task_type"] == "task"
        assert call_kwargs["priority"] == 3
        # Note: labels are now stored separately (per migration 072)

    @patch("app.storage.tasks.create_task")
    def test_includes_analysis_in_description(self, mock_create: MagicMock) -> None:
        """Test task description includes analysis details."""
        finding = Finding(
            file_path="app/api/routes.py",
            category="stale_todos",
            pattern="TODO: Fix later",
        )
        result = ClassificationResult(
            verdict=ClassificationVerdict.TRUE_POSITIVE,
            confidence=0.85,
            reason="Outdated TODO from 2 years ago",
            suggested_action="Create task or remove",
        )

        _create_health_task("my-project", finding, result)

        call_kwargs = mock_create.call_args.kwargs
        description = call_kwargs["description"]
        assert "stale_todos" in description
        assert "app/api/routes.py" in description
        assert "Outdated TODO" in description
        assert "85%" in description  # Confidence percentage

    @patch("app.storage.tasks.create_task")
    def test_handles_missing_suggested_action(self, mock_create: MagicMock) -> None:
        """Test handling when suggested_action is None."""
        finding = Finding(
            file_path="test.py",
            category="test",
            pattern="test",
        )
        result = ClassificationResult(
            verdict=ClassificationVerdict.TRUE_POSITIVE,
            confidence=0.5,
            reason="Test",
            suggested_action=None,
        )

        _create_health_task("project", finding, result)

        call_kwargs = mock_create.call_args.kwargs
        description = call_kwargs["description"]
        assert "Review and fix the issue" in description

    @patch("app.storage.tasks.create_task", side_effect=Exception("DB error"))
    def test_handles_task_creation_failure(self, mock_create: MagicMock) -> None:
        """Test graceful handling of task creation failure."""
        finding = Finding(
            file_path="test.py",
            category="test",
            pattern="test",
        )
        result = ClassificationResult(
            verdict=ClassificationVerdict.TRUE_POSITIVE,
            confidence=0.5,
            reason="Test",
        )

        # Should not raise, just log error
        _create_health_task("project", finding, result)

        mock_create.assert_called_once()


class TestTaskScheduleConfig:
    """Test that task schedules are configured correctly."""

    def test_daily_scan_task_is_registered(self) -> None:
        """Test daily_code_health_scan is registered as Celery task."""
        from app.tasks.code_health import daily_code_health_scan

        assert hasattr(daily_code_health_scan, "name")
        assert daily_code_health_scan.name == "summitflow.daily_code_health_scan"

    def test_weekly_scan_task_is_registered(self) -> None:
        """Test weekly_deep_scan is registered as Celery task."""
        from app.tasks.code_health import weekly_deep_scan

        assert hasattr(weekly_deep_scan, "name")
        assert weekly_deep_scan.name == "summitflow.weekly_deep_scan"

    def test_tasks_in_beat_schedule(self) -> None:
        """Test code health tasks are in Celery beat schedule."""
        from app.celery_app import celery_app

        schedule = celery_app.conf.beat_schedule
        assert "daily-code-health-scan" in schedule
        assert "weekly-deep-scan" in schedule
        assert schedule["daily-code-health-scan"]["task"] == "summitflow.daily_code_health_scan"
        assert schedule["weekly-deep-scan"]["task"] == "summitflow.weekly_deep_scan"
