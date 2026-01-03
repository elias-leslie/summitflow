"""Unit tests for subtask completion gate enforcement.

Tests the gate logic in subtasks.update_subtask_passes() that ensures
a subtask cannot be marked passed until all its steps are passed.
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
    """Tests for the gate enforcement in update_subtask_passes()."""

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

    @patch("app.storage.subtasks.get_connection")
    def test_gate_blocks_when_steps_incomplete(self, mock_get_conn, mock_connection):
        """Marking subtask as passed should fail if any steps are incomplete."""
        mock_conn, mock_cursor = mock_connection
        mock_get_conn.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_get_conn.return_value.__exit__ = MagicMock(return_value=False)
        # Simulate incomplete steps 2 and 4
        mock_cursor.fetchall.return_value = [(2,), (4,)]

        with pytest.raises(SubtaskGateError) as exc_info:
            update_subtask_passes("task-123", "1.1", passes=True)

        assert exc_info.value.incomplete_steps == [2, 4]
        assert "Cannot mark subtask 1.1 as passed" in str(exc_info.value)
        assert "[2, 4]" in str(exc_info.value)

    @patch("app.storage.subtasks.get_connection")
    def test_gate_allows_when_all_steps_complete(self, mock_get_conn, mock_connection):
        """Marking subtask as passed should work if all steps are complete."""
        mock_conn, mock_cursor = mock_connection
        mock_get_conn.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_get_conn.return_value.__exit__ = MagicMock(return_value=False)
        now = datetime.now(UTC)
        # Simulate all steps complete (empty list)
        mock_cursor.fetchall.return_value = []
        mock_cursor.fetchone.return_value = (
            "task-123-1.1",
            "task-123",
            "1.1",
            "implementation",
            "Description",
            True,
            now,
            0,
            now,
        )

        # Should not raise
        result = update_subtask_passes("task-123", "1.1", passes=True)
        assert result is not None

    @patch("app.storage.subtasks.get_connection")
    def test_force_bypasses_gate(self, mock_get_conn, mock_connection):
        """force=True should bypass gate check even with incomplete steps."""
        mock_conn, mock_cursor = mock_connection
        mock_get_conn.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_get_conn.return_value.__exit__ = MagicMock(return_value=False)
        now = datetime.now(UTC)
        # Even with incomplete steps, force should work
        mock_cursor.fetchone.return_value = (
            "task-123-1.1",
            "task-123",
            "1.1",
            "implementation",
            "Description",
            True,
            now,
            0,
            now,
        )

        # Should not raise with force=True
        result = update_subtask_passes("task-123", "1.1", passes=True, force=True)
        assert result is not None
        # fetchall for gate check should NOT be called
        mock_cursor.fetchall.assert_not_called()

    @patch("app.storage.subtasks.get_connection")
    def test_passes_false_skips_gate(self, mock_get_conn, mock_connection):
        """Setting passes=False should skip gate check (resetting is always allowed)."""
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
            False,
            None,
            0,
            now,
        )

        # Should not raise, gate only applies when passes=True
        result = update_subtask_passes("task-123", "1.1", passes=False)
        assert result is not None
        # Gate query should not be called for passes=False
        mock_cursor.fetchall.assert_not_called()

    @patch("app.storage.subtasks.get_connection")
    def test_subtask_with_no_steps_can_pass(self, mock_get_conn, mock_connection):
        """Subtask with no steps should be allowed to pass (no gate violation)."""
        mock_conn, mock_cursor = mock_connection
        mock_get_conn.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_get_conn.return_value.__exit__ = MagicMock(return_value=False)
        now = datetime.now(UTC)
        # No incomplete steps (also means no steps at all)
        mock_cursor.fetchall.return_value = []
        mock_cursor.fetchone.return_value = (
            "task-123-1.1",
            "task-123",
            "1.1",
            "implementation",
            "Description",
            True,
            now,
            0,
            now,
        )

        # Should not raise
        result = update_subtask_passes("task-123", "1.1", passes=True)
        assert result is not None


class TestGateErrorMessage:
    """Tests for gate error message formatting."""

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

    def test_message_includes_bypass_hint(self):
        """Error message should mention force=True bypass option."""
        error = SubtaskGateError(
            "Cannot mark subtask 2.3 as passed: steps [1] are not complete. "
            "Use force=True to bypass.",
            incomplete_steps=[1],
        )
        assert "force=True" in str(error)


class TestSubtaskIdGeneration:
    """Tests for subtask ID generation in gate logic."""

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

    @patch("app.storage.subtasks._generate_subtask_id")
    @patch("app.storage.subtasks.get_connection")
    def test_uses_generated_table_id(self, mock_get_conn, mock_gen_id, mock_connection):
        """Gate check should use the generated table ID format."""
        mock_conn, mock_cursor = mock_connection
        mock_get_conn.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_get_conn.return_value.__exit__ = MagicMock(return_value=False)
        now = datetime.now(UTC)
        mock_gen_id.return_value = "task-abc-1.1"
        mock_cursor.fetchall.return_value = []
        mock_cursor.fetchone.return_value = (
            "task-abc-1.1",
            "task-abc",
            "1.1",
            "implementation",
            "Description",
            True,
            now,
            0,
            now,
        )

        update_subtask_passes("task-abc", "1.1", passes=True)

        # Verify _generate_subtask_id was called with correct args
        mock_gen_id.assert_called_with("task-abc", "1.1")
