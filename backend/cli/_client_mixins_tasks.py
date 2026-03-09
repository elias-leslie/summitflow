"""Task and dependency operation mixins for STClient."""

from __future__ import annotations

from typing import Any

from . import _client_dependencies as deps_ops
from . import _client_tasks as tasks_ops


class TaskOperationsMixin:
    """Mixin providing task-related operations."""

    _client: Any
    _url: Any
    _global_url: Any
    _handle_response: Any

    def create_task(self, data: dict[str, Any]) -> dict[str, Any]:
        return tasks_ops.create_task(self._client, self._url, self._handle_response, data)

    def batch_create_tasks(self, items: list[dict[str, Any]]) -> dict[str, Any]:
        return tasks_ops.batch_create_tasks(
            self._client,
            self._url,
            self._handle_response,
            items,
        )

    def get_task(self, task_id: str) -> dict[str, Any]:
        return tasks_ops.get_task(self._client, self._global_url, self._handle_response, task_id)

    def get_task_completion_readiness(self, task_id: str) -> dict[str, Any]:
        return tasks_ops.get_task_completion_readiness(
            self._client,
            self._global_url,
            self._handle_response,
            task_id,
        )

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
            self._client,
            self._url,
            self._handle_response,
            task_id,
            **updates,
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

    def close_task(
        self,
        task_id: str,
        reason: str | None = None,
        skip_gates: bool = False,
    ) -> dict[str, Any]:
        return self.update_status(task_id, "completed", reason=reason, skip_gates=skip_gates)

    def cancel_task(self, task_id: str) -> dict[str, Any]:
        return self.update_status(task_id, "cancelled")

    def delete_task(self, task_id: str) -> dict[str, Any]:
        return tasks_ops.delete_task(self._client, self._url, self._handle_response, task_id)

    def claim_task(
        self, task_id: str, lock_minutes: int = 30, worker_id: str | None = None
    ) -> dict[str, Any]:
        return tasks_ops.claim_task(
            self._client,
            self._url,
            self._handle_response,
            task_id,
            lock_minutes,
            worker_id,
        )

    def release_task(self, task_id: str) -> dict[str, Any]:
        return tasks_ops.release_task(self._client, self._url, self._handle_response, task_id)

    def append_log(self, task_id: str, entry: str) -> dict[str, Any]:
        return tasks_ops.append_log(
            self._client,
            self._global_url,
            self._handle_response,
            task_id,
            entry,
        )

    def validate_ready(self, task_id: str) -> dict[str, Any]:
        return tasks_ops.validate_ready(
            self._client,
            self._url,
            self._handle_response,
            task_id,
        )

    def finalize_task_merge(self, task_id: str) -> dict[str, Any]:
        return tasks_ops.finalize_task_merge(
            self._client,
            self._global_url,
            self._handle_response,
            task_id,
        )

    def resolve_task_conflict(self, task_id: str) -> dict[str, Any]:
        return tasks_ops.resolve_task_conflict(
            self._client,
            self._global_url,
            self._handle_response,
            task_id,
        )

    def smart_sync_project(self, project_id: str) -> dict[str, Any]:
        return tasks_ops.smart_sync_project(
            self._client,
            self._global_url,
            self._handle_response,
            project_id,
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
            self._client,
            self._url,
            self._handle_response,
            task_id,
            depends_on,
            dep_type,
        )

    def list_dependencies(self, task_id: str) -> list[dict[str, Any]]:
        return deps_ops.list_dependencies(
            self._client,
            self._global_url,
            self._handle_response,
            task_id,
        )

    def remove_dependency(
        self, task_id: str, depends_on: str, dep_type: str | None = None
    ) -> dict[str, Any]:
        return deps_ops.remove_dependency(
            self._client,
            self._url,
            self._handle_response,
            task_id,
            depends_on,
            dep_type,
        )
