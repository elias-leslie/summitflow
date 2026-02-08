"""Tests for duplicate dispatch prevention in the autocode pipeline.

Covers:
- Status guard in dispatch_task_immediate (running/non-dispatchable tasks)
- Atomic claim via claim_task() prevents concurrent execution
- claim_task() accepts queue status for autonomous tasks
- start_execution() idempotency guard rejects duplicate workers
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from app.tasks.autonomous.pickup import dispatch_task_immediate


class TestDispatchStatusGuard:
    """Tests for task status checks before dispatch."""

    @patch("app.tasks.autonomous.pickup.task_store")
    def test_dispatch_skips_running_task(self, mock_store: MagicMock) -> None:
        """Already-running task is not re-dispatched."""
        mock_store.get_task.return_value = {
            "id": "task-123",
            "status": "running",
            "claimed_by": "worker-1",
        }

        result = dispatch_task_immediate("task-123", "test-project")

        assert result["status"] == "already_running"
        assert result["task_id"] == "task-123"

    @patch("app.tasks.autonomous.pickup.task_store")
    def test_dispatch_skips_completed_task(self, mock_store: MagicMock) -> None:
        """Completed task is not re-dispatched."""
        mock_store.get_task.return_value = {
            "id": "task-123",
            "status": "done",
        }

        result = dispatch_task_immediate("task-123", "test-project")

        assert result["status"] == "skipped"
        assert "done" in result["reason"]

    @patch("app.tasks.autonomous.pickup.task_store")
    def test_dispatch_returns_error_for_missing_task(self, mock_store: MagicMock) -> None:
        """Missing task returns error status."""
        mock_store.get_task.return_value = None

        result = dispatch_task_immediate("task-missing", "test-project")

        assert result["status"] == "error"
        assert result["reason"] == "task_not_found"

    @patch("app.tasks.autonomous.pickup.task_store")
    def test_dispatch_skips_abandoned_task(self, mock_store: MagicMock) -> None:
        """Abandoned task is not re-dispatched."""
        mock_store.get_task.return_value = {
            "id": "task-123",
            "status": "abandoned",
        }

        result = dispatch_task_immediate("task-123", "test-project")

        assert result["status"] == "skipped"
        assert "abandoned" in result["reason"]


class TestDispatchAtomicClaim:
    """Tests for atomic claim_task() in execution dispatch path."""

    @patch("app.tasks.autonomous.pickup.claim_task")
    @patch("app.tasks.autonomous.pickup.start_execution")
    @patch("app.tasks.autonomous.pickup._determine_next_stage")
    @patch("app.storage.agent_configs.is_autonomous_enabled")
    @patch("app.storage.agent_configs.is_within_autonomous_hours")
    @patch("app.storage.agent_configs.get_autonomous_schedule")
    @patch("app.tasks.autonomous.pickup.task_store")
    def test_dispatch_uses_claim_for_execution(
        self,
        mock_store: MagicMock,
        mock_schedule: MagicMock,
        mock_within_hours: MagicMock,
        mock_enabled: MagicMock,
        mock_stage: MagicMock,
        mock_exec: MagicMock,
        mock_claim: MagicMock,
    ) -> None:
        """Execution dispatch uses claim_task() for atomicity."""
        mock_store.get_task.return_value = {"id": "task-123", "status": "queue"}
        mock_enabled.return_value = True
        mock_within_hours.return_value = True
        mock_schedule.return_value = {"max_concurrent": 1}
        mock_store.count_running_tasks.return_value = 0
        mock_stage.return_value = "execution"
        mock_claim.return_value = {"id": "task-123", "status": "running", "claimed_by": "dispatch-test-project"}

        result = dispatch_task_immediate("task-123", "test-project")

        mock_claim.assert_called_once_with("task-123", "dispatch-test-project", lock_duration_minutes=60)
        mock_exec.delay.assert_called_once_with("task-123", "test-project")
        assert result["status"] == "dispatched"
        assert result["stage"] == "execution"

    @patch("app.tasks.autonomous.pickup.claim_task")
    @patch("app.tasks.autonomous.pickup.start_execution")
    @patch("app.tasks.autonomous.pickup._determine_next_stage")
    @patch("app.storage.agent_configs.is_autonomous_enabled")
    @patch("app.storage.agent_configs.is_within_autonomous_hours")
    @patch("app.storage.agent_configs.get_autonomous_schedule")
    @patch("app.tasks.autonomous.pickup.task_store")
    def test_dispatch_skips_when_claim_fails(
        self,
        mock_store: MagicMock,
        mock_schedule: MagicMock,
        mock_within_hours: MagicMock,
        mock_enabled: MagicMock,
        mock_stage: MagicMock,
        mock_exec: MagicMock,
        mock_claim: MagicMock,
    ) -> None:
        """Dispatch skips execution when claim_task() returns None (already claimed)."""
        mock_store.get_task.return_value = {"id": "task-123", "status": "queue"}
        mock_enabled.return_value = True
        mock_within_hours.return_value = True
        mock_schedule.return_value = {"max_concurrent": 1}
        mock_store.count_running_tasks.return_value = 0
        mock_stage.return_value = "execution"
        mock_claim.return_value = None

        result = dispatch_task_immediate("task-123", "test-project")

        mock_claim.assert_called_once()
        mock_exec.delay.assert_not_called()
        assert result["status"] == "already_claimed"


class TestClaimTaskQueueStatus:
    """Tests that claim_task accepts queue status for autonomous tasks."""

    @patch("app.storage.tasks.claims.get_connection")
    def test_queue_status_is_claimable(self, mock_conn: MagicMock) -> None:
        """queue status is included in claimable_statuses."""
        from app.storage.tasks.claims import claim_task

        mock_cursor = MagicMock()
        mock_conn.return_value.__enter__ = MagicMock(return_value=mock_conn.return_value)
        mock_conn.return_value.__exit__ = MagicMock(return_value=False)
        mock_conn.return_value.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_conn.return_value.cursor.return_value.__exit__ = MagicMock(return_value=False)

        task_row = [
            "task-123", "test-project", "Test", None, "queue", 2, "task",
            None, None, None, None, None, None, None, None, None, None,
            None, None, None, None, None, None, None, None,
        ]
        mock_cursor.fetchone.side_effect = [task_row, None]

        result = claim_task("task-123", "test-worker")

        assert result is None


class TestStartExecutionIdempotency:
    """Tests for start_execution() duplicate execution guard."""

    @patch("app.tasks.autonomous.execution.task_store")
    @patch("app.tasks.autonomous.execution._emit_log")
    @patch("app.tasks.autonomous.execution._emit_error")
    @patch("app.tasks.autonomous.execution.debug_section")
    def test_start_execution_rejects_duplicate_worker(
        self,
        mock_debug: MagicMock,
        mock_emit_error: MagicMock,
        mock_emit_log: MagicMock,
        mock_store: MagicMock,
    ) -> None:
        """start_execution skips if task already claimed by different worker."""
        from app.tasks.autonomous.execution import start_execution

        mock_store.get_task.return_value = {
            "id": "task-123",
            "status": "running",
            "claimed_by": "other-worker",
        }

        mock_self = MagicMock()
        mock_self.request.hostname = "this-worker"

        result = start_execution(mock_self, "task-123", "test-project")

        assert result["status"] == "skipped"
        assert result["reason"] == "duplicate_execution"
        assert result["claimed_by"] == "other-worker"
