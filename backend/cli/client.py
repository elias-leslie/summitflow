"""API client for SummitFlow Tasks."""

from __future__ import annotations

import socket
from typing import Any

import httpx

from .config import get_config


class APIError(Exception):
    """API request error with status code and detail."""

    def __init__(self, status_code: int, detail: str) -> None:
        self.status_code = status_code
        self.detail = detail
        super().__init__(f"[{status_code}] {detail}")


class STClient:
    """HTTP client for SummitFlow Tasks API."""

    def __init__(
        self,
        base_url: str | None = None,
        project_id: str | None = None,
        timeout: float = 30.0,
    ) -> None:
        """Initialize the client.

        Args:
            base_url: API base URL (default from ST_API_BASE)
            project_id: Project ID (default from ST_PROJECT_ID)
            timeout: Request timeout in seconds
        """
        config = get_config()
        self.base_url = base_url or config.api_base
        self.project_id = project_id or config.project_id
        self._client = httpx.Client(timeout=timeout)

    def _url(self, path: str) -> str:
        """Build project-scoped URL."""
        return f"{self.base_url}/projects/{self.project_id}{path}"

    def _handle_response(self, response: httpx.Response) -> dict[str, Any]:
        """Handle response and raise APIError on failure."""
        if response.status_code >= 400:
            try:
                data = response.json()
                detail = data.get("detail", response.text)
            except Exception:
                detail = response.text
            raise APIError(response.status_code, detail)
        return response.json()

    # Task CRUD operations

    def create_task(self, data: dict[str, Any]) -> dict[str, Any]:
        """Create a new task.

        Args:
            data: Task data (title, description, priority, labels, task_type, etc.)

        Returns:
            Created task dict.
        """
        response = self._client.post(self._url("/tasks"), json=data)
        return self._handle_response(response)

    def get_task(self, task_id: str) -> dict[str, Any]:
        """Get a task by ID.

        Args:
            task_id: Task ID

        Returns:
            Task dict.
        """
        response = self._client.get(self._url(f"/tasks/{task_id}"))
        return self._handle_response(response)

    def list_tasks(
        self,
        status: str | None = None,
        task_type: str | None = None,
        priority: int | None = None,
        labels: list[str] | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> dict[str, Any]:
        """List tasks with optional filters.

        Args:
            status: Filter by status
            task_type: Filter by type (feature, bug, task)
            priority: Filter by priority (0-4)
            labels: Filter by labels
            limit: Results per page
            offset: Results offset

        Returns:
            Dict with tasks list and total count.
        """
        params: dict[str, Any] = {"limit": limit, "offset": offset}
        if status:
            params["status"] = status
        if task_type:
            params["type"] = task_type
        if priority is not None:
            params["priority"] = priority
        if labels:
            params["labels"] = ",".join(labels)

        response = self._client.get(self._url("/tasks"), params=params)
        return self._handle_response(response)

    def list_ready(self, limit: int = 50) -> dict[str, Any]:
        """List tasks ready to work on (no blocking dependencies).

        Args:
            limit: Max results

        Returns:
            Dict with tasks list and total count.
        """
        response = self._client.get(self._url("/tasks/ready"), params={"limit": limit})
        return self._handle_response(response)

    def update_task(self, task_id: str, **updates: Any) -> dict[str, Any]:
        """Update a task.

        Args:
            task_id: Task ID
            **updates: Fields to update

        Returns:
            Updated task dict.
        """
        response = self._client.patch(self._url(f"/tasks/{task_id}"), json=updates)
        return self._handle_response(response)

    def update_status(
        self,
        task_id: str,
        status: str,
        error_message: str | None = None,
        force: bool = False,
    ) -> dict[str, Any]:
        """Update task status.

        Args:
            task_id: Task ID
            status: New status
            error_message: Optional error message
            force: Bypass validation

        Returns:
            Updated task dict.
        """
        data: dict[str, Any] = {"status": status, "force": force}
        if error_message:
            data["error_message"] = error_message

        response = self._client.patch(self._url(f"/tasks/{task_id}/status"), json=data)
        return self._handle_response(response)

    def close_task(
        self,
        task_id: str,
        reason: str | None = None,
        force: bool = False,
    ) -> dict[str, Any]:
        """Close a task (mark as completed).

        Args:
            task_id: Task ID
            reason: Completion reason (appended to description)
            force: Bypass validation

        Returns:
            Updated task dict.
        """
        return self.update_status(task_id, "completed", force=force)

    def delete_task(self, task_id: str) -> dict[str, Any]:
        """Delete a task.

        Args:
            task_id: Task ID

        Returns:
            Deletion confirmation dict.
        """
        response = self._client.delete(self._url(f"/tasks/{task_id}"))
        return self._handle_response(response)

    # Task claim/release

    def claim_task(
        self,
        task_id: str,
        lock_minutes: int = 30,
        worker_id: str | None = None,
    ) -> dict[str, Any]:
        """Claim a task for exclusive execution.

        Args:
            task_id: Task ID
            lock_minutes: How long to hold the lock
            worker_id: Worker identifier (defaults to hostname)

        Returns:
            Claimed task dict.
        """
        if worker_id is None:
            worker_id = socket.gethostname()

        data = {"worker_id": worker_id, "lock_minutes": lock_minutes}
        response = self._client.post(self._url(f"/tasks/{task_id}/claim"), json=data)
        return self._handle_response(response)

    def release_task(self, task_id: str) -> dict[str, Any]:
        """Release a claimed task.

        Args:
            task_id: Task ID

        Returns:
            Released task dict.
        """
        response = self._client.post(self._url(f"/tasks/{task_id}/release"))
        return self._handle_response(response)
