"""Subtask operation mixins for STClient."""

from __future__ import annotations

from typing import Any

from . import _client_subtasks as subtasks_ops


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
        subtask_type: str | None = None,
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
            subtask_type=subtask_type,
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
