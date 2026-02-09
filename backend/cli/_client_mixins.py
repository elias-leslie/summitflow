"""Mixins providing method delegations for STClient."""

from __future__ import annotations

from typing import Any

from . import _client_dependencies as deps_ops
from . import _client_execution as exec_ops
from . import _client_steps as steps_ops
from . import _client_subtasks as subtasks_ops
from . import _client_tasks as tasks_ops
from . import _client_tests as tests_ops


class TaskOperationsMixin:
    """Mixin providing task-related operations."""

    # Implemented by BaseHTTPClient
    _client: Any
    _url: Any
    _global_url: Any
    _handle_response: Any

    def create_task(self, data: dict[str, Any]) -> dict[str, Any]:
        return tasks_ops.create_task(self._client, self._url, self._handle_response, data)

    def batch_create_tasks(self, items: list[dict[str, Any]]) -> dict[str, Any]:
        return tasks_ops.batch_create_tasks(self._client, self._url, self._handle_response, items)

    def get_task(self, task_id: str) -> dict[str, Any]:
        return tasks_ops.get_task(self._client, self._global_url, self._handle_response, task_id)

    def list_tasks(
        self,
        status: str | None = None,
        task_type: str | None = None,
        priority: int | None = None,
        labels: list[str] | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> dict[str, Any]:
        return tasks_ops.list_tasks(
            self._client,
            self._url,
            self._handle_response,
            status,
            task_type,
            priority,
            labels,
            limit,
            offset,
        )

    def list_ready(self, limit: int = 50) -> dict[str, Any]:
        return tasks_ops.list_ready(self._client, self._url, self._handle_response, limit)

    def update_task(self, task_id: str, **updates: Any) -> dict[str, Any]:
        return tasks_ops.update_task(
            self._client, self._url, self._handle_response, task_id, **updates
        )

    def update_status(
        self,
        task_id: str,
        status: str,
        error_message: str | None = None,
        reason: str | None = None,
        skip_gates: bool = False,
    ) -> dict[str, Any]:
        return tasks_ops.update_status(
            self._client,
            self._url,
            self._handle_response,
            task_id,
            status,
            error_message,
            reason,
            skip_gates,
        )

    def close_task(self, task_id: str, reason: str | None = None) -> dict[str, Any]:
        return self.update_status(task_id, "completed", reason=reason, skip_gates=True)

    def cancel_task(self, task_id: str) -> dict[str, Any]:
        return self.update_status(task_id, "cancelled")

    def delete_task(self, task_id: str) -> dict[str, Any]:
        return tasks_ops.delete_task(self._client, self._url, self._handle_response, task_id)

    def claim_task(
        self, task_id: str, lock_minutes: int = 30, worker_id: str | None = None
    ) -> dict[str, Any]:
        return tasks_ops.claim_task(
            self._client, self._url, self._handle_response, task_id, lock_minutes, worker_id
        )

    def release_task(self, task_id: str) -> dict[str, Any]:
        return tasks_ops.release_task(self._client, self._url, self._handle_response, task_id)

    def append_log(self, task_id: str, entry: str) -> dict[str, Any]:
        return tasks_ops.append_log(
            self._client, self._global_url, self._handle_response, task_id, entry
        )


class DependencyOperationsMixin:
    """Mixin providing dependency operations."""

    _client: Any
    _url: Any
    _global_url: Any
    _handle_response: Any

    def add_dependency(
        self, task_id: str, depends_on: str, dep_type: str = "blocks"
    ) -> dict[str, Any]:
        return deps_ops.add_dependency(
            self._client, self._url, self._handle_response, task_id, depends_on, dep_type
        )

    def list_dependencies(self, task_id: str) -> list[dict[str, Any]]:
        return deps_ops.list_dependencies(
            self._client, self._global_url, self._handle_response, task_id
        )

    def remove_dependency(
        self, task_id: str, depends_on: str, dep_type: str | None = None
    ) -> dict[str, Any]:
        return deps_ops.remove_dependency(
            self._client, self._url, self._handle_response, task_id, depends_on, dep_type
        )


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


class SubtaskOperationsMixin:
    """Mixin providing subtask operations."""

    _client: Any
    _url: Any
    _global_url: Any
    _handle_response: Any

    def get_subtasks(self, task_id: str, include_steps: bool = False) -> dict[str, Any]:
        return subtasks_ops.get_subtasks(
            self._client, self._global_url, self._handle_response, task_id, include_steps
        )

    def create_subtask(
        self,
        task_id: str,
        subtask_id: str,
        description: str,
        phase: str = "implementation",
        steps: list[str | dict[str, Any]] | None = None,
        details: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return subtasks_ops.create_subtask(
            self._client,
            self._url,
            self._handle_response,
            task_id,
            subtask_id,
            description,
            phase,
            steps,
            details,
        )

    def bulk_create_subtasks(self, task_id: str, subtasks: list[dict[str, Any]]) -> dict[str, Any]:
        return subtasks_ops.bulk_create_subtasks(
            self._client, self._url, self._handle_response, task_id, subtasks
        )

    def update_subtask(self, task_id: str, subtask_id: str, passes: bool) -> dict[str, Any]:
        return subtasks_ops.update_subtask(
            self._client, self._global_url, self._handle_response, task_id, subtask_id, passes
        )

    def delete_subtask(self, task_id: str, subtask_id: str) -> dict[str, Any]:
        return subtasks_ops.delete_subtask(
            self._client, self._url, self._handle_response, task_id, subtask_id
        )

    def log_citations(self, task_id: str, subtask_id: str, citations: list[str]) -> dict[str, Any]:
        return subtasks_ops.log_citations(
            self._client, self._global_url, self._handle_response, task_id, subtask_id, citations
        )

    def acknowledge_no_citations(self, task_id: str, subtask_id: str) -> dict[str, Any]:
        return subtasks_ops.acknowledge_no_citations(
            self._client, self._global_url, self._handle_response, task_id, subtask_id
        )


class StepOperationsMixin:
    """Mixin providing step operations."""

    _client: Any
    _url: Any
    _global_url: Any
    _handle_response: Any

    def get_steps(self, task_id: str, subtask_id: str) -> list[dict[str, Any]]:
        return steps_ops.get_steps(
            self._client, self._url, self._handle_response, task_id, subtask_id
        )

    def bulk_create_steps(
        self, task_id: str, subtask_id: str, descriptions: list[str]
    ) -> dict[str, Any]:
        return steps_ops.bulk_create_steps(
            self._client, self._url, self._handle_response, task_id, subtask_id, descriptions
        )

    def append_steps(
        self, task_id: str, subtask_id: str, descriptions: list[str]
    ) -> dict[str, Any]:
        return steps_ops.append_steps(
            self._client, self._url, self._handle_response, task_id, subtask_id, descriptions
        )

    def update_step(
        self, task_id: str, subtask_id: str, step_number: int, passes: bool,
        already_verified: bool = False,
    ) -> dict[str, Any]:
        return steps_ops.update_step(
            self._client,
            self._global_url,
            self._handle_response,
            task_id,
            subtask_id,
            step_number,
            passes,
            already_verified=already_verified,
        )

    def delete_step(
        self, task_id: str, subtask_id: str, step_number: int, force: bool = False
    ) -> dict[str, Any]:
        return steps_ops.delete_step(
            self._client,
            self._url,
            self._handle_response,
            task_id,
            subtask_id,
            step_number,
            force=force,
        )

    def insert_step(
        self, task_id: str, subtask_id: str, position: int, description: str
    ) -> dict[str, Any]:
        return steps_ops.insert_step(
            self._client,
            self._url,
            self._handle_response,
            task_id,
            subtask_id,
            position,
            description,
        )

    def create_step_with_verification(
        self,
        task_id: str,
        subtask_id: str,
        description: str,
        verify_command: str,
        expected_output: str,
    ) -> dict[str, Any]:
        return steps_ops.create_step_with_verification(
            self._client,
            self._url,
            self._handle_response,
            task_id,
            subtask_id,
            description,
            verify_command,
            expected_output,
        )

    def update_step_fields(
        self, task_id: str, subtask_id: str, step_number: int, description: str | None = None
    ) -> dict[str, Any]:
        return steps_ops.update_step_fields(
            self._client,
            self._url,
            self._handle_response,
            task_id,
            subtask_id,
            step_number,
            description,
        )

    def update_step_status(
        self,
        task_id: str,
        subtask_id: str,
        step_number: int,
        status: str,
        fix_step_number: int | None = None,
    ) -> dict[str, Any]:
        return steps_ops.update_step_status(
            self._client,
            self._global_url,
            self._handle_response,
            task_id,
            subtask_id,
            step_number,
            status,
            fix_step_number,
        )


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

    def get_autonomous_status(self) -> dict[str, Any]:
        return exec_ops.get_autonomous_status(self._client, self._url, self._handle_response)

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
