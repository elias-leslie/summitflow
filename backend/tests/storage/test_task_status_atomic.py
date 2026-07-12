from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.storage.tasks import status as task_status


def test_transition_validation_locks_row_before_rejecting_update() -> None:
    """Validation and mutation must share one locked transaction."""
    cursor = MagicMock()
    cursor.fetchone.return_value = ("completed",)
    cursor_context = MagicMock()
    cursor_context.__enter__.return_value = cursor
    connection = MagicMock()
    connection.cursor.return_value = cursor_context
    connection_context = MagicMock()
    connection_context.__enter__.return_value = connection

    with (
        patch.object(task_status, "get_connection", return_value=connection_context),
        pytest.raises(ValueError, match="Invalid transition"),
    ):
        task_status.update_task_status("task-12345678", "running")

    cursor.execute.assert_called_once_with(
        "SELECT status FROM tasks WHERE id = %s FOR UPDATE",
        ("task-12345678",),
    )
    connection.commit.assert_not_called()
