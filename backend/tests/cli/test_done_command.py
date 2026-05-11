from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
import typer

from cli.commands.done import _handle_task_completion, _refuse_if_autocode_owned


def test_refuse_when_task_is_actively_claimed() -> None:
    task: dict[str, object] = {
        "id": "task-94c77a0a",
        "claimed_by": "api-dispatch-agent-hub",
        "lock_expires_at": "2026-05-11T16:34:11Z",
    }
    with (
        patch("cli.commands.done.output_error") as mock_error,
        pytest.raises(typer.Exit),
    ):
        _refuse_if_autocode_owned(task, "task-94c77a0a", admin=False)
    assert mock_error.called
    msg = mock_error.call_args[0][0]
    assert "api-dispatch-agent-hub" in msg
    assert "orchestrator owns completion" in msg


def test_allow_when_claim_is_empty() -> None:
    _refuse_if_autocode_owned({"id": "task-x"}, "task-x", admin=False)
    _refuse_if_autocode_owned({"id": "task-x", "claimed_by": None}, "task-x", admin=False)
    _refuse_if_autocode_owned({"id": "task-x", "claimed_by": ""}, "task-x", admin=False)


def test_admin_override_bypasses_claim_check() -> None:
    task: dict[str, object] = {"id": "task-x", "claimed_by": "api-dispatch-agent-hub"}
    _refuse_if_autocode_owned(task, "task-x", admin=True)


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
