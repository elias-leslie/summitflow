"""Tests for notification storage layer.

Covers deduplication logic, Johnny-branded convenience functions,
and create_notification fundamentals.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from app.storage.notifications import (
    _is_duplicate,
    create_task_completion_notification,
    create_task_failure_notification,
)


class TestIsDuplicate:
    """Tests for _is_duplicate() dedup check."""

    @patch("app.storage.notifications.get_connection")
    def test_no_existing_notification_not_duplicate(self, mock_conn: MagicMock) -> None:
        """First notification of its kind is never a duplicate."""
        cursor = MagicMock()
        cursor.fetchone.return_value = None
        mock_conn.return_value.__enter__ = lambda s: MagicMock(cursor=lambda: MagicMock(__enter__=lambda s: cursor, __exit__=lambda *a: None))
        mock_conn.return_value.__exit__ = lambda *a: None

        # Properly mock the context manager chain
        ctx = MagicMock()
        cur = MagicMock()
        cur.fetchone.return_value = None
        ctx.cursor.return_value.__enter__ = lambda s: cur
        ctx.cursor.return_value.__exit__ = lambda *a: None
        mock_conn.return_value.__enter__ = lambda s: ctx
        mock_conn.return_value.__exit__ = lambda *a: None

        result = _is_duplicate("proj-1", "task_failed", "error", "task-1")
        assert result is False

    @patch("app.storage.notifications.get_connection")
    def test_existing_same_severity_is_duplicate(self, mock_conn: MagicMock) -> None:
        """Same type+task+severity within window is a duplicate."""
        cur = MagicMock()
        cur.fetchone.return_value = ("error",)  # existing with same severity
        ctx = MagicMock()
        ctx.cursor.return_value.__enter__ = lambda s: cur
        ctx.cursor.return_value.__exit__ = lambda *a: None
        mock_conn.return_value.__enter__ = lambda s: ctx
        mock_conn.return_value.__exit__ = lambda *a: None

        result = _is_duplicate("proj-1", "task_failed", "error", "task-1")
        assert result is True

    @patch("app.storage.notifications.get_connection")
    def test_severity_escalation_not_duplicate(self, mock_conn: MagicMock) -> None:
        """Higher severity for same task is NOT a duplicate (escalation)."""
        cur = MagicMock()
        cur.fetchone.return_value = ("warning",)  # existing is warning
        ctx = MagicMock()
        ctx.cursor.return_value.__enter__ = lambda s: cur
        ctx.cursor.return_value.__exit__ = lambda *a: None
        mock_conn.return_value.__enter__ = lambda s: ctx
        mock_conn.return_value.__exit__ = lambda *a: None

        result = _is_duplicate("proj-1", "task_failed", "error", "task-1")
        assert result is False  # error > warning → not a dup

    @patch("app.storage.notifications.get_connection")
    def test_severity_downgrade_is_duplicate(self, mock_conn: MagicMock) -> None:
        """Lower severity for same task IS a duplicate."""
        cur = MagicMock()
        cur.fetchone.return_value = ("error",)  # existing is error
        ctx = MagicMock()
        ctx.cursor.return_value.__enter__ = lambda s: cur
        ctx.cursor.return_value.__exit__ = lambda *a: None
        mock_conn.return_value.__enter__ = lambda s: ctx
        mock_conn.return_value.__exit__ = lambda *a: None

        result = _is_duplicate("proj-1", "task_failed", "warning", "task-1")
        assert result is True  # warning < error → dup

    def test_system_notifications_never_deduped(self) -> None:
        """System notifications bypass dedup entirely."""
        # No DB mock needed — should return False before any query
        result = _is_duplicate("proj-1", "system", "error")
        assert result is False


class TestCreateTaskFailureNotification:
    """Tests for Johnny-branded task failure notifications."""

    @patch("app.storage.notifications._schedule_delivery")
    @patch("app.storage.notifications._is_duplicate", return_value=False)
    @patch("app.storage.notifications.get_connection")
    def test_johnny_voice_in_message(
        self, mock_conn: MagicMock, mock_dedup: MagicMock, mock_delivery: MagicMock
    ) -> None:
        """Failure notification uses first-person Johnny voice."""
        cur = MagicMock()
        row = (
            "notif-1", "proj-1", "task-1", None, None,
            "task_failed", "Task failed: Fix login",
            "I was working on 'Fix login' but hit a problem: Build error. Tap to chat about next steps.",
            "error", "pending", {"johnny": True}, None, None, None,
        )
        cur.fetchone.return_value = row
        ctx = MagicMock()
        ctx.cursor.return_value.__enter__ = lambda s: cur
        ctx.cursor.return_value.__exit__ = lambda *a: None
        mock_conn.return_value.__enter__ = lambda s: ctx
        mock_conn.return_value.__exit__ = lambda *a: None

        create_task_failure_notification(
            project_id="proj-1",
            task_id="task-1",
            task_title="Fix login",
            error_message="Build error.",
        )

        # Verify the SQL was called with Johnny-branded text
        call_args = cur.execute.call_args
        params = call_args[0][1]
        title = params[5]  # title param
        message = params[6]  # message param
        assert title == "Task failed: Fix login"
        assert "I was working on" in message
        assert "Tap to chat" in message

    @patch("app.storage.notifications._schedule_delivery")
    @patch("app.storage.notifications._is_duplicate", return_value=False)
    @patch("app.storage.notifications.get_connection")
    def test_session_ids_in_metadata(
        self, mock_conn: MagicMock, mock_dedup: MagicMock, mock_delivery: MagicMock
    ) -> None:
        """Session IDs are included in notification metadata."""
        cur = MagicMock()
        cur.fetchone.return_value = (
            "notif-1", "proj-1", "task-1", None, None,
            "task_failed", "title", "msg",
            "error", "pending",
            {"johnny": True, "agent_hub_session_ids": ["sess-1", "sess-2"]},
            None, None, None,
        )
        ctx = MagicMock()
        ctx.cursor.return_value.__enter__ = lambda s: cur
        ctx.cursor.return_value.__exit__ = lambda *a: None
        mock_conn.return_value.__enter__ = lambda s: ctx
        mock_conn.return_value.__exit__ = lambda *a: None

        create_task_failure_notification(
            project_id="proj-1",
            task_id="task-1",
            task_title="Test",
            error_message="Error.",
            agent_hub_session_ids=["sess-1", "sess-2"],
        )

        call_args = cur.execute.call_args
        import json

        metadata_json = call_args[0][1][8]  # metadata param (9th positional)
        metadata = json.loads(metadata_json)
        assert metadata["johnny"] is True
        assert metadata["agent_hub_session_ids"] == ["sess-1", "sess-2"]


class TestCreateTaskCompletionNotification:
    """Tests for Johnny-branded task completion notifications."""

    @patch("app.storage.notifications._schedule_delivery")
    @patch("app.storage.notifications._is_duplicate", return_value=False)
    @patch("app.storage.notifications.get_connection")
    def test_completion_uses_warning_severity(
        self, mock_conn: MagicMock, mock_dedup: MagicMock, mock_delivery: MagicMock
    ) -> None:
        """Completion notifications use 'warning' severity to trigger push."""
        cur = MagicMock()
        cur.fetchone.return_value = (
            "notif-1", "proj-1", "task-1", None, None,
            "task_completed", "Task done: Deploy", "Finished 'Deploy'...",
            "warning", "pending", {"johnny": True}, None, None, None,
        )
        ctx = MagicMock()
        ctx.cursor.return_value.__enter__ = lambda s: cur
        ctx.cursor.return_value.__exit__ = lambda *a: None
        mock_conn.return_value.__enter__ = lambda s: ctx
        mock_conn.return_value.__exit__ = lambda *a: None

        create_task_completion_notification(
            project_id="proj-1",
            task_id="task-1",
            task_title="Deploy",
        )

        call_args = cur.execute.call_args
        params = call_args[0][1]
        severity = params[7]
        assert severity == "warning"

    @patch("app.storage.notifications._schedule_delivery")
    @patch("app.storage.notifications._is_duplicate", return_value=False)
    @patch("app.storage.notifications.get_connection")
    def test_completion_johnny_voice(
        self, mock_conn: MagicMock, mock_dedup: MagicMock, mock_delivery: MagicMock
    ) -> None:
        """Completion notification uses Johnny's voice."""
        cur = MagicMock()
        cur.fetchone.return_value = (
            "notif-1", "proj-1", "task-1", None, None,
            "task_completed", "Task done: Deploy",
            "Finished 'Deploy' — all checks passed. Tap to review.",
            "warning", "pending", {"johnny": True}, None, None, None,
        )
        ctx = MagicMock()
        ctx.cursor.return_value.__enter__ = lambda s: cur
        ctx.cursor.return_value.__exit__ = lambda *a: None
        mock_conn.return_value.__enter__ = lambda s: ctx
        mock_conn.return_value.__exit__ = lambda *a: None

        create_task_completion_notification(
            project_id="proj-1",
            task_id="task-1",
            task_title="Deploy",
            detail="Auto-merged.",
        )

        call_args = cur.execute.call_args
        params = call_args[0][1]
        title = params[5]
        message = params[6]
        assert title == "Task done: Deploy"
        assert "Finished" in message
        assert "Auto-merged." in message

    @patch("app.storage.notifications._schedule_delivery")
    @patch("app.storage.notifications._is_duplicate", return_value=True)
    @patch("app.storage.notifications.get_connection")
    def test_dedup_returns_empty_dict(
        self, mock_conn: MagicMock, mock_dedup: MagicMock, mock_delivery: MagicMock
    ) -> None:
        """Deduplicated notifications return empty dict without DB insert."""
        result = create_task_completion_notification(
            project_id="proj-1",
            task_id="task-1",
            task_title="Deploy",
        )

        assert result == {}
        # Verify no DB call was made
        mock_conn.return_value.__enter__.assert_not_called()
