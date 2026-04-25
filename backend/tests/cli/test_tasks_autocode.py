from __future__ import annotations

from unittest.mock import MagicMock, patch

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
