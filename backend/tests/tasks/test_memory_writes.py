"""Tests for post-execution memory writes."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from app.tasks.autonomous.exec_modules.memory_writes import (
    rate_cited_memories,
    save_qa_fix_pattern,
    save_subtask_learning,
)


class TestSaveSubtaskLearning:
    """Tests for subtask execution learning saves."""

    @patch("app.tasks.autonomous.exec_modules.memory_writes.get_sync_client")
    def test_clean_pass_saves_nothing(self, mock_get: MagicMock) -> None:
        """Clean pass (first attempt) should not save - nothing to learn."""
        save_subtask_learning(
            task_id="task-1",
            subtask_short_id="1.1",
            subtask_type="implementation",
            project_id="test-project",
            passed=True,
            self_fix_attempts=0,
            supervisor_guided_attempts=0,
            step_results=[{"passed": True}],
        )
        mock_get.assert_not_called()

    @patch("app.tasks.autonomous.exec_modules.memory_writes.get_sync_client")
    def test_pass_after_self_fix_saves_pattern(self, mock_get: MagicMock) -> None:
        """Passed after retry should save the learning pattern."""
        client = MagicMock()
        mock_get.return_value = client

        save_subtask_learning(
            task_id="task-1",
            subtask_short_id="1.1",
            subtask_type="implementation",
            project_id="test-project",
            passed=True,
            self_fix_attempts=2,
            supervisor_guided_attempts=0,
            step_results=[
                {"passed": False, "reason": "import error"},
                {"passed": True},
            ],
        )

        client.save_learning.assert_called_once()
        call_args = client.save_learning.call_args
        content = call_args.args[0]
        assert "3 attempts" in content
        assert "2 self-fix" in content
        assert "import error" in content
        assert call_args.kwargs["injection_tier"] == "reference"
        assert call_args.kwargs["confidence"] == 70

    @patch("app.tasks.autonomous.exec_modules.memory_writes.get_sync_client")
    def test_pass_after_supervisor_guided_saves(self, mock_get: MagicMock) -> None:
        """Passed after supervisor guidance saves with correct counts."""
        client = MagicMock()
        mock_get.return_value = client

        save_subtask_learning(
            task_id="task-1",
            subtask_short_id="1.1",
            subtask_type=None,
            project_id="test-project",
            passed=True,
            self_fix_attempts=3,
            supervisor_guided_attempts=1,
            step_results=[{"passed": False, "error": "timeout"}],
        )

        content = client.save_learning.call_args.args[0]
        assert "5 attempts" in content
        assert "3 self-fix" in content
        assert "1 guided" in content

    @patch("app.tasks.autonomous.exec_modules.memory_writes.get_sync_client")
    def test_failure_saves_failure_pattern(self, mock_get: MagicMock) -> None:
        """Failed subtask saves failure pattern for avoidance."""
        client = MagicMock()
        mock_get.return_value = client

        save_subtask_learning(
            task_id="task-1",
            subtask_short_id="1.2",
            subtask_type="testing",
            project_id="test-project",
            passed=False,
            self_fix_attempts=3,
            supervisor_guided_attempts=3,
            step_results=[
                {"passed": False, "reason": "assertion error"},
                {"passed": False, "error": "module not found"},
            ],
        )

        content = client.save_learning.call_args.args[0]
        assert "FAILED" in content
        assert "7 attempts" in content
        assert "assertion error" in content
        assert client.save_learning.call_args.kwargs["confidence"] == 60

    @patch("app.tasks.autonomous.exec_modules.memory_writes.get_sync_client")
    def test_error_handled_silently(self, mock_get: MagicMock) -> None:
        """Memory write failures should not raise."""
        mock_get.side_effect = RuntimeError("connection failed")

        # Should not raise
        save_subtask_learning(
            task_id="task-1",
            subtask_short_id="1.1",
            subtask_type=None,
            project_id="test-project",
            passed=True,
            self_fix_attempts=1,
            supervisor_guided_attempts=0,
            step_results=[{"passed": False, "reason": "x"}],
        )


class TestSaveQAFixPattern:
    """Tests for QA fix pattern saving."""

    @patch("app.tasks.autonomous.exec_modules.memory_writes.get_sync_client")
    def test_saves_pattern_with_correct_fields(self, mock_get: MagicMock) -> None:
        client = MagicMock()
        mock_get.return_value = client

        save_qa_fix_pattern("task-1", "test-project", "missing type hints", 2)

        client.save_learning.assert_called_once()
        content = client.save_learning.call_args.args[0]
        assert "missing type hints" in content
        assert "2 iteration" in content
        assert client.save_learning.call_args.kwargs["confidence"] == 75

    @patch("app.tasks.autonomous.exec_modules.memory_writes.get_sync_client")
    def test_truncates_long_concerns(self, mock_get: MagicMock) -> None:
        client = MagicMock()
        mock_get.return_value = client

        long_concern = "x" * 200
        save_qa_fix_pattern("task-1", "test-project", long_concern, 1)

        content = client.save_learning.call_args.args[0]
        # Concern truncated to 120 chars — full 200-char string should not appear
        assert long_concern not in content

    @patch("app.tasks.autonomous.exec_modules.memory_writes.get_sync_client")
    def test_error_handled_silently(self, mock_get: MagicMock) -> None:
        mock_get.side_effect = RuntimeError("fail")
        save_qa_fix_pattern("task-1", "test-project", "concern", 1)


class TestRateCitedMemories:
    """Tests for memory citation rating."""

    @patch("app.tasks.autonomous.exec_modules.memory_writes.get_sync_client")
    def test_rates_each_cited_uuid(self, mock_get: MagicMock) -> None:
        client = MagicMock()
        mock_get.return_value = client

        rate_cited_memories(["uuid1", "uuid2", "uuid3"])

        assert client.rate_episode.call_count == 3

    @patch("app.tasks.autonomous.exec_modules.memory_writes.get_sync_client")
    def test_caps_at_10_uuids(self, mock_get: MagicMock) -> None:
        client = MagicMock()
        mock_get.return_value = client

        uuids = [f"uuid{i}" for i in range(20)]
        rate_cited_memories(uuids)

        assert client.rate_episode.call_count == 10

    @patch("app.tasks.autonomous.exec_modules.memory_writes.get_sync_client")
    def test_empty_list_noop(self, mock_get: MagicMock) -> None:
        rate_cited_memories([])
        mock_get.assert_not_called()

    @patch("app.tasks.autonomous.exec_modules.memory_writes.get_sync_client")
    def test_error_handled_silently(self, mock_get: MagicMock) -> None:
        mock_get.side_effect = RuntimeError("fail")
        rate_cited_memories(["uuid1"])
