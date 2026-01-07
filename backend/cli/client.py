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

    def _global_url(self, path: str) -> str:
        """Build non-project-scoped URL for global operations."""
        return f"{self.base_url}{path}"

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

    def batch_create_tasks(self, items: list[dict[str, Any]]) -> dict[str, Any]:
        """Create multiple tasks in batch.

        Args:
            items: List of task dicts (title, description, priority, labels, task_type, etc.)

        Returns:
            Dict with 'created' list and 'errors' list.
        """
        response = self._client.post(self._url("/tasks/batch"), json={"items": items})
        return self._handle_response(response)

    def get_task(self, task_id: str) -> dict[str, Any]:
        """Get a task by ID (global lookup, no project context required).

        Task IDs are globally unique, so this uses the non-project-scoped
        endpoint for lookups that don't need project validation.

        Args:
            task_id: Task ID

        Returns:
            Task dict.
        """
        response = self._client.get(self._global_url(f"/tasks/{task_id}"))
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
        reason: str | None = None,
    ) -> dict[str, Any]:
        """Update task status.

        Args:
            task_id: Task ID
            status: New status
            error_message: Optional error message
            reason: Optional completion reason (stored in progress_log)

        Returns:
            Updated task dict.
        """
        data: dict[str, Any] = {"status": status}
        if error_message:
            data["error_message"] = error_message
        if reason:
            data["reason"] = reason

        response = self._client.patch(self._url(f"/tasks/{task_id}/status"), json=data)
        return self._handle_response(response)

    def close_task(
        self,
        task_id: str,
        reason: str | None = None,
    ) -> dict[str, Any]:
        """Close a task (mark as completed).

        All subtasks must be complete and acceptance criteria verified.
        There is no bypass - complete the work first.

        Args:
            task_id: Task ID
            reason: Completion reason (stored in progress_log)

        Returns:
            Updated task dict.
        """
        return self.update_status(task_id, "completed", reason=reason)

    def cancel_task(self, task_id: str) -> dict[str, Any]:
        """Cancel a task (mark as cancelled from any non-terminal state).

        Args:
            task_id: Task ID

        Returns:
            Updated task dict.
        """
        return self.update_status(task_id, "cancelled")

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

    # Dependencies

    def add_dependency(
        self,
        task_id: str,
        depends_on: str,
        dep_type: str = "blocks",
    ) -> dict[str, Any]:
        """Add a dependency to a task.

        Args:
            task_id: Task that depends on another
            depends_on: Task ID being depended on
            dep_type: Dependency type (blocks, discovered-from)

        Returns:
            Created dependency dict.
        """
        data = {"depends_on_task_id": depends_on, "dependency_type": dep_type}
        response = self._client.post(self._url(f"/tasks/{task_id}/dependencies"), json=data)
        return self._handle_response(response)

    def list_dependencies(self, task_id: str) -> list[dict[str, Any]]:
        """List dependencies for a task.

        Args:
            task_id: Task ID

        Returns:
            List of dependency dicts.
        """
        response = self._client.get(self._url(f"/tasks/{task_id}/dependencies"))
        return self._handle_response(response)

    def remove_dependency(
        self,
        task_id: str,
        depends_on: str,
        dep_type: str | None = None,
    ) -> dict[str, Any]:
        """Remove a dependency from a task.

        Args:
            task_id: Task ID
            depends_on: Task ID being depended on
            dep_type: Dependency type (optional, removes all if not specified)

        Returns:
            Status dict.
        """
        url = f"/tasks/{task_id}/dependencies/{depends_on}"
        params = {}
        if dep_type:
            params["dependency_type"] = dep_type
        response = self._client.delete(self._url(url), params=params)
        return self._handle_response(response)

    # Components

    def list_components(self) -> list[dict[str, Any]]:
        """List all components for the project.

        Returns:
            List of component dicts.
        """
        response = self._client.get(self._url("/components"))
        return self._handle_response(response)

    def get_component(self, component_id: str) -> dict[str, Any]:
        """Get a component by ID.

        Args:
            component_id: Component ID (slug or integer ID)

        Returns:
            Component dict.
        """
        response = self._client.get(self._url(f"/components/{component_id}"))
        return self._handle_response(response)

    def create_component(
        self,
        component_id: str,
        name: str,
        description: str | None = None,
    ) -> dict[str, Any]:
        """Create a new component.

        Args:
            component_id: Component ID slug (e.g., "cli-tools")
            name: Display name
            description: Optional description

        Returns:
            Created component dict.
        """
        data: dict[str, Any] = {"component_id": component_id, "name": name}
        if description:
            data["description"] = description
        response = self._client.post(self._url("/components"), json=data)
        return self._handle_response(response)

    # Capabilities

    def list_capabilities(self) -> list[dict[str, Any]]:
        """List all capabilities for the project.

        Returns:
            List of capability dicts.
        """
        response = self._client.get(self._url("/capabilities"))
        return self._handle_response(response)

    def get_capability(self, capability_id: str) -> dict[str, Any]:
        """Get a capability by ID.

        Args:
            capability_id: Capability ID (slug or integer ID)

        Returns:
            Capability dict.
        """
        response = self._client.get(self._url(f"/capabilities/{capability_id}"))
        return self._handle_response(response)

    def create_capability(
        self,
        component_id: int | str,
        capability_id: str,
        name: str,
        description: str | None = None,
        priority: int = 2,
    ) -> dict[str, Any]:
        """Create a new capability.

        Args:
            component_id: Parent component ID (integer)
            capability_id: Capability ID slug (e.g., "user-login")
            name: Display name
            description: Optional description
            priority: Priority level (0-4, default 2)

        Returns:
            Created capability dict.
        """
        data: dict[str, Any] = {
            "component_id": component_id,
            "capability_id": capability_id,
            "name": name,
            "priority": priority,
        }
        if description:
            data["description"] = description
        response = self._client.post(self._url("/capabilities"), json=data)
        return self._handle_response(response)

    def verify_capability(self, capability_id: str) -> dict[str, Any]:
        """Verify a capability's tests.

        Args:
            capability_id: Capability ID

        Returns:
            Verification result dict.
        """
        response = self._client.post(self._url(f"/capabilities/{capability_id}/verify"))
        return self._handle_response(response)

    def update_capability(
        self,
        capability_id: str,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Update a capability.

        Args:
            capability_id: Capability ID
            **kwargs: Fields to update (name, description, priority, status)

        Returns:
            Updated capability dict.
        """
        data = {k: v for k, v in kwargs.items() if v is not None}
        response = self._client.patch(self._url(f"/capabilities/{capability_id}"), json=data)
        return self._handle_response(response)

    # Criterion Linkage

    def link_test_to_criterion(
        self,
        capability_id: str,
        criterion_id: str,
        test_id: int,
        is_primary: bool = False,
    ) -> dict[str, Any]:
        """Link a test to a criterion.

        Args:
            capability_id: Capability ID (slug)
            criterion_id: Criterion ID (e.g., "ac-001")
            test_id: Test ID (integer)
            is_primary: Whether this is the primary test

        Returns:
            Status dict.
        """
        data = {"test_id": test_id, "is_primary": is_primary}
        response = self._client.post(
            self._url(f"/capabilities/{capability_id}/criteria/{criterion_id}/link-test"),
            json=data,
        )
        return self._handle_response(response)

    def verify_criterion(
        self,
        task_id: str,
        criterion_id: str,
        verified: bool = True,
        verified_by: str = "test",
    ) -> dict[str, Any]:
        """Verify a criterion for a task.

        Args:
            task_id: Task ID
            criterion_id: Criterion ID (e.g., "ac-001")
            verified: Whether criterion is verified
            verified_by: Who/what verified (e.g., "test", "manual")

        Returns:
            Status dict with verification info.
        """
        data = {"verified": verified, "verified_by": verified_by}
        response = self._client.patch(
            self._url(f"/tasks/{task_id}/criteria/{criterion_id}/verify"),
            json=data,
        )
        return self._handle_response(response)

    def list_criteria(self, capability_id: str) -> list[dict[str, Any]]:
        """List criteria for a capability.

        Args:
            capability_id: Capability ID (slug)

        Returns:
            List of criterion dicts.
        """
        # Get capability with criteria included
        cap = self.get_capability(capability_id)
        return cap.get("criteria", [])

    def create_criterion(
        self,
        capability_id: str,
        criterion: str,
        category: str = "correctness",
        measurement: str = "test",
        threshold: str | None = None,
    ) -> dict[str, Any]:
        """Create a criterion and link to a capability.

        Args:
            capability_id: Capability ID (slug)
            criterion: The criterion text (min 10 chars)
            category: correctness, performance, security, quality
            measurement: test, metric, tool, manual
            threshold: Optional threshold value

        Returns:
            Created criterion dict.
        """
        data: dict[str, Any] = {
            "criterion": criterion,
            "category": category,
            "measurement": measurement,
        }
        if threshold:
            data["threshold"] = threshold
        response = self._client.post(
            self._url(f"/capabilities/{capability_id}/criteria"),
            json=data,
        )
        return self._handle_response(response)

    def update_criterion(
        self,
        criterion_id: str,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Update a criterion.

        Args:
            criterion_id: Criterion ID (e.g., "ac-001")
            **kwargs: Fields to update (criterion, category, measurement, threshold)

        Returns:
            Updated criterion dict.
        """
        data = {k: v for k, v in kwargs.items() if v is not None}
        response = self._client.patch(
            self._url(f"/criteria/{criterion_id}"),
            json=data,
        )
        return self._handle_response(response)

    # Tests

    def list_tests(self, test_type: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
        """List tests for the project.

        Args:
            test_type: Filter by test type
            limit: Max results to return

        Returns:
            List of test dicts.
        """
        params: dict[str, Any] = {"limit": limit}
        if test_type:
            params["type"] = test_type
        response = self._client.get(self._url("/tests"), params=params)
        return self._handle_response(response)

    def import_tests(self, framework: str) -> dict[str, Any]:
        """Import tests from a framework.

        Args:
            framework: Framework to import from (pytest, mypy, ruff, etc.)

        Returns:
            Import result dict.
        """
        response = self._client.post(self._url("/tests/import"), json={"framework": framework})
        return self._handle_response(response)

    # Subtasks

    def get_subtasks(
        self,
        task_id: str,
        include_steps: bool = False,
    ) -> dict[str, Any]:
        """Get subtasks for a task.

        Args:
            task_id: Task ID
            include_steps: Include steps from table

        Returns:
            Dict with subtasks list and summary.
        """
        params = {"include_steps": str(include_steps).lower()}
        response = self._client.get(self._url(f"/tasks/{task_id}/subtasks"), params=params)
        return self._handle_response(response)

    def create_subtask(
        self,
        task_id: str,
        subtask_id: str,
        description: str,
        phase: str = "implementation",
        steps: list[str] | None = None,
    ) -> dict[str, Any]:
        """Create a subtask for a task.

        Args:
            task_id: Task ID
            subtask_id: Subtask ID (e.g., "1.1")
            description: Subtask description
            phase: Phase name (e.g., "backend", "frontend")
            steps: Optional list of step descriptions

        Returns:
            Created subtask dict.
        """
        data: dict[str, Any] = {
            "subtask_id": subtask_id,
            "description": description,
            "phase": phase,
        }
        if steps:
            data["steps"] = steps
        response = self._client.post(self._url(f"/tasks/{task_id}/subtasks"), json=data)
        return self._handle_response(response)

    def bulk_create_subtasks(
        self,
        task_id: str,
        subtasks: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Create multiple subtasks for a task in batch.

        Args:
            task_id: Task ID
            subtasks: List of subtask dicts with subtask_id, description, phase, steps

        Returns:
            Dict with created list and errors list.
        """
        response = self._client.post(
            self._url(f"/tasks/{task_id}/subtasks/batch"),
            json={"subtasks": subtasks},
        )
        return self._handle_response(response)

    def update_subtask(
        self,
        task_id: str,
        subtask_id: str,
        passes: bool,
    ) -> dict[str, Any]:
        """Update a subtask's passes status.

        Args:
            task_id: Task ID
            subtask_id: Subtask ID (e.g., "1.1")
            passes: Whether subtask passes

        Returns:
            Updated subtask dict.
        """
        data = {"passes": passes}
        response = self._client.patch(
            self._url(f"/tasks/{task_id}/subtasks/{subtask_id}"), json=data
        )
        return self._handle_response(response)

    def delete_subtask(self, task_id: str, subtask_id: str) -> dict[str, Any]:
        """Delete a subtask and all its steps.

        Args:
            task_id: Task ID
            subtask_id: Subtask ID (e.g., "99.1")

        Returns:
            Deletion confirmation dict.
        """
        response = self._client.delete(self._url(f"/tasks/{task_id}/subtasks/{subtask_id}"))
        return self._handle_response(response)

    # Steps

    def get_steps(self, task_id: str, subtask_id: str) -> list[dict[str, Any]]:
        """Get steps for a subtask.

        Args:
            task_id: Task ID
            subtask_id: Subtask ID (e.g., "1.1")

        Returns:
            List of step dicts.
        """
        response = self._client.get(self._url(f"/tasks/{task_id}/subtasks/{subtask_id}/steps"))
        return self._handle_response(response)

    def bulk_create_steps(
        self,
        task_id: str,
        subtask_id: str,
        descriptions: list[str],
    ) -> dict[str, Any]:
        """Create multiple steps for a subtask in batch.

        Args:
            task_id: Task ID
            subtask_id: Subtask ID (e.g., "1.1")
            descriptions: List of step descriptions

        Returns:
            Dict with created list.
        """
        response = self._client.post(
            self._url(f"/tasks/{task_id}/subtasks/{subtask_id}/steps/batch"),
            json={"descriptions": descriptions},
        )
        return self._handle_response(response)

    def append_steps(
        self,
        task_id: str,
        subtask_id: str,
        descriptions: list[str],
    ) -> dict[str, Any]:
        """Append steps to a subtask, continuing from highest existing step number.

        Unlike bulk_create_steps which starts at 1, this finds the max step_number
        and continues from there. Safe to call on subtasks with existing steps.

        Args:
            task_id: Task ID
            subtask_id: Subtask ID (e.g., "1.1")
            descriptions: List of step descriptions to append

        Returns:
            Dict with created list.
        """
        response = self._client.post(
            self._url(f"/tasks/{task_id}/subtasks/{subtask_id}/steps/append"),
            json={"descriptions": descriptions},
        )
        return self._handle_response(response)

    def update_step(
        self,
        task_id: str,
        subtask_id: str,
        step_number: int,
        passes: bool,
    ) -> dict[str, Any]:
        """Update a step's passes status.

        Args:
            task_id: Task ID
            subtask_id: Subtask ID (e.g., "1.1")
            step_number: Step number (1-indexed)
            passes: Whether step passes

        Returns:
            Updated step dict.
        """
        data = {"passes": passes}
        response = self._client.patch(
            self._url(f"/tasks/{task_id}/subtasks/{subtask_id}/steps/{step_number}"),
            json=data,
        )
        return self._handle_response(response)

    def delete_step(
        self,
        task_id: str,
        subtask_id: str,
        step_number: int,
    ) -> dict[str, Any]:
        """Delete a step from a subtask.

        Args:
            task_id: Task ID
            subtask_id: Subtask ID (e.g., "1.1")
            step_number: Step number to delete (1-indexed)

        Returns:
            Deletion confirmation dict.
        """
        response = self._client.delete(
            self._url(f"/tasks/{task_id}/subtasks/{subtask_id}/steps/{step_number}")
        )
        return self._handle_response(response)

    # Execution

    def start_execution(
        self,
        task_id: str,
        agent_type: str = "claude",
        use_worktree: bool = False,
    ) -> dict[str, Any]:
        """Start execution of a task.

        Args:
            task_id: Task ID
            agent_type: Agent to use (claude/gemini)
            use_worktree: Execute in isolated git worktree

        Returns:
            Session info with session_id, status, worktree_path.
        """
        data = {"agent_type": agent_type, "use_worktree": use_worktree}
        response = self._client.post(self._url(f"/tasks/{task_id}/execute/start"), json=data)
        return self._handle_response(response)

    # Autonomous

    def get_autonomous_settings(self) -> dict[str, Any]:
        """Get autonomous execution settings.

        Returns:
            Settings dict with enabled, frequency_minutes, etc.
        """
        response = self._client.get(self._url("/autonomous/settings"))
        return self._handle_response(response)

    def update_autonomous_settings(self, **updates: Any) -> dict[str, Any]:
        """Update autonomous execution settings.

        Args:
            **updates: Fields to update (enabled, frequency_minutes, etc.)

        Returns:
            Updated settings dict.
        """
        response = self._client.patch(self._url("/autonomous/settings"), json=updates)
        return self._handle_response(response)

    def get_autonomous_status(self) -> dict[str, Any]:
        """Get autonomous execution status and metrics.

        Returns:
            Status dict with execution counts, recent activity, etc.
        """
        response = self._client.get(self._url("/autonomous/status"))
        return self._handle_response(response)

    # Sessions

    def list_sessions(self) -> list[dict[str, Any]]:
        """List agent sessions for the project.

        Returns:
            List of session dicts.
        """
        response = self._client.get(self._url("/sessions"))
        return self._handle_response(response)

    def get_session(self, session_id: str) -> dict[str, Any]:
        """Get a specific session.

        Args:
            session_id: Session ID

        Returns:
            Session dict.
        """
        response = self._client.get(self._url(f"/sessions/{session_id}"))
        return self._handle_response(response)

    def append_log(self, task_id: str, entry: str) -> dict[str, Any]:
        """Append an entry to the task's progress log.

        Args:
            task_id: Task ID
            entry: Log entry text

        Returns:
            Status dict confirming append.
        """
        data = {"entry": entry}
        response = self._client.post(self._url(f"/tasks/{task_id}/log"), json=data)
        return self._handle_response(response)
