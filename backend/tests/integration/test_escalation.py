"""Integration test for 3-2-1 escalation flow.

Tests the escalation pattern: worker fails 3x -> supervisor guidance -> human escalation.
"""

from __future__ import annotations

from app.tasks.autonomous.escalation import (
    SUPERVISOR_MAX_ATTEMPTS,
    WORKER_MAX_FAILURES,
    check_escalation_needed,
    supervisor_guidance,
)


class TestEscalationConstants:
    """Test escalation threshold constants."""

    def test_worker_max_failures_is_3(self) -> None:
        """Worker should escalate after 3 failures (3-2-1 pattern)."""
        assert WORKER_MAX_FAILURES == 3

    def test_supervisor_max_attempts_is_2(self) -> None:
        """Supervisor should escalate after 2 attempts (3-2-1 pattern)."""
        assert SUPERVISOR_MAX_ATTEMPTS == 2


class TestEscalationDetection:
    """Test escalation condition detection."""

    def test_escalation_check_function_exists(self) -> None:
        """Escalation check function should exist."""
        assert callable(check_escalation_needed)

    def test_no_escalation_below_threshold(self) -> None:
        """First failures should not trigger escalation."""
        result = check_escalation_needed(failure_count=1, supervisor_attempts=0)
        assert result["escalate_to_supervisor"] is False
        assert result["escalate_to_human"] is False

    def test_escalate_to_supervisor_at_threshold(self) -> None:
        """3 worker failures should trigger supervisor escalation."""
        result = check_escalation_needed(failure_count=3, supervisor_attempts=0)
        assert result["escalate_to_supervisor"] is True
        assert result["escalate_to_human"] is False

    def test_escalate_to_human_at_threshold(self) -> None:
        """2 supervisor attempts should trigger human escalation."""
        result = check_escalation_needed(failure_count=3, supervisor_attempts=2)
        assert result["escalate_to_human"] is True


class TestSupervisorGuidance:
    """Test supervisor guidance task."""

    def test_supervisor_guidance_function_exists(self) -> None:
        """Supervisor guidance function should exist."""
        assert callable(supervisor_guidance)
        assert supervisor_guidance.__name__ == "supervisor_guidance"
