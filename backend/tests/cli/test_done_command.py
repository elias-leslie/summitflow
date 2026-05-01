from __future__ import annotations

from unittest.mock import MagicMock, patch

from cli.commands.done import _handle_task_completion


def test_task_completion_uses_task_project_client_after_global_lookup() -> None:
    lookup_client = MagicMock()
    lookup_client.get_task.return_value = {"id": "task-1", "project_id": "portfolio-ai"}
    project_client = MagicMock()

    with (
        patch("cli.commands.done.STClient", return_value=project_client) as client_cls,
        patch("cli.commands.done.require_pulse_gate") as mock_gate,
        patch(
            "cli.commands.done.complete_task",
            return_value={"merged": False, "project_id": "portfolio-ai"},
        ) as mock_complete,
        patch("cli.commands.done.output_success"),
    ):
        _handle_task_completion(
            lookup_client,
            "task-1",
            "done",
            strict=False,
            admin=True,
            skip_diff_gate=True,
        )

    lookup_client.get_task.assert_called_once_with("task-1")
    client_cls.assert_called_once_with(project_id="portfolio-ai")
    mock_complete.assert_called_once_with(
        project_client,
        "task-1",
        "done",
        strict=False,
        admin=True,
        skip_diff_gate=True,
    )
    mock_gate.assert_any_call("portfolio-ai", allow_task_id="task-1")
