"""Tests for autonomous agent execution client calls."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app.tasks.autonomous.exec_modules.agent_execution import (
    execute_agent_fix,
    execute_agent_initial,
)
from app.tasks.autonomous.exec_modules.agent_helpers import call_complete


def test_call_complete_omits_request_timeout_by_default() -> None:
    """Autocode should let Agent Hub handle long-running agentic loops."""
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
            include_roles=["system", "autocode"],
        )

    assert response.content == "done"
    build_kwargs.assert_called_once()
    assert "timeout_seconds" not in built_kwargs
    client.complete.assert_called_once_with(
        messages=[{"role": "user", "content": "hi"}],
        project_id="summitflow",
    )


def test_execute_agent_initial_does_not_set_request_timeout() -> None:
    """Initial autocode runs should not impose a local HTTP timeout ceiling."""
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
    assert "timeout_seconds" not in call_complete_mock.call_args.kwargs


def test_execute_agent_fix_does_not_set_request_timeout() -> None:
    """Fix attempts should not impose a local HTTP timeout ceiling."""
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
    assert "timeout_seconds" not in call_complete_mock.call_args.kwargs
