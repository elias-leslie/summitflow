"""Test and execution operation mixins for STClient."""

from __future__ import annotations

from typing import Any

from . import _client_execution as exec_ops
from . import _client_tests as tests_ops


class TestOperationsMixin:
    """Mixin providing test operations."""

    _client: Any
    _url: Any
    _handle_response: Any

    def list_tests(self, test_type: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
        return tests_ops.list_tests(
            self._client, self._url, self._handle_response, test_type, limit
        )

    def import_tests(self, framework: str) -> dict[str, Any]:
        return tests_ops.import_tests(self._client, self._url, self._handle_response, framework)


class ExecutionOperationsMixin:
    """Mixin providing execution and session operations."""

    _client: Any
    _url: Any
    _handle_response: Any
    base_url: str
    get_task: Any

    def get_autonomous_settings(self) -> dict[str, Any]:
        return exec_ops.get_autonomous_settings(self._client, self._url, self._handle_response)

    def update_autonomous_settings(self, **updates: Any) -> dict[str, Any]:
        return exec_ops.update_autonomous_settings(
            self._client, self._url, self._handle_response, **updates
        )

    def list_sessions(self) -> list[dict[str, Any]]:
        return exec_ops.list_sessions(self._client, self._url, self._handle_response)

    def get_session(self, session_id: str) -> dict[str, Any]:
        return exec_ops.get_session(self._client, self._url, self._handle_response, session_id)

    def get_task_agent_events(
        self,
        task_id: str,
        event_type: str | None = None,
        turn: int | None = None,
        page: int = 1,
        page_size: int = 500,
    ) -> dict[str, Any]:
        task = self.get_task(task_id)
        project_id = task.get("project_id", "")
        return exec_ops.get_task_agent_events(
            self._client,
            self.base_url,
            self._handle_response,
            project_id,
            task_id,
            event_type,
            turn,
            page,
            page_size,
        )

    def get_events(
        self, project_id: str, task_id: str, limit: int = 50, include_debug: bool = False
    ) -> dict[str, Any]:
        return exec_ops.get_events(
            self._client,
            self.base_url,
            self._handle_response,
            project_id,
            task_id,
            limit,
            include_debug,
        )
