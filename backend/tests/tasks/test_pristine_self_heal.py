"""Tests for pristine self-heal functionality.

Tests the pre-execution self-healing loop that fixes quality gate failures.
"""

from __future__ import annotations

from collections.abc import Generator
from unittest.mock import MagicMock, patch

import pytest

# Base module path for pristine.py where functions are imported/used
_PRISTINE = "app.tasks.autonomous.exec_modules.pristine"


class TestParseErrorCount:
    """Tests for _parse_error_count helper function."""

    def test_parse_found_n_errors(self):
        """Parse 'Found N errors' pattern."""
        from app.tasks.autonomous.execution import _parse_error_count

        output = "Running lint... Found 5 errors in 3 files"
        assert _parse_error_count(output) == 5

    def test_parse_n_errors(self):
        """Parse 'N errors' pattern."""
        from app.tasks.autonomous.execution import _parse_error_count

        output = "Lint check failed: 12 errors detected"
        assert _parse_error_count(output) == 12

    def test_parse_n_failed(self):
        """Parse 'N failed' pattern."""
        from app.tasks.autonomous.execution import _parse_error_count

        output = "Test results: 3 failed, 47 passed"
        assert _parse_error_count(output) == 3

    def test_parse_fallback_to_error_lines(self):
        """Fall back to counting error lines."""
        from app.tasks.autonomous.execution import _parse_error_count

        output = """
error: unused import
error: variable not defined
error: syntax error
"""
        assert _parse_error_count(output) == 3

    def test_parse_no_errors(self):
        """No errors returns 0."""
        from app.tasks.autonomous.execution import _parse_error_count

        output = "All checks passed successfully!"
        assert _parse_error_count(output) == 0


