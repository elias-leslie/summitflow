"""Tests for deterministic duplicate detection in triage.

Verifies that triage_idea() rejects duplicates deterministically
before calling the LLM, and that the LLM prompt no longer contains
active task context.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from app.tasks.autonomous.triage import _parse_triage_response, triage_idea


class TestTriageDeterministicDedup:
    """Triage rejects duplicates without calling the LLM."""

    @patch("app.tasks.autonomous.triage.duplicate_task_exists", return_value="task-dup123")
    @patch("app.tasks.autonomous.triage.task_store")
    @patch("app.tasks.autonomous.triage.log_task_event")
    def test_duplicate_rejected_before_llm(
        self,
        mock_log: MagicMock,
        mock_store: MagicMock,
        mock_dedup: MagicMock,
    ) -> None:
        """When deterministic dedup finds a match, task is cancelled without LLM call."""
        mock_store.get_task.return_value = {
            "title": "Fix login bug",
            "description": "Login is broken",
        }

        with patch("app.tasks.autonomous.triage.get_sync_client") as mock_client:
            result = triage_idea("task-new", "test-project")

            # LLM should NOT be called
            mock_client.assert_not_called()

        assert result["status"] == "completed"
        assert result["result"]["status"] == "REJECT"
        assert "task-dup123" in result["result"]["reject_reason"]
        mock_store.update_task_status.assert_called_once_with("task-new", "cancelled")

    @patch("app.tasks.autonomous.triage.duplicate_task_exists", return_value="task-dup123")
    @patch("app.tasks.autonomous.triage.task_store")
    @patch("app.tasks.autonomous.triage.log_task_event")
    def test_duplicate_logged_with_match_id(
        self,
        mock_log: MagicMock,
        mock_store: MagicMock,
        mock_dedup: MagicMock,
    ) -> None:
        """Rejection event includes the duplicate task ID."""
        mock_store.get_task.return_value = {"title": "Fix bug", "description": ""}

        triage_idea("task-new", "test-project")

        log_msg = mock_log.call_args[0][1]
        assert "task-dup123" in log_msg
        assert "deterministic" in log_msg.lower()

    @patch("app.tasks.autonomous.triage.duplicate_task_exists", return_value="task-dup123")
    @patch("app.tasks.autonomous.triage.task_store")
    @patch("app.tasks.autonomous.triage.log_task_event")
    def test_dedup_called_with_exclude_self(
        self,
        mock_log: MagicMock,
        mock_store: MagicMock,
        mock_dedup: MagicMock,
    ) -> None:
        """duplicate_task_exists is called with exclude_task_id=task_id."""
        mock_store.get_task.return_value = {"title": "Fix bug", "description": ""}

        triage_idea("task-self", "test-project")

        mock_dedup.assert_called_once_with("test-project", "Fix bug", exclude_task_id="task-self", description="")


class TestTriagePromptCleanup:
    """LLM prompt no longer contains active task context."""

    @patch("app.tasks.autonomous.triage.duplicate_task_exists", return_value=None)
    @patch("app.tasks.autonomous.triage.task_store")
    @patch("app.tasks.autonomous.triage.log_task_event")
    def test_no_active_context_in_prompt(
        self,
        mock_log: MagicMock,
        mock_store: MagicMock,
        mock_dedup: MagicMock,
    ) -> None:
        """When no duplicate found, LLM is called but without active task titles."""
        mock_store.get_task.return_value = {
            "title": "New unique task",
            "description": "Something new",
        }
        mock_store.list_tasks.return_value = [{"title": "Other task"}]

        mock_client = MagicMock()
        mock_client.complete.return_value = MagicMock(
            content='{"status": "READY", "objective": "Do thing", "done_when": [], "suggested_complexity": "SIMPLE", "priority": "medium", "reasoning": "ok"}'
        )

        with patch("app.tasks.autonomous.triage.get_sync_client", return_value=mock_client):
            triage_idea("task-new", "test-project")

        prompt = mock_client.complete.call_args[1].get("messages", [{}])[0].get("content", "")
        assert "Existing active/queued tasks" not in prompt
        assert "Check for duplicates" not in prompt


class TestParseTriageResponse:
    """Tests for _parse_triage_response."""

    def test_parse_valid_json(self) -> None:
        content = '{"status": "READY", "objective": "Fix the bug", "reasoning": "clear"}'
        result = _parse_triage_response(content)
        assert result["status"] == "READY"
        assert result["objective"] == "Fix the bug"

    def test_parse_json_with_surrounding_text(self) -> None:
        content = 'Here is my assessment:\n{"status": "REJECT", "reject_reason": "duplicate"}\nThat is all.'
        result = _parse_triage_response(content)
        assert result["status"] == "REJECT"

    def test_parse_invalid_json_returns_clarification(self) -> None:
        result = _parse_triage_response("This is not JSON at all")
        assert result["status"] == "NEEDS_CLARIFICATION"
