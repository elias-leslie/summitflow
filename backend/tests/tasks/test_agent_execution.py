"""Tests for autonomous agent execution client calls."""

from __future__ import annotations

from types import SimpleNamespace
from typing import cast
from unittest.mock import MagicMock, patch

from agent_hub import CompletionResponse

from app.tasks.autonomous.exec_modules.agent_execution import (
    execute_agent_initial,
)
from app.tasks.autonomous.exec_modules.agent_helpers import (
    agent_completion_failure,
    call_complete,
    log_initial_completion_fallback,
    record_citations,
)
from app.tasks.autonomous.exec_modules.interruption import ExecutionInterrupted


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


def test_call_complete_retries_transient_agent_hub_disconnect() -> None:
    client = MagicMock()
    client.complete.side_effect = [
        ConnectionError("Server disconnected without sending a response."),
        ConnectionError("[Errno 111] Connection refused"),
        SimpleNamespace(content="done"),
    ]
    built_kwargs = {"messages": [{"role": "user", "content": "hi"}], "project_id": "agent-hub"}

    with (
        patch(
            "app.tasks.autonomous.exec_modules.agent_helpers.build_complete_kwargs",
            return_value=built_kwargs,
        ),
        patch("app.tasks.autonomous.exec_modules.agent_helpers.get_task", return_value={"status": "running"}),
        patch("app.tasks.autonomous.exec_modules.agent_helpers.sleep") as sleep_mock,
        patch("app.tasks.autonomous.exec_modules.agent_helpers.emit_log") as emit_log_mock,
    ):
        response = call_complete(
            client,
            prompt="Fix ownership",
            agent_slug="coder",
            project_path="/tmp/task",
            project_id="agent-hub",
            task_id="task-123",
            session_id="sess-1",
            include_roles=["system", "autocode"],
        )

    assert response.content == "done"
    assert client.complete.call_count == 3
    assert [call.args[0] for call in sleep_mock.call_args_list] == [2.0, 4.0]
    assert emit_log_mock.call_count == 2


def test_call_complete_keeps_retrying_transient_agent_hub_disconnect_past_old_cap() -> None:
    client = MagicMock()
    client.complete.side_effect = [
        ConnectionError("Server disconnected without sending a response."),
        ConnectionError("Server disconnected without sending a response."),
        ConnectionError("Server disconnected without sending a response."),
        ConnectionError("Server disconnected without sending a response."),
        ConnectionError("Server disconnected without sending a response."),
        ConnectionError("Server disconnected without sending a response."),
        SimpleNamespace(content="done"),
    ]
    built_kwargs = {"messages": [{"role": "user", "content": "hi"}], "project_id": "agent-hub"}

    with (
        patch(
            "app.tasks.autonomous.exec_modules.agent_helpers.build_complete_kwargs",
            return_value=built_kwargs,
        ),
        patch("app.tasks.autonomous.exec_modules.agent_helpers.get_task", return_value={"status": "running"}),
        patch("app.tasks.autonomous.exec_modules.agent_helpers.sleep") as sleep_mock,
        patch("app.tasks.autonomous.exec_modules.agent_helpers.emit_log"),
    ):
        response = call_complete(
            client,
            prompt="Fix ownership",
            agent_slug="coder",
            project_path="/tmp/task",
            project_id="agent-hub",
            task_id="task-123",
            session_id="sess-1",
        )

    assert response.content == "done"
    assert client.complete.call_count == 7
    assert [call.args[0] for call in sleep_mock.call_args_list] == [2.0, 4.0, 8.0, 16.0, 16.0, 16.0]


