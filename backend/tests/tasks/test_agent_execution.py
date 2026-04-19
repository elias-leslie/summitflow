"""Tests for autonomous agent execution timeouts."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app.tasks.autonomous.exec_modules.agent_execution import (
    AUTOCODE_REQUEST_TIMEOUT_SECONDS,
    execute_agent_fix,
    execute_agent_initial,
)
from app.tasks.autonomous.exec_modules.agent_helpers import call_complete


def test_call_complete_passes_request_timeout_without_changing_payload_builder() -> None:
    """Autocode request timeout should be applied at the client call boundary."""
    client = MagicMock()
    client.complete.return_value = SimpleNamespace(content="done")
    built_kwargs = {"messages": [{"role": "user", "content": "hi"}], "project_id": "summitflow"}

    with patch(
        "app.tasks.autonomous.exec_modules.agent_helpers.build_complete_kwargs",
        return_value=built_kwargs,
    ) as build_kwargs:
        response = call_complete(
            client,
            prompt="Refactor this file",
            agent_slug="refactor",
            project_path="/tmp/task",
            project_id="summitflow",
            task_id="task-123",
            session_id="sess-1",
            max_turns=50,
            include_roles=["system", "autocode"],
            timeout_seconds=AUTOCODE_REQUEST_TIMEOUT_SECONDS,
        )

    assert response.content == "done"
    build_kwargs.assert_called_once()
    assert "timeout_seconds" not in built_kwargs
    client.complete.assert_called_once_with(
        messages=[{"role": "user", "content": "hi"}],
        project_id="summitflow",
        timeout_seconds=AUTOCODE_REQUEST_TIMEOUT_SECONDS,
    )


def test_execute_agent_initial_uses_extended_request_timeout() -> None:
    """Initial autocode runs should not inherit the 120s default client timeout."""
    response = SimpleNamespace(session_id="sess-1", content="done")

    with (
        patch("app.tasks.autonomous.exec_modules.agent_execution.get_sync_client", return_value=MagicMock()),
        patch("app.tasks.autonomous.exec_modules.agent_execution.create_session", return_value="sess-1"),
        patch("app.tasks.autonomous.exec_modules.agent_execution.call_complete", return_value=response) as call_complete_mock,
        patch("app.tasks.autonomous.exec_modules.agent_execution.update_session_if_changed", return_value="sess-1"),
        patch("app.tasks.autonomous.exec_modules.agent_execution.post_initial_response"),
        patch("app.tasks.autonomous.exec_modules.agent_execution.emit_log"),
    ):
        result, session_id = execute_agent_initial(
            task_id="task-123",
            subtask_short_id="1.1",
            prompt="Do the work",
            agent_slug="refactor",
            project_path="/tmp/task",
            project_id="summitflow",
        )

    assert result is response
    assert session_id == "sess-1"
    assert call_complete_mock.call_args.kwargs["timeout_seconds"] == AUTOCODE_REQUEST_TIMEOUT_SECONDS


def test_execute_agent_fix_uses_extended_request_timeout() -> None:
    """Fix attempts should keep the same long-running request timeout."""
    response = SimpleNamespace(session_id="sess-2", content="done")

    with (
        patch("app.tasks.autonomous.exec_modules.agent_execution.get_sync_client", return_value=MagicMock()),
        patch("app.tasks.autonomous.exec_modules.agent_execution.call_complete", return_value=response) as call_complete_mock,
        patch("app.tasks.autonomous.exec_modules.agent_execution.update_session_if_changed", return_value="sess-2"),
        patch("app.tasks.autonomous.exec_modules.agent_execution.post_fix_response", return_value="sess-2"),
        patch("app.tasks.autonomous.exec_modules.agent_execution.emit_log"),
    ):
        result, session_id = execute_agent_fix(
            task_id="task-123",
            subtask_short_id="1.1",
            fix_prompt="Try again",
            agent_slug="refactor",
            project_path="/tmp/task",
            project_id="summitflow",
            agent_session_id="sess-1",
        )

    assert result is response
    assert session_id == "sess-2"
    assert call_complete_mock.call_args.kwargs["timeout_seconds"] == AUTOCODE_REQUEST_TIMEOUT_SECONDS
