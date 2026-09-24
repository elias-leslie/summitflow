from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
import typer

from cli.commands.tasks_autocode import autocode_task


@patch("cli.commands.tasks_autocode.output_json")
def test_autocode_pending_task_calls_execute_endpoint(mock_output_json: MagicMock) -> None:
    client = MagicMock()
    client.project_id = "summitflow"
    client.get_task.return_value = {"id": "task-123", "project_id": "summitflow", "status": "pending"}
    client.get_subtasks.return_value = {"subtasks": []}
    client.validate_ready.return_value = {"ready": True}
    client.execute_task.return_value = {"id": "task-123", "status": "pending"}

    autocode_task("task-123", dry_run=False, at=None, client=client)

    client.execute_task.assert_called_once_with("task-123")
    client.update_status.assert_not_called()
    result = mock_output_json.call_args.args[0]
    assert result["task_id"] == "task-123"
    assert result["status"] == "queued"
    assert result["dispatch"] == "immediate"


@pytest.mark.parametrize("dry_run", [False, True])
def test_autocode_at_refuses_before_any_client_call(dry_run: bool) -> None:
    client = MagicMock()

    with (
        patch("cli.commands.tasks_autocode.output_error") as output_error,
        pytest.raises(typer.Exit) as exc,
    ):
        autocode_task("task-123", dry_run=dry_run, at="in 1h", client=client)

    assert exc.value.exit_code == 2
    output_error.assert_called_once_with(
        "Scheduled autocode is unavailable. Omit --at to queue the task now."
    )
    assert client.mock_calls == []
