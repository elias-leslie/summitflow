"""Unit tests for attempt history tracking.

Tests circular fix detection, attempt recording, and history persistence.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from app.services.self_healing.attempt_history import (
    ATTEMPT_HISTORY_FILENAME,
    AttemptHistory,
    compute_diff_hash,
    compute_error_hash,
)


class TestComputeErrorHash:
    """Tests for error hash computation."""

    def test_hash_is_stable(self) -> None:
        """Same input produces same hash."""
        h1 = compute_error_hash("ruff", "F401", "'os' imported but unused")
        h2 = compute_error_hash("ruff", "F401", "'os' imported but unused")
        assert h1 == h2

    def test_different_errors_different_hashes(self) -> None:
        """Different errors produce different hashes."""
        h1 = compute_error_hash("ruff", "F401", "'os' imported but unused")
        h2 = compute_error_hash("ruff", "F401", "'sys' imported but unused")
        assert h1 != h2

    def test_different_check_types_different_hashes(self) -> None:
        """Different check types produce different hashes."""
        h1 = compute_error_hash("ruff", "F401", "unused import")
        h2 = compute_error_hash("mypy", "F401", "unused import")
        assert h1 != h2

    def test_hash_length(self) -> None:
        """Hash is truncated to 16 characters."""
        h = compute_error_hash("ruff", "F401", "test error")
        assert len(h) == 16

    def test_hash_with_file_path(self) -> None:
        """File path affects hash."""
        h1 = compute_error_hash("ruff", "F401", "error", file_path="a.py")
        h2 = compute_error_hash("ruff", "F401", "error", file_path="b.py")
        assert h1 != h2

    def test_line_number_normalized(self) -> None:
        """Line numbers in error messages are normalized."""
        h1 = compute_error_hash("ruff", "F401", "error on line 42")
        h2 = compute_error_hash("ruff", "F401", "error on line 99")
        assert h1 == h2


class TestComputeDiffHash:
    """Tests for diff hash computation."""

    def test_same_diff_same_hash(self) -> None:
        """Same change produces same hash."""
        original = "import os\nimport sys"
        new = "import sys"

        h1 = compute_diff_hash(original, new)
        h2 = compute_diff_hash(original, new)
        assert h1 == h2

    def test_different_diff_different_hash(self) -> None:
        """Different changes produce different hashes."""
        original = "import os\nimport sys"

        h1 = compute_diff_hash(original, "import sys")
        h2 = compute_diff_hash(original, "import os")
        assert h1 != h2

    def test_hash_length(self) -> None:
        """Hash is truncated to 16 characters."""
        h = compute_diff_hash("line1\nline2", "line1\nline3")
        assert len(h) == 16


class TestAttemptHistory:
    """Tests for AttemptHistory class."""

    @pytest.fixture
    def temp_worktree(self) -> Path:
        """Create a temporary worktree directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)

    @pytest.fixture
    def history(self, temp_worktree: Path) -> AttemptHistory:
        """Create an AttemptHistory instance."""
        return AttemptHistory(temp_worktree)

    def test_record_and_retrieve_attempt(self, history: AttemptHistory) -> None:
        """Test recording and retrieving attempts."""
        attempt = history.record_attempt(
            task_id="task-123",
            error_hash="abc123",
            diff_hash="def456",
            approach_summary="Remove unused import",
            outcome="failed",
            model="gemini-flash",
            escalation_level="WORKER",
        )

        assert attempt.attempt_number == 1
        assert attempt.error_hash == "abc123"
        assert attempt.outcome == "failed"

    def test_attempt_count_increments(self, history: AttemptHistory) -> None:
        """Test that attempt numbers increment."""
        history.record_attempt(
            task_id="task-123",
            error_hash="abc123",
            diff_hash="diff1",
            approach_summary="First try",
            outcome="failed",
        )
        attempt2 = history.record_attempt(
            task_id="task-123",
            error_hash="abc123",
            diff_hash="diff2",
            approach_summary="Second try",
            outcome="failed",
        )

        assert attempt2.attempt_number == 2
        assert history.get_attempt_count("abc123") == 2

    def test_is_circular_fix_false_first_attempt(self, history: AttemptHistory) -> None:
        """Test circular check returns False for first attempt."""
        is_circular = history.is_circular_fix("error1", "diff1")
        assert is_circular is False

    def test_is_circular_fix_false_after_one_failure(self, history: AttemptHistory) -> None:
        """Test circular check returns False after one failure."""
        history.record_attempt(
            task_id="task-123",
            error_hash="error1",
            diff_hash="diff1",
            approach_summary="First try",
            outcome="failed",
        )

        is_circular = history.is_circular_fix("error1", "diff1")
        assert is_circular is False

    def test_is_circular_fix_true_after_two_failures(self, history: AttemptHistory) -> None:
        """Test circular check returns True after two failures with same diff."""
        # Record two failed attempts with same diff
        history.record_attempt(
            task_id="task-123",
            error_hash="error1",
            diff_hash="diff1",
            approach_summary="First try",
            outcome="failed",
        )
        history.record_attempt(
            task_id="task-123",
            error_hash="error1",
            diff_hash="diff1",
            approach_summary="Second try (same approach)",
            outcome="failed",
        )

        # Same diff should now be circular
        is_circular = history.is_circular_fix("error1", "diff1")
        assert is_circular is True

    def test_is_circular_fix_false_for_different_diff(self, history: AttemptHistory) -> None:
        """Test circular check returns False for different diff."""
        # Record two failed attempts with same diff
        history.record_attempt(
            task_id="task-123",
            error_hash="error1",
            diff_hash="diff1",
            approach_summary="First try",
            outcome="failed",
        )
        history.record_attempt(
            task_id="task-123",
            error_hash="error1",
            diff_hash="diff1",
            approach_summary="Second try",
            outcome="failed",
        )

        # Different diff should not be circular
        is_circular = history.is_circular_fix("error1", "diff2")
        assert is_circular is False

    def test_is_circular_fix_ignores_success(self, history: AttemptHistory) -> None:
        """Test circular check ignores successful attempts."""
        history.record_attempt(
            task_id="task-123",
            error_hash="error1",
            diff_hash="diff1",
            approach_summary="First try",
            outcome="success",
        )
        history.record_attempt(
            task_id="task-123",
            error_hash="error1",
            diff_hash="diff1",
            approach_summary="Second try",
            outcome="success",
        )

        # Successful attempts don't count toward circular
        is_circular = history.is_circular_fix("error1", "diff1")
        assert is_circular is False

    def test_get_previous_approaches(self, history: AttemptHistory) -> None:
        """Test getting previous approaches."""
        history.record_attempt(
            task_id="task-123",
            error_hash="error1",
            diff_hash="diff1",
            approach_summary="First approach",
            outcome="failed",
            model="gemini-flash",
        )
        history.record_attempt(
            task_id="task-123",
            error_hash="error1",
            diff_hash="diff2",
            approach_summary="Second approach",
            outcome="failed",
            model="claude-sonnet",
        )

        approaches = history.get_previous_approaches("error1")

        assert len(approaches) == 2
        assert approaches[0]["approach_summary"] == "First approach"
        assert approaches[1]["approach_summary"] == "Second approach"

    def test_get_failed_diff_hashes(self, history: AttemptHistory) -> None:
        """Test getting failed diff hashes."""
        history.record_attempt(
            task_id="task-123",
            error_hash="error1",
            diff_hash="diff1",
            approach_summary="Try 1",
            outcome="failed",
        )
        history.record_attempt(
            task_id="task-123",
            error_hash="error1",
            diff_hash="diff2",
            approach_summary="Try 2",
            outcome="success",
        )
        history.record_attempt(
            task_id="task-123",
            error_hash="error1",
            diff_hash="diff3",
            approach_summary="Try 3",
            outcome="failed",
        )

        failed_hashes = history.get_failed_diff_hashes("error1")

        assert failed_hashes == {"diff1", "diff3"}

    def test_persistence(self, temp_worktree: Path) -> None:
        """Test that history persists to file and can be reloaded."""
        # Create and record
        history1 = AttemptHistory(temp_worktree)
        history1.record_attempt(
            task_id="task-123",
            error_hash="error1",
            diff_hash="diff1",
            approach_summary="Persisted attempt",
            outcome="failed",
        )

        # File should exist
        history_file = temp_worktree / ATTEMPT_HISTORY_FILENAME
        assert history_file.exists()

        # Create new instance from same path
        history2 = AttemptHistory(temp_worktree)

        # Should have same data
        assert history2.get_attempt_count("error1") == 1
        approaches = history2.get_previous_approaches("error1")
        assert approaches[0]["approach_summary"] == "Persisted attempt"

    def test_clear_specific_error(self, history: AttemptHistory) -> None:
        """Test clearing history for specific error."""
        history.record_attempt(
            task_id="task-123",
            error_hash="error1",
            diff_hash="diff1",
            approach_summary="Error 1",
            outcome="failed",
        )
        history.record_attempt(
            task_id="task-456",
            error_hash="error2",
            diff_hash="diff2",
            approach_summary="Error 2",
            outcome="failed",
        )

        history.clear("error1")

        assert history.get_attempt_count("error1") == 0
        assert history.get_attempt_count("error2") == 1

    def test_clear_all(self, history: AttemptHistory) -> None:
        """Test clearing all history."""
        history.record_attempt(
            task_id="task-123",
            error_hash="error1",
            diff_hash="diff1",
            approach_summary="Error 1",
            outcome="failed",
        )
        history.record_attempt(
            task_id="task-456",
            error_hash="error2",
            diff_hash="diff2",
            approach_summary="Error 2",
            outcome="failed",
        )

        history.clear()

        assert history.get_attempt_count("error1") == 0
        assert history.get_attempt_count("error2") == 0

    def test_json_structure(self, temp_worktree: Path) -> None:
        """Test the JSON file structure is correct."""
        history = AttemptHistory(temp_worktree)
        history.record_attempt(
            task_id="task-123",
            error_hash="abc123",
            diff_hash="def456",
            approach_summary="Test approach",
            outcome="failed",
            model="gemini-flash",
            escalation_level="WORKER",
            error_signature="ruff:F401:test",
            file_path="test.py",
        )

        history_file = temp_worktree / ATTEMPT_HISTORY_FILENAME
        data = json.loads(history_file.read_text())

        assert "abc123" in data
        entry = data["abc123"]
        assert entry["task_id"] == "task-123"
        assert entry["error_signature"] == "ruff:F401:test"
        assert entry["file_path"] == "test.py"
        assert len(entry["attempts"]) == 1
        assert entry["attempts"][0]["diff_hash"] == "def456"
        assert entry["attempts"][0]["model"] == "gemini-flash"
