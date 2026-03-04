"""Subtask and step operation mixins for STClient."""

from __future__ import annotations

from typing import Any

from . import _client_steps as steps_ops
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
    ) -> dict[str, Any]:
        return steps_ops.create_step_with_verification(
            self._client,
            self._url,
            self._handle_response,
            task_id,
            subtask_id,
            description,
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
