"""Unit tests for subtask completion gate enforcement.

Tests the gate logic in subtasks.update_subtask_passes().
Note: Per ac-1050/ac-1051, the gate now runs verification via
_run_linked_verifications_for_subtask instead of blocking.
"""

from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import pytest

from app.storage.subtasks import SubtaskGateError, update_subtask_passes


class TestSubtaskGateError:
    """Tests for the SubtaskGateError exception class."""

    def test_error_message(self):
        """Test that error message is preserved."""
        error = SubtaskGateError("Cannot mark subtask 1.1 as passed")
        assert str(error) == "Cannot mark subtask 1.1 as passed"

    def test_incomplete_steps_attribute(self):
        """Test that incomplete_steps attribute is set."""
        error = SubtaskGateError("Error", incomplete_steps=[1, 2, 3])
        assert error.incomplete_steps == [1, 2, 3]

    def test_incomplete_steps_defaults_empty(self):
        """Test that incomplete_steps defaults to empty list."""
        error = SubtaskGateError("Error")
        assert error.incomplete_steps == []


class TestUpdateSubtaskPassesGate:
    """Tests for the gate behavior in update_subtask_passes().

    Note: Per ac-1050/ac-1051, verification runs via
    _run_linked_verifications_for_subtask.
    """

    @pytest.fixture
    def mock_connection(self):
        """Create a mock database connection."""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=False)
        return mock_conn, mock_cursor

    @patch("app.storage.subtasks._run_linked_verifications_for_subtask")
    @patch("app.storage.subtasks.get_connection")
    def test_gate_runs_verification(self, mock_get_conn, mock_verify, mock_connection):
        """Marking subtask as passed should run linked verifications."""
        mock_conn, mock_cursor = mock_connection
        mock_get_conn.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_get_conn.return_value.__exit__ = MagicMock(return_value=False)
        mock_verify.return_value = {"passed": True, "results": [], "failed": None}
        mock_cursor.rowcount = 0  # No steps to auto-close
        now = datetime.now(UTC)
        mock_cursor.fetchone.return_value = (
            "task-123-1.1",
            "task-123",
            "1.1",
            "implementation",
            "Description",
            None,
            True,
            now,
            0,
            now,
        )

        update_subtask_passes("task-123", "1.1", passes=True)
        mock_verify.assert_called_once()

    @patch("app.storage.subtasks._run_linked_verifications_for_subtask")
    @patch("app.storage.subtasks.get_connection")
    def test_gate_allows_when_verification_passes(
        self, mock_get_conn, mock_verify, mock_connection
    ):
        """Marking subtask as passed should work if verification passes."""
        mock_conn, mock_cursor = mock_connection
        mock_get_conn.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_get_conn.return_value.__exit__ = MagicMock(return_value=False)
        mock_verify.return_value = {"passed": True, "results": [], "failed": None}
        mock_cursor.rowcount = 0  # No steps to auto-close
        now = datetime.now(UTC)
        mock_cursor.fetchone.return_value = (
            "task-123-1.1",
            "task-123",
            "1.1",
            "implementation",
            "Description",
            None,
            True,
            now,
            0,
            now,
        )

        update_subtask_passes("task-123", "1.1", passes=True)
        assert mock_verify.called

    @patch("app.storage.subtasks._run_linked_verifications_for_subtask")
    @patch("app.storage.subtasks.get_connection")
    def test_force_param_deprecated(self, mock_get_conn, mock_verify, mock_connection):
        """force=True is deprecated - behavior unchanged."""
        mock_conn, mock_cursor = mock_connection
        mock_get_conn.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_get_conn.return_value.__exit__ = MagicMock(return_value=False)
        mock_verify.return_value = {"passed": True, "results": [], "failed": None}
        mock_cursor.rowcount = 0  # No steps to auto-close
        now = datetime.now(UTC)
        mock_cursor.fetchone.return_value = (
            "task-123-1.1",
            "task-123",
            "1.1",
            "implementation",
            "Description",
            None,
            True,
            now,
            0,
            now,
        )

        # Should not raise with force=True (param ignored)
        update_subtask_passes("task-123", "1.1", passes=True, force=True)
        # Verification still called regardless of force
        assert mock_verify.called

    @patch("app.storage.subtasks.get_connection")
    def test_passes_false_skips_verification(self, mock_get_conn, mock_connection):
        """Setting passes=False should skip verification (resetting is always allowed)."""
        mock_conn, mock_cursor = mock_connection
        mock_get_conn.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_get_conn.return_value.__exit__ = MagicMock(return_value=False)
        now = datetime.now(UTC)
        mock_cursor.fetchone.return_value = (
            "task-123-1.1",
            "task-123",
            "1.1",
            "implementation",
            "Description",
            None,
            False,
            None,
            0,
            now,
        )

        # Should not raise, verification only applies when passes=True
        result = update_subtask_passes("task-123", "1.1", passes=False)
        assert result is not None

    @patch("app.storage.subtasks._run_linked_verifications_for_subtask")
    @patch("app.storage.subtasks.get_connection")
    def test_subtask_with_no_linked_criteria_can_pass(
        self, mock_get_conn, mock_verify, mock_connection
    ):
        """Subtask with no linked criteria should be allowed to pass."""
        mock_conn, mock_cursor = mock_connection
        mock_get_conn.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_get_conn.return_value.__exit__ = MagicMock(return_value=False)
        mock_verify.return_value = {"passed": True, "results": [], "failed": None}
        mock_cursor.rowcount = 0  # No steps to auto-close
        now = datetime.now(UTC)
        mock_cursor.fetchone.return_value = (
            "task-123-1.1",
            "task-123",
            "1.1",
            "implementation",
            "Description",
            None,
            True,
            now,
            0,
            now,
        )

        update_subtask_passes("task-123", "1.1", passes=True)
        assert mock_verify.called


class TestGateErrorMessage:
    """Tests for gate error message formatting (for API compatibility)."""

    def test_message_includes_subtask_id(self):
        """Error message should include the subtask ID being marked."""
        error = SubtaskGateError(
            "Cannot mark subtask 2.3 as passed: steps [1, 2] are not complete.",
            incomplete_steps=[1, 2],
        )
        assert "subtask 2.3" in str(error)

    def test_message_includes_incomplete_list(self):
        """Error message should list the incomplete steps."""
        error = SubtaskGateError(
            "Cannot mark subtask 2.3 as passed: steps [1, 2] are not complete.",
            incomplete_steps=[1, 2],
        )
        assert "[1, 2]" in str(error)
