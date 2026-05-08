"""Tests for task dispatch service.

Covers:
- Stage determination and workflow triggering
- Claim-before-execution for API dispatch path
- Non-execution stages skip claiming
- Not-claimable tasks return early
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services import dispatch as dispatch_service
from app.services.dispatch import dispatch_task


@pytest.fixture(autouse=True)
def allow_autonomous_dispatch(monkeypatch: pytest.MonkeyPatch) -> None:
    """Dispatch unit tests focus on stage/claim behavior unless a guard is under test."""
    monkeypatch.setattr(
        "app.services.dispatch.validate_autonomous_dispatch",
        lambda _project_id, _task_type=None: None,
    )


class TestDispatchTaskClaiming:
    """Tests for claim_task integration in the API dispatch path."""

    @pytest.mark.asyncio
    @patch("app.services.dispatch._trigger_workflow", new_callable=AsyncMock)
    @patch("app.services.dispatch.claim_task")
    @patch("app.services.dispatch._determine_next_stage", return_value="execution")
    @patch("app.services.dispatch.task_store")
    async def test_execution_stage_claims_before_workflow(
        self,
        mock_task_store: MagicMock,
        mock_stage: MagicMock,
        mock_claim: MagicMock,
        mock_trigger: AsyncMock,
    ) -> None:
        """Execution stage claims the task before triggering Hatchet workflow."""
        mock_task_store.get_task.return_value = {"id": "task-1", "status": "pending"}
        mock_claim.return_value = {"id": "task-1", "status": "running", "claimed_by": "api-dispatch-monkey-fight"}

        result = await dispatch_task("task-1", "monkey-fight")

        mock_claim.assert_called_once_with("task-1", "api-dispatch-monkey-fight", lock_duration_minutes=60)
        mock_trigger.assert_called_once_with("execution", "task-1", "monkey-fight")
        assert result["status"] == "dispatched"
        assert result["stage"] == "execution"

    @pytest.mark.asyncio
    @patch("app.services.dispatch._trigger_workflow", new_callable=AsyncMock)
    @patch("app.services.dispatch.claim_task", return_value=None)
    @patch("app.services.dispatch._determine_next_stage", return_value="execution")
    @patch("app.services.dispatch.task_store")
    async def test_execution_stage_not_claimable_returns_early(
        self,
        mock_task_store: MagicMock,
        mock_stage: MagicMock,
        mock_claim: MagicMock,
        mock_trigger: AsyncMock,
    ) -> None:
        """When claim_task returns None, dispatch returns not_claimable and skips workflow."""
        mock_task_store.get_task.return_value = {"id": "task-1", "status": "running"}

        result = await dispatch_task("task-1", "monkey-fight")

        assert result["status"] == "not_claimable"
        assert result["stage"] == "execution"
        mock_trigger.assert_not_called()

    @pytest.mark.asyncio
    @patch("app.services.dispatch._trigger_workflow", new_callable=AsyncMock)
    @patch("app.services.dispatch.claim_task")
    @patch("app.services.dispatch._determine_next_stage", return_value="triage")
    @patch("app.services.dispatch.task_store")
    async def test_triage_stage_skips_claim(
        self,
        mock_task_store: MagicMock,
        mock_stage: MagicMock,
        mock_claim: MagicMock,
        mock_trigger: AsyncMock,
    ) -> None:
        """Triage stage does not attempt to claim the task."""
        mock_task_store.get_task.return_value = {"id": "task-1", "status": "pending"}

        result = await dispatch_task("task-1", "monkey-fight")

        mock_claim.assert_not_called()
        mock_trigger.assert_called_once_with("triage", "task-1", "monkey-fight")
        assert result["status"] == "dispatched"

    @pytest.mark.asyncio
    @patch("app.services.dispatch._trigger_workflow", new_callable=AsyncMock)
    @patch("app.services.dispatch.claim_task")
    @patch("app.services.dispatch._determine_next_stage", return_value="planning")
    @patch("app.services.dispatch.task_store")
    async def test_planning_stage_skips_claim(
        self,
        mock_task_store: MagicMock,
        mock_stage: MagicMock,
        mock_claim: MagicMock,
        mock_trigger: AsyncMock,
    ) -> None:
        """Planning stage does not attempt to claim the task."""
        mock_task_store.get_task.return_value = {"id": "task-1", "status": "pending"}

        result = await dispatch_task("task-1", "monkey-fight")

        mock_claim.assert_not_called()
        mock_trigger.assert_called_once_with("planning", "task-1", "monkey-fight")
        assert result["status"] == "dispatched"

    @pytest.mark.asyncio
    @patch("app.services.dispatch._trigger_workflow", new_callable=AsyncMock)
    @patch("app.services.dispatch.claim_task")
    @patch("app.services.dispatch._determine_next_stage", return_value="ideation")
    @patch("app.services.dispatch.task_store")
    async def test_ideation_stage_skips_claim(
        self,
        mock_task_store: MagicMock,
        mock_stage: MagicMock,
        mock_claim: MagicMock,
        mock_trigger: AsyncMock,
    ) -> None:
        """Ideation stage does not attempt to claim the task."""
        mock_task_store.get_task.return_value = {"id": "task-1", "status": "pending"}

        result = await dispatch_task("task-1", "monkey-fight")

        mock_claim.assert_not_called()
        mock_trigger.assert_called_once_with("ideation", "task-1", "monkey-fight")
        assert result["status"] == "dispatched"

    @pytest.mark.asyncio
    @patch("app.services.dispatch._trigger_workflow", new_callable=AsyncMock)
    @patch("app.services.dispatch.claim_task")
    @patch("app.services.dispatch._determine_next_stage", return_value="review")
    @patch("app.services.dispatch.task_store")
    async def test_review_stage_skips_claim(
        self,
        mock_task_store: MagicMock,
        mock_stage: MagicMock,
        mock_claim: MagicMock,
        mock_trigger: AsyncMock,
    ) -> None:
        """Review stage does not attempt to claim the task."""
        mock_task_store.get_task.return_value = {"id": "task-1", "status": "pending"}

        result = await dispatch_task("task-1", "monkey-fight")

        mock_claim.assert_not_called()
        mock_trigger.assert_called_once_with("review", "task-1", "monkey-fight")
        assert result["status"] == "dispatched"


class TestDispatchTaskBasics:
    """Tests for dispatch_task foundational behavior."""

    @pytest.mark.asyncio
    @patch("app.services.dispatch.task_store")
    async def test_missing_task_raises_value_error(
        self,
        mock_task_store: MagicMock,
    ) -> None:
        """Dispatching a non-existent task raises ValueError."""
        mock_task_store.get_task.return_value = None

        with pytest.raises(ValueError, match="not found"):
            await dispatch_task("task-nonexistent", "monkey-fight")

    @pytest.mark.asyncio
    async def test_guard_failure_skips_claim_and_workflow(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Autonomous guard failures return a clear blocked result before dispatch."""
        trigger = AsyncMock()
        claim = MagicMock()
        stage = MagicMock(return_value="execution")

        monkeypatch.setattr(
            dispatch_service.task_store,
            "get_task",
            lambda _task_id: {"id": "task-1", "status": "pending", "task_type": "bug"},
        )
        monkeypatch.setattr(dispatch_service, "_trigger_workflow", trigger)
        monkeypatch.setattr(dispatch_service, "claim_task", claim)
        monkeypatch.setattr(dispatch_service, "_determine_next_stage", stage)
        monkeypatch.setattr(
            dispatch_service,
            "validate_autonomous_dispatch",
            lambda _project_id, _task_type=None: {"status": "disabled", "reason": "not_allowed"},
        )

        result = await dispatch_task("task-1", "monkey-fight")

        assert result["status"] == "disabled"
        assert result["stage"] == "blocked"
        assert result["reason"] == "not_allowed"
        assert result["details"] == {"status": "disabled", "reason": "not_allowed"}
        stage.assert_not_called()
        claim.assert_not_called()
        trigger.assert_not_awaited()

    @pytest.mark.asyncio
    @patch("app.services.dispatch._trigger_workflow", new_callable=AsyncMock)
    @patch("app.services.dispatch.claim_task")
    @patch("app.services.dispatch._determine_next_stage", return_value="execution")
    @patch("app.services.dispatch.task_store")
    async def test_execution_claim_uses_project_id_in_worker_id(
        self,
        mock_task_store: MagicMock,
        mock_stage: MagicMock,
        mock_claim: MagicMock,
        mock_trigger: AsyncMock,
    ) -> None:
        """Worker ID for claim includes the project ID for traceability."""
        mock_task_store.get_task.return_value = {"id": "task-1", "status": "pending"}
        mock_claim.return_value = {"id": "task-1", "claimed_by": "api-dispatch-monkey-fight"}

        await dispatch_task("task-1", "monkey-fight")

        worker_id = mock_claim.call_args[0][1]
        assert worker_id == "api-dispatch-monkey-fight"

    @pytest.mark.asyncio
    @patch("app.services.dispatch._trigger_workflow", new_callable=AsyncMock)
    @patch("app.services.dispatch.claim_task")
    @patch("app.services.dispatch._determine_next_stage", return_value="execution")
    @patch("app.services.dispatch.task_store")
    async def test_execution_claim_lock_duration_is_60_minutes(
        self,
        mock_task_store: MagicMock,
        mock_stage: MagicMock,
        mock_claim: MagicMock,
        mock_trigger: AsyncMock,
    ) -> None:
        """Execution claims use 60-minute lock duration for long-running tasks."""
        mock_task_store.get_task.return_value = {"id": "task-1", "status": "pending"}
        mock_claim.return_value = {"id": "task-1", "claimed_by": "api-dispatch-monkey-fight"}

        await dispatch_task("task-1", "monkey-fight")

        assert mock_claim.call_args.kwargs["lock_duration_minutes"] == 60

    @pytest.mark.asyncio
    @patch("app.services.dispatch._trigger_workflow", new_callable=AsyncMock)
    @patch("app.services.dispatch.claim_task")
    @patch("app.services.dispatch._determine_next_stage", return_value="execution")
    @patch("app.services.dispatch.task_store")
    async def test_dispatch_result_contains_all_fields(
        self,
        mock_task_store: MagicMock,
        mock_stage: MagicMock,
        mock_claim: MagicMock,
        mock_trigger: AsyncMock,
    ) -> None:
        """DispatchResult has task_id, project_id, stage, and status."""
        mock_task_store.get_task.return_value = {"id": "task-1", "status": "pending"}
        mock_claim.return_value = {"id": "task-1", "claimed_by": "api-dispatch-monkey-fight"}

        result = await dispatch_task("task-1", "monkey-fight")

        assert result["task_id"] == "task-1"
        assert result["project_id"] == "monkey-fight"
        assert result["stage"] == "execution"
        assert result["status"] == "dispatched"
