"""Unit tests for step completion gate enforcement.

Tests the sequential gate logic in steps.update_step_passes().
Note: Gate is now logging-only, not blocking (per ac-1051).
The gate logs a warning but allows out-of-order completion.
"""

from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import pytest

from app.storage.steps import StepGateError, update_step_passes


class TestStepGateError:
    """Tests for the StepGateError exception class."""

    def test_error_message(self):
        """Test that error message is preserved."""
        error = StepGateError("Cannot mark step 3 as passed")
        assert str(error) == "Cannot mark step 3 as passed"

    def test_missing_steps_attribute(self):
        """Test that missing_steps attribute is set."""
        error = StepGateError("Error", missing_steps=[1, 2])
        assert error.missing_steps == [1, 2]

    def test_missing_steps_defaults_empty(self):
        """Test that missing_steps defaults to empty list."""
        error = StepGateError("Error")
        assert error.missing_steps == []


class TestUpdateStepPassesGate:
    """Tests for the gate behavior in update_step_passes().

    Note: The gate is now logging-only per ac-1051.
    Out-of-order completion is allowed but logged.
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

    @patch("app.storage.steps.get_connection")
    def test_step_one_always_allowed(self, mock_get_conn, mock_connection):
        """Step 1 should always be allowed (no previous steps to check)."""
        mock_conn, mock_cursor = mock_connection
        mock_get_conn.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_get_conn.return_value.__exit__ = MagicMock(return_value=False)
        now = datetime.now(UTC)
        # No gate query should run for step 1
        # Row format: (id, subtask_id, step_number, description, spec, passes, passed_at, created_at)
        mock_cursor.fetchone.return_value = (1, "subtask-1", 1, "Step 1", None, False, None, now)

        # Should not raise
        update_step_passes("subtask-1", 1, passes=True)

    @patch("app.storage.steps._run_linked_verifications")
    @patch("app.storage.steps.get_connection")
    def test_gate_logs_when_previous_incomplete(self, mock_get_conn, mock_verify, mock_connection):
        """Marking step N as passed with incomplete previous steps logs but allows."""
        mock_conn, mock_cursor = mock_connection
        mock_get_conn.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_get_conn.return_value.__exit__ = MagicMock(return_value=False)
        mock_verify.return_value = {"passed": True, "results": [], "failed": None}
        now = datetime.now(UTC)
        # Simulate incomplete steps 1 and 2
        mock_cursor.fetchall.return_value = [(1,), (2,)]
        # Successful row return for the update
        mock_cursor.fetchone.return_value = (1, "subtask-1", 3, "Step 3", None, True, now, now)

        # Should NOT raise - gate is logging-only now
        result = update_step_passes("subtask-1", 3, passes=True)
        assert result is not None

    @patch("app.storage.steps._run_linked_verifications")
    @patch("app.storage.steps.get_connection")
    def test_gate_allows_when_previous_complete(self, mock_get_conn, mock_verify, mock_connection):
        """Marking step N as passed should work if all previous steps are complete."""
        mock_conn, mock_cursor = mock_connection
        mock_get_conn.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_get_conn.return_value.__exit__ = MagicMock(return_value=False)
        mock_verify.return_value = {"passed": True, "results": [], "failed": None}
        now = datetime.now(UTC)
        # Simulate all previous steps complete (empty list)
        mock_cursor.fetchall.return_value = []
        # Row format: (id, subtask_id, step_number, description, spec, passes, passed_at, created_at)
        mock_cursor.fetchone.return_value = (1, "subtask-1", 3, "Step 3", None, True, now, now)

        # Should not raise
        result = update_step_passes("subtask-1", 3, passes=True)
        assert result is not None

    @patch("app.storage.steps._run_linked_verifications")
    @patch("app.storage.steps.get_connection")
    def test_force_param_deprecated(self, mock_get_conn, mock_verify, mock_connection):
        """force=True is deprecated but still accepted for API compatibility."""
        mock_conn, mock_cursor = mock_connection
        mock_get_conn.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_get_conn.return_value.__exit__ = MagicMock(return_value=False)
        mock_verify.return_value = {"passed": True, "results": [], "failed": None}
        now = datetime.now(UTC)
        # Row format: (id, subtask_id, step_number, description, spec, passes, passed_at, created_at)
        mock_cursor.fetchone.return_value = (1, "subtask-1", 3, "Step 3", None, True, now, now)
        mock_cursor.fetchall.return_value = []

        # Should not raise with force=True (param ignored but accepted)
        result = update_step_passes("subtask-1", 3, passes=True, force=True)
        assert result is not None

    @patch("app.storage.steps.get_connection")
    def test_passes_false_skips_verification(self, mock_get_conn, mock_connection):
        """Setting passes=False should skip verification (resetting is always allowed)."""
        mock_conn, mock_cursor = mock_connection
        mock_get_conn.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_get_conn.return_value.__exit__ = MagicMock(return_value=False)
        now = datetime.now(UTC)
        # Row format: (id, subtask_id, step_number, description, spec, passes, passed_at, created_at)
        mock_cursor.fetchone.return_value = (1, "subtask-1", 3, "Step 3", None, False, None, now)

        # Should not raise, gate only applies when passes=True
        result = update_step_passes("subtask-1", 3, passes=False)
        assert result is not None


class TestGateErrorMessage:
    """Tests for gate error message formatting."""

    def test_message_includes_step_number(self):
        """Error message should include the step number being marked."""
        error = StepGateError(
            "Cannot mark step 5 as passed: previous steps [1, 2, 3] are not complete.",
            missing_steps=[1, 2, 3],
        )
        assert "step 5" in str(error)

    def test_message_includes_incomplete_list(self):
        """Error message should list the incomplete steps."""
        error = StepGateError(
            "Cannot mark step 5 as passed: previous steps [1, 2, 3] are not complete.",
            missing_steps=[1, 2, 3],
        )
        assert "[1, 2, 3]" in str(error)
