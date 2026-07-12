from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
import typer
from typer.testing import CliRunner

from cli.commands.done import _handle_task_completion, _refuse_if_autocode_owned, app

runner = CliRunner()


def test_refuse_when_task_is_claimed_by_autocode_dispatcher() -> None:
    task: dict[str, object] = {
        "id": "task-94c77a0a",
        "claimed_by": "api-dispatch-agent-hub",
        "lock_expires_at": "2026-05-11T16:34:11Z",
    }
    with (
        patch("cli.commands.done.output_error") as mock_error,
        pytest.raises(typer.Exit),
    ):
        _refuse_if_autocode_owned(task, "task-94c77a0a")
    assert mock_error.called
    msg = mock_error.call_args[0][0]
    assert "api-dispatch-agent-hub" in msg
    assert "dispatcher owns completion" in msg


def test_allow_when_claim_is_empty() -> None:
    _refuse_if_autocode_owned({"id": "task-x"}, "task-x")
    _refuse_if_autocode_owned({"id": "task-x", "claimed_by": None}, "task-x")
    _refuse_if_autocode_owned({"id": "task-x", "claimed_by": ""}, "task-x")


def test_allow_when_task_is_claimed_by_non_dispatch_worker() -> None:
    _refuse_if_autocode_owned({"id": "task-x", "claimed_by": "davion-sidarli"}, "task-x")
    _refuse_if_autocode_owned({"id": "task-x", "claimed_by": "worker-1"}, "task-x")


def test_already_completed_task_is_noop() -> None:
    """Idempotent close: `st done` on an already-completed task returns 0."""
    lookup_client = MagicMock()
    lookup_client.get_task.return_value = {
        "id": "task-1",
        "status": "completed",
        "project_id": "portfolio-ai",
    }
    with (
        patch("cli.commands.done.get_snapshot_info", return_value=None),
        patch("cli.commands.done.STClient") as client_cls,
        patch("cli.commands.done.preflight") as mock_gate,
        patch("cli.commands.done.complete_task") as mock_complete,
        patch("cli.commands.done.output_success") as mock_success,
    ):
        _handle_task_completion(lookup_client, "task-1", "done")

    mock_success.assert_called_once()
    assert "already complete" in mock_success.call_args[0][0]
    mock_complete.assert_not_called()
    mock_gate.assert_not_called()
    client_cls.assert_not_called()


def test_completed_task_with_checkpoint_retries_closeout() -> None:
    lookup_client = MagicMock()
    lookup_client.get_task.return_value = {
        "id": "task-1",
        "status": "completed",
        "project_id": "portfolio-ai",
    }
    project_client = MagicMock()

    with (
        patch("cli.commands.done.get_snapshot_info", return_value={"task_id": "task-1"}),
        patch("cli.commands.done.STClient", return_value=project_client),
        patch("cli.commands.done.preflight") as mock_gate,
        patch(
            "cli.commands.done.complete_task",
            return_value={"snapshot_removed": True, "base_branch": "main"},
        ) as mock_complete,
        patch("cli.commands.done.output_success"),
    ):
        _handle_task_completion(lookup_client, "task-1", "retry publish")

    mock_gate.assert_called_once_with("task-1", "portfolio-ai", op="done")
    mock_complete.assert_called_once_with(project_client, "task-1", "retry publish")


def test_task_completion_uses_task_project_client_after_global_lookup() -> None:
    lookup_client = MagicMock()
    lookup_client.get_task.return_value = {
        "id": "task-1",
        "status": "running",
        "project_id": "portfolio-ai",
    }
    project_client = MagicMock()

    with (
        patch("cli.commands.done.STClient", return_value=project_client) as client_cls,
        patch("cli.commands.done.preflight") as mock_gate,
        patch(
            "cli.commands.done.complete_task",
            return_value={"merged": False, "project_id": "portfolio-ai"},
        ) as mock_complete,
        patch("cli.commands.done.output_success"),
    ):
        _handle_task_completion(lookup_client, "task-1", "done")

    lookup_client.get_task.assert_called_once_with("task-1")
    client_cls.assert_called_once_with(project_id="portfolio-ai")
    mock_complete.assert_called_once_with(project_client, "task-1", "done")
    mock_gate.assert_called_once_with("task-1", "portfolio-ai", op="done")


def test_done_dotted_id_uses_subtask_completion_path() -> None:
    with (
        patch("cli.commands.done.STClient") as mock_client_cls,
        patch("cli.commands.done.complete_subtask") as mock_complete_subtask,
        patch("cli.commands.done.complete_task") as mock_complete_task,
        patch("cli.commands.done.output_success"),
    ):
        mock_complete_subtask.return_value = {"action": "completed"}
        result = runner.invoke(app, ["1.1", "--task", "task-parent"])

    assert result.exit_code == 0
    mock_client_cls.assert_called_once_with()
    mock_complete_subtask.assert_called_once_with(
        mock_client_cls.return_value,
        "1.1",
        "task-parent",
        None,
        citations=None,
        acknowledge_none=False,
    )
    mock_complete_task.assert_not_called()
