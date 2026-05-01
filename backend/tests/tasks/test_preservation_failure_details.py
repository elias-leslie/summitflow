from __future__ import annotations

from unittest.mock import MagicMock, patch


def test_checkout_setup_logs_preservation_failure_detail() -> None:
    from app.tasks.autonomous.exec_modules.checkout_setup import setup_task_checkout

    checkout = MagicMock(branch="task-1/main")
    with (
        patch("app.tasks.autonomous.exec_modules.checkout_setup.create_task_checkout", return_value=checkout),
        patch("app.tasks.autonomous.exec_modules.checkout_setup.get_project_path", return_value="/repo"),
        patch("app.tasks.autonomous.exec_modules.checkout_setup.has_uncommitted_changes", return_value=True),
        patch(
            "app.tasks.autonomous.exec_modules.checkout_setup.smart_commit_result",
            return_value={
                "success": False,
                "detail": "commit helper failed: st commit --task task-1; stderr: rejected",
            },
        ),
        patch("app.tasks.autonomous.exec_modules.checkout_setup.emit_log") as mock_log,
    ):
        result = setup_task_checkout("task-1", "summitflow")

    assert result == "/repo"
    messages = [call.args[2] for call in mock_log.call_args_list]
    assert any("stderr: rejected" in message for message in messages)


def test_subtask_commit_logs_preservation_failure_detail() -> None:
    from app.tasks.autonomous.exec_modules.execution_loop import _commit_subtask_changes

    with (
        patch("app.tasks.autonomous.exec_modules.execution_loop.has_uncommitted_changes", return_value=True),
        patch(
            "app.tasks.autonomous.exec_modules.execution_loop.smart_commit_result",
            return_value={
                "success": False,
                "detail": "commit helper failed: st commit --task task-1; stderr: checks failed",
            },
        ),
        patch("app.tasks.autonomous.exec_modules.execution_loop.emit_log") as mock_log,
    ):
        _commit_subtask_changes(
            "/repo",
            "task-1",
            "summitflow",
            {"subtask_id": "1.2", "description": "Change checkout"},
            "completed",
        )

    mock_log.assert_called_once()
    assert "1.2" in mock_log.call_args.args[2]
    assert "stderr: checks failed" in mock_log.call_args.args[2]