def test_call_complete_retries_transient_interrupted_response() -> None:
    client = MagicMock()
    client.complete.side_effect = [
        SimpleNamespace(
            content="Session interrupted: Error: Completion cancelled unexpectedly.",
            finish_reason="error",
        ),
        SimpleNamespace(content="done", finish_reason="end_turn"),
    ]
    built_kwargs = {"messages": [{"role": "user", "content": "hi"}], "project_id": "agent-hub"}

    with (
        patch(
            "app.tasks.autonomous.exec_modules.agent_helpers.build_complete_kwargs",
            return_value=built_kwargs,
        ),
        patch("app.tasks.autonomous.exec_modules.agent_helpers.get_task", return_value={"status": "running"}),
        patch("app.tasks.autonomous.exec_modules.agent_helpers.add_agent_hub_session") as add_session_mock,
        patch("app.tasks.autonomous.exec_modules.agent_helpers.sleep") as sleep_mock,
        patch("app.tasks.autonomous.exec_modules.agent_helpers.emit_log") as emit_log_mock,
    ):
        response = call_complete(
            client,
            prompt="Fix ownership",
            agent_slug="coder",
            project_path="/tmp/task",
            project_id="agent-hub",
            task_id="task-123",
            session_id="sess-1",
        )

    assert response.content == "done"
    assert client.complete.call_count == 2
    assert client.complete.call_args.kwargs["session_id"] != "sess-1"
    add_session_mock.assert_called_once()
    sleep_mock.assert_called_once_with(2.0)
    assert "transient interruption" in emit_log_mock.call_args.args[2]


def test_call_complete_retries_missing_final_summary_response() -> None:
    client = MagicMock()
    client.complete.side_effect = [
        SimpleNamespace(
            content="Tool activity recorded without a final assistant summary. Tools: bash.",
            finish_reason="end_turn",
        ),
        SimpleNamespace(content="done", finish_reason="end_turn"),
    ]
    built_kwargs = {
        "messages": [{"role": "user", "content": "hi"}],
        "project_id": "agent-hub",
        "session_id": "sess-1",
    }

    with (
        patch(
            "app.tasks.autonomous.exec_modules.agent_helpers.build_complete_kwargs",
            return_value=built_kwargs,
        ),
        patch("app.tasks.autonomous.exec_modules.agent_helpers.get_task", return_value={"status": "running"}),
        patch("app.tasks.autonomous.exec_modules.agent_helpers.add_agent_hub_session"),
        patch("app.tasks.autonomous.exec_modules.agent_helpers.sleep") as sleep_mock,
        patch("app.tasks.autonomous.exec_modules.agent_helpers.emit_log"),
    ):
        response = call_complete(
            client,
            prompt="Fix ownership",
            agent_slug="coder",
            project_path="/tmp/task",
            project_id="agent-hub",
            task_id="task-123",
            session_id="sess-1",
        )

    assert response.content == "done"
    assert client.complete.call_count == 2
    sleep_mock.assert_called_once_with(2.0)


def test_call_complete_aborts_transient_retry_when_task_is_paused() -> None:
    client = MagicMock()
    client.complete.return_value = SimpleNamespace(
        content="Session interrupted: Error: Completion cancelled unexpectedly.",
        finish_reason="error",
    )
    built_kwargs = {
        "messages": [{"role": "user", "content": "hi"}],
        "project_id": "agent-hub",
        "session_id": "sess-1",
    }

    with (
        patch(
            "app.tasks.autonomous.exec_modules.agent_helpers.build_complete_kwargs",
            return_value=built_kwargs,
        ),
        patch("app.tasks.autonomous.exec_modules.agent_helpers.get_task", return_value={"status": "paused"}),
        patch("app.tasks.autonomous.exec_modules.agent_helpers.add_agent_hub_session") as add_session_mock,
        patch("app.tasks.autonomous.exec_modules.agent_helpers.sleep") as sleep_mock,
        patch("app.tasks.autonomous.exec_modules.agent_helpers.emit_log"),
    ):
        try:
            call_complete(
                client,
                prompt="Fix ownership",
                agent_slug="coder",
                project_path="/tmp/task",
                project_id="agent-hub",
                task_id="task-123",
                session_id="sess-1",
            )
        except ExecutionInterrupted as exc:
            assert exc.status == "paused"
        else:
            raise AssertionError("expected ExecutionInterrupted")

    client.complete.assert_called_once()
    add_session_mock.assert_not_called()
    sleep_mock.assert_not_called()