class TestPristineSelfHeal:
    """Tests for pristine_self_heal function."""

    @pytest.fixture
    def mock_project_path(self):
        """Mock get_project_root_path to return a test path."""
        with patch(f"{_PRISTINE}.get_project_root_path") as mock:
            mock.return_value = "/test/project"
            yield mock

    @pytest.fixture
    def mock_dt_found(self):
        """Mock find_dev_tools to return dt path."""
        with patch(f"{_PRISTINE}.find_dev_tools") as mock:
            mock.return_value = "/usr/local/bin/dt"
            yield mock

    @pytest.fixture
    def mock_subprocess(self):
        """Mock subprocess.run."""
        with patch(f"{_PRISTINE}.subprocess.run") as mock:
            yield mock

    @pytest.fixture
    def mock_agent_client(self):
        """Mock get_sync_client."""
        with patch(f"{_PRISTINE}.get_sync_client") as mock:
            client = MagicMock()
            response = MagicMock()
            response.content = "Fixed the issues"
            response.session_id = "session-123"
            response.progress_log = None
            client.complete.return_value = response
            mock.return_value = client
            yield client

    @pytest.fixture(autouse=True)
    def mock_prompt_template(self) -> Generator[MagicMock]:
        """Mock get_prompt_template to avoid hitting real API."""
        with patch(f"{_PRISTINE}.get_prompt_template") as mock:
            mock.return_value = "Fix errors:\n```\n{errors_output}\n```"
            yield mock

    @pytest.fixture(autouse=True)
    def mock_build_dt_command(self) -> Generator[MagicMock]:
        """Mock build_dt_command to avoid hitting database."""
        with patch(f"{_PRISTINE}.build_dt_command") as mock:
            mock.return_value = ["/usr/local/bin/dt", "--quick"]
            yield mock

    @pytest.fixture(autouse=True)
    def mock_emit_log(self) -> Generator[MagicMock]:
        """Mock emit_log to avoid hitting Redis."""
        with patch(f"{_PRISTINE}.emit_log") as mock:
            yield mock

    @pytest.fixture(autouse=True)
    def mock_emit_progress_log(self) -> Generator[MagicMock]:
        """Mock emit_progress_log to avoid hitting Redis."""
        with patch(f"{_PRISTINE}.emit_progress_log") as mock:
            yield mock

    @pytest.fixture(autouse=True)
    def mock_add_agent_hub_session(self) -> Generator[MagicMock]:
        """Mock add_agent_hub_session to avoid hitting database."""
        with patch("app.storage.tasks.core.add_agent_hub_session") as mock:
            yield mock

    def test_pristine_already_clean(self, mock_project_path, mock_dt_found, mock_subprocess):
        """If dt --check passes on first try, return True without agent call."""
        from app.tasks.autonomous.execution import pristine_self_heal

        mock_subprocess.return_value = MagicMock(returncode=0)

        result = pristine_self_heal("task-123", "test-project")

        assert result is True
        mock_subprocess.assert_called_once()

    def test_pristine_fix_succeeds(
        self, mock_project_path, mock_dt_found, mock_subprocess, mock_agent_client
    ):
        """Agent fixes issues successfully."""
        from app.tasks.autonomous.execution import pristine_self_heal

        mock_subprocess.side_effect = [
            MagicMock(returncode=1, stdout="Found 3 errors", stderr=""),
            MagicMock(returncode=0, stdout="", stderr=""),
        ]

        with patch(f"{_PRISTINE}.has_uncommitted_changes") as mock_changes:
            mock_changes.return_value = True
            with patch(f"{_PRISTINE}.auto_commit") as mock_commit:
                mock_commit.return_value = True

                result = pristine_self_heal("task-123", "test-project")

        assert result is True
        mock_agent_client.complete.assert_called_once()
        mock_commit.assert_called()

    def test_pristine_error_count_regression_reverts(
        self, mock_project_path, mock_dt_found, mock_subprocess, mock_agent_client
    ):
        """If error count increases, revert with git checkout and return False."""
        from app.tasks.autonomous.execution import pristine_self_heal

        mock_subprocess.side_effect = [
            MagicMock(returncode=1, stdout="Found 3 errors", stderr=""),
            MagicMock(returncode=1, stdout="Found 5 errors", stderr=""),
            MagicMock(returncode=0, stdout="", stderr=""),
        ]

        result = pristine_self_heal("task-123", "test-project")

        assert result is False
        git_checkout_calls = [c for c in mock_subprocess.call_args_list if "checkout" in str(c)]
        assert len(git_checkout_calls) == 1

    def test_pristine_max_attempts_exhausted(
        self, mock_project_path, mock_dt_found, mock_subprocess, mock_agent_client
    ):
        """After max attempts, return False."""
        from app.tasks.autonomous.execution import pristine_self_heal

        mock_subprocess.return_value = MagicMock(returncode=1, stdout="Found 3 errors", stderr="")

        result = pristine_self_heal("task-123", "test-project")

        assert result is False
        assert mock_agent_client.complete.call_count == 2

    def test_pristine_no_project_path(self):
        """If project has no root_path, return False."""
        from app.tasks.autonomous.execution import pristine_self_heal

        with patch(f"{_PRISTINE}.get_project_root_path") as mock:
            mock.return_value = None

            result = pristine_self_heal("task-123", "test-project")

        assert result is False

    def test_pristine_no_dt_command(self, mock_project_path):
        """If dt not found, return True (skip check)."""
        from app.tasks.autonomous.execution import pristine_self_heal

        with patch(f"{_PRISTINE}.find_dev_tools") as mock:
            mock.return_value = None

            result = pristine_self_heal("task-123", "test-project")

        assert result is True

    def test_pristine_timeout(self, mock_project_path, mock_dt_found, mock_subprocess):
        """Timeout returns False."""
        import subprocess

        from app.tasks.autonomous.execution import pristine_self_heal

        mock_subprocess.side_effect = subprocess.TimeoutExpired("dt", 600)

        result = pristine_self_heal("task-123", "test-project")

        assert result is False
