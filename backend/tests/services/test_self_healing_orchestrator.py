"""Tests for SelfHealingOrchestrator service."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from app.services.self_healing.orchestrator import (
    CHECK_TYPE_PRIORITY,
    MAX_ERRORS_PER_PROJECT,
    MAX_ERRORS_PER_RUN,
    SelfHealingOrchestrator,
    poll_and_fix_all,
)


@pytest.fixture
def mock_conn() -> MagicMock:
    """Create a mock database connection."""
    return MagicMock()


class TestSelfHealingOrchestrator:
    """Tests for SelfHealingOrchestrator."""

    def test_check_type_priority_order(self) -> None:
        """Verify priority order: lint before types before tests."""
        # Lint tools should come first
        assert CHECK_TYPE_PRIORITY.index("ruff") < CHECK_TYPE_PRIORITY.index("mypy")
        assert CHECK_TYPE_PRIORITY.index("biome") < CHECK_TYPE_PRIORITY.index("tsc")

        # Types before tests
        assert CHECK_TYPE_PRIORITY.index("mypy") < CHECK_TYPE_PRIORITY.index("pytest")
        assert CHECK_TYPE_PRIORITY.index("tsc") < CHECK_TYPE_PRIORITY.index("pytest")

    def test_init_default_limits(self, mock_conn: MagicMock) -> None:
        """Test default limits are set correctly."""
        orch = SelfHealingOrchestrator(mock_conn)
        assert orch.max_errors_per_run == MAX_ERRORS_PER_RUN
        assert orch.max_errors_per_project == MAX_ERRORS_PER_PROJECT
        assert orch.conn is mock_conn

    def test_init_custom_limits(self, mock_conn: MagicMock) -> None:
        """Test custom limits can be set."""
        orch = SelfHealingOrchestrator(
            mock_conn,
            max_errors_per_run=5,
            max_errors_per_project=2,
        )
        assert orch.max_errors_per_run == 5
        assert orch.max_errors_per_project == 2

    @patch("app.services.self_healing.orchestrator.list_projects")
    @patch("app.services.self_healing.orchestrator.qcr_store")
    def test_poll_and_fix_no_errors(
        self,
        mock_qcr: MagicMock,
        mock_list_projects: MagicMock,
        mock_conn: MagicMock,
    ) -> None:
        """Test poll_and_fix when no errors exist."""
        mock_list_projects.return_value = [{"id": "proj-1"}]
        mock_qcr.get_unfixed_count.return_value = 0

        orch = SelfHealingOrchestrator(mock_conn)
        result = orch.poll_and_fix()

        assert result["projects_processed"] == 0
        assert result["total_fixed"] == 0
        assert result["total_failed"] == 0
        assert result["total_escalated"] == 0

    @patch("app.services.quality_gate.fix_agent.fix_unfixed_errors")
    @patch("app.services.self_healing.orchestrator.list_projects")
    @patch("app.services.self_healing.orchestrator.qcr_store")
    def test_poll_and_fix_single_project(
        self,
        mock_qcr: MagicMock,
        mock_list_projects: MagicMock,
        mock_fix: MagicMock,
        mock_conn: MagicMock,
    ) -> None:
        """Test poll_and_fix with a single project."""
        mock_list_projects.return_value = [{"id": "proj-1"}]

        # Only ruff has unfixed errors
        def get_unfixed_count(conn: Any, project_id: str, check_type: str) -> int:
            if project_id == "proj-1" and check_type == "ruff":
                return 3
            return 0

        mock_qcr.get_unfixed_count.side_effect = get_unfixed_count
        mock_fix.return_value = {"fixed": 2, "failed": 1, "escalated": 0}

        orch = SelfHealingOrchestrator(mock_conn)
        result = orch.poll_and_fix()

        assert result["projects_processed"] == 1
        assert result["total_fixed"] == 2
        assert result["total_failed"] == 1
        assert result["total_escalated"] == 0
        assert "ruff" in result["by_check_type"]
        mock_fix.assert_called_once()

    @patch("app.services.quality_gate.fix_agent.fix_unfixed_errors")
    @patch("app.services.self_healing.orchestrator.list_projects")
    @patch("app.services.self_healing.orchestrator.qcr_store")
    def test_poll_and_fix_priority_order(
        self,
        mock_qcr: MagicMock,
        mock_list_projects: MagicMock,
        mock_fix: MagicMock,
        mock_conn: MagicMock,
    ) -> None:
        """Test that check types are processed in priority order."""
        mock_list_projects.return_value = [{"id": "proj-1"}]

        # Both ruff and mypy have errors
        def get_unfixed_count(conn: Any, project_id: str, check_type: str) -> int:
            if project_id == "proj-1":
                if check_type == "ruff":
                    return 2
                if check_type == "mypy":
                    return 3
            return 0

        mock_qcr.get_unfixed_count.side_effect = get_unfixed_count
        mock_fix.return_value = {"fixed": 1, "failed": 0, "escalated": 0}

        orch = SelfHealingOrchestrator(mock_conn, max_errors_per_project=10)
        orch.poll_and_fix()

        # Verify ruff was called first (appears first in call list)
        calls = mock_fix.call_args_list
        assert len(calls) == 2
        assert calls[0].kwargs["check_type"] == "ruff"
        assert calls[1].kwargs["check_type"] == "mypy"

    @patch("app.services.quality_gate.fix_agent.fix_unfixed_errors")
    @patch("app.services.self_healing.orchestrator.list_projects")
    @patch("app.services.self_healing.orchestrator.qcr_store")
    def test_poll_and_fix_respects_run_budget(
        self,
        mock_qcr: MagicMock,
        mock_list_projects: MagicMock,
        mock_fix: MagicMock,
        mock_conn: MagicMock,
    ) -> None:
        """Test that max_errors_per_run is respected via limit parameter."""
        mock_list_projects.return_value = [
            {"id": "proj-1"},
            {"id": "proj-2"},
        ]

        # Both projects have many errors
        mock_qcr.get_unfixed_count.return_value = 10

        # Mock fix to return count matching the limit it was called with
        def mock_fix_respecting_limit(**kwargs: Any) -> dict[str, int]:
            limit = kwargs.get("limit", 10)
            return {"fixed": min(limit, 5), "failed": 0, "escalated": 0}

        mock_fix.side_effect = mock_fix_respecting_limit

        orch = SelfHealingOrchestrator(
            mock_conn,
            max_errors_per_run=6,  # Only allow 6 total
            max_errors_per_project=10,
        )
        orch.poll_and_fix()

        # Verify the limit was passed correctly to fix_unfixed_errors
        # First call should have limit=6 (remaining budget)
        first_call = mock_fix.call_args_list[0]
        assert first_call.kwargs["limit"] == 6

        # After first call returns 5, remaining budget is 1
        # Second call should have limit=1
        if len(mock_fix.call_args_list) > 1:
            second_call = mock_fix.call_args_list[1]
            assert second_call.kwargs["limit"] <= 1

    @patch("app.services.quality_gate.fix_agent.fix_unfixed_errors")
    @patch("app.services.self_healing.orchestrator.list_projects")
    @patch("app.services.self_healing.orchestrator.qcr_store")
    def test_poll_and_fix_respects_project_budget(
        self,
        mock_qcr: MagicMock,
        mock_list_projects: MagicMock,
        mock_fix: MagicMock,
        mock_conn: MagicMock,
    ) -> None:
        """Test that max_errors_per_project limits per-project processing."""
        mock_list_projects.return_value = [{"id": "proj-1"}]

        # Project has many errors of multiple types
        def get_unfixed_count(conn: Any, project_id: str, check_type: str) -> int:
            return 10  # All check types have 10 errors

        mock_qcr.get_unfixed_count.side_effect = get_unfixed_count

        # Each fix processes 5 errors
        mock_fix.return_value = {"fixed": 5, "failed": 0, "escalated": 0}

        orch = SelfHealingOrchestrator(
            mock_conn,
            max_errors_per_run=100,
            max_errors_per_project=7,  # Only allow 7 per project
        )
        orch.poll_and_fix()

        # The limit should be passed to fix_unfixed_errors
        call_args = mock_fix.call_args_list[0]
        assert call_args.kwargs["limit"] <= 7

    @patch("app.services.self_healing.orchestrator.list_projects")
    @patch("app.services.self_healing.orchestrator.qcr_store")
    def test_get_health_summary_no_errors(
        self,
        mock_qcr: MagicMock,
        mock_list_projects: MagicMock,
        mock_conn: MagicMock,
    ) -> None:
        """Test health summary when no errors exist."""
        mock_list_projects.return_value = [{"id": "proj-1"}]
        mock_qcr.get_unfixed_count.return_value = 0

        orch = SelfHealingOrchestrator(mock_conn)
        summary = orch.get_health_summary()

        assert summary["should_run"] is False
        assert summary["total_unfixed"] == 0
        assert summary["projects_needing_fixes"] == 0

    @patch("app.services.self_healing.orchestrator.list_projects")
    @patch("app.services.self_healing.orchestrator.qcr_store")
    def test_get_health_summary_with_errors(
        self,
        mock_qcr: MagicMock,
        mock_list_projects: MagicMock,
        mock_conn: MagicMock,
    ) -> None:
        """Test health summary when errors exist."""
        mock_list_projects.return_value = [
            {"id": "proj-1"},
            {"id": "proj-2"},
        ]

        def get_unfixed_count(conn: Any, project_id: str, check_type: str) -> int:
            if project_id == "proj-1" and check_type == "ruff":
                return 5
            if project_id == "proj-2" and check_type == "mypy":
                return 3
            return 0

        mock_qcr.get_unfixed_count.side_effect = get_unfixed_count

        orch = SelfHealingOrchestrator(mock_conn)
        summary = orch.get_health_summary()

        assert summary["should_run"] is True
        assert summary["total_unfixed"] == 8
        assert summary["projects_needing_fixes"] == 2
        assert summary["by_project"]["proj-1"] == 5
        assert summary["by_project"]["proj-2"] == 3

    @patch("app.services.quality_gate.fix_agent.fix_unfixed_errors")
    @patch("app.services.self_healing.orchestrator.list_projects")
    @patch("app.services.self_healing.orchestrator.qcr_store")
    def test_poll_and_fix_handles_escalation(
        self,
        mock_qcr: MagicMock,
        mock_list_projects: MagicMock,
        mock_fix: MagicMock,
        mock_conn: MagicMock,
    ) -> None:
        """Test that escalation counts are tracked correctly."""
        mock_list_projects.return_value = [{"id": "proj-1"}]

        def get_unfixed_count(conn: Any, project_id: str, check_type: str) -> int:
            if check_type == "ruff":
                return 3
            return 0

        mock_qcr.get_unfixed_count.side_effect = get_unfixed_count
        mock_fix.return_value = {"fixed": 1, "failed": 1, "escalated": 1}

        orch = SelfHealingOrchestrator(mock_conn)
        result = orch.poll_and_fix()

        assert result["total_fixed"] == 1
        assert result["total_failed"] == 1
        assert result["total_escalated"] == 1


class TestPollAndFixAll:
    """Tests for the poll_and_fix_all convenience function."""

    @patch("app.services.self_healing.orchestrator.SelfHealingOrchestrator")
    def test_poll_and_fix_all_creates_orchestrator(
        self,
        mock_orch_class: MagicMock,
        mock_conn: MagicMock,
    ) -> None:
        """Test that poll_and_fix_all creates orchestrator correctly."""
        mock_instance = MagicMock()
        mock_instance.poll_and_fix.return_value = {"total_fixed": 5}
        mock_orch_class.return_value = mock_instance

        result = poll_and_fix_all(mock_conn, max_errors=10)

        mock_orch_class.assert_called_once_with(mock_conn, max_errors_per_run=10)
        mock_instance.poll_and_fix.assert_called_once()
        assert result == {"total_fixed": 5}