def test_call_complete_does_not_retry_non_transient_interrupted_response() -> None:
    client = MagicMock()
    response = SimpleNamespace(
        content="Session interrupted: Repeated identical tool result 5 times for bash",
        finish_reason="error",
    )
    client.complete.return_value = response

    with (
        patch(
            "app.tasks.autonomous.exec_modules.agent_helpers.build_complete_kwargs",
            return_value={"messages": []},
        ),
        patch("app.tasks.autonomous.exec_modules.agent_helpers.sleep") as sleep_mock,
        patch("app.tasks.autonomous.exec_modules.agent_helpers.emit_log") as emit_log_mock,
    ):
        result = call_complete(
            client,
            prompt="Fix ownership",
            agent_slug="coder",
            project_path="/tmp/task",
            project_id="agent-hub",
            task_id="task-123",
            session_id="sess-1",
        )

    assert result is response
    client.complete.assert_called_once()
    sleep_mock.assert_not_called()
    emit_log_mock.assert_not_called()


def test_call_complete_does_not_retry_non_transient_error() -> None:
    client = MagicMock()
    client.complete.side_effect = ValueError("bad request")

    with (
        patch(
            "app.tasks.autonomous.exec_modules.agent_helpers.build_complete_kwargs",
            return_value={"messages": []},
        ),
        patch("app.tasks.autonomous.exec_modules.agent_helpers.sleep") as sleep_mock,
    ):
        try:
            call_complete(
                client,
                prompt="Fix ownership",
                agent_slug="coder",
                project_path="/tmp/task",
                project_id="agent-hub",
                task_id="task-123",
                session_id="sess-1",
            )
        except ValueError:
            pass
        else:
            raise AssertionError("expected ValueError")

    client.complete.assert_called_once()
    sleep_mock.assert_not_called()


def test_agent_completion_failure_detects_interrupted_tool_loop() -> None:
    response = MagicMock()
    response.content = "Session interrupted: Repeated identical tool result 5 times for bash"
    response.finish_reason = "error"

    failure = agent_completion_failure(response)

    assert failure is not None
    assert "Repeated identical tool result" in failure


def test_agent_completion_failure_detects_missing_final_summary() -> None:
    response = MagicMock()
    response.content = "Tool activity recorded without a final assistant summary. Tools: bash."
    response.finish_reason = "end_turn"

    failure = agent_completion_failure(response)

    assert failure is not None
    assert "without a final assistant summary" in failure


def test_log_initial_completion_fallback_does_not_mark_interrupted_session_complete() -> None:
    response = MagicMock()
    response.content = "Session interrupted: Repeated identical tool result 5 times for bash"
    response.finish_reason = "error"
    response.progress_log = None

    with patch("app.tasks.autonomous.exec_modules.agent_helpers.emit_log") as emit_log:
        log_initial_completion_fallback("task-123", "1.1", response, "summitflow")

    messages = [call.args[2] for call in emit_log.call_args_list]
    assert any("Agent interrupted subtask 1.1" in message for message in messages)
    assert not any(message == "Agent completed subtask 1.1" for message in messages)


def test_record_citations_skips_synthetic_task_unit() -> None:
    response = cast(CompletionResponse, SimpleNamespace(cited_uuids=["M:abc12345"]))

    with (
        patch("app.tasks.autonomous.exec_modules.agent_helpers.get_subtask", return_value=None),
        patch("app.tasks.autonomous.exec_modules.agent_helpers.log_citations") as log_citations,
        patch("app.tasks.autonomous.exec_modules.agent_helpers.acknowledge_no_citations") as acknowledge,
    ):
        record_citations("task-123", "task", response)

    log_citations.assert_not_called()
    acknowledge.assert_not_called()


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
