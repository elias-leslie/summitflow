"""Unit tests for quality-gate escalation task creation."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from app.services.quality_gate.escalation import escalate_to_supervisor


def test_escalation_creates_autonomous_bug_task() -> None:
    """Escalated quality failures should re-enter the autonomous bug queue."""
    conn = MagicMock()
    check_result = {
        "project_id": "summitflow",
        "check_type": "ruff",
        "file_path": "backend/app/example.py",
        "line_number": 12,
        "error_message": "Unused import",
        "check_name": "F401",
        "escalation_task_id": None,
    }

    with (
        patch(
            "app.services.quality_gate.escalation.qcr_store.get_check_result",
            return_value=check_result,
        ),
        patch("app.services.quality_gate.escalation.qcr_store.mark_escalated") as mock_mark,
        patch(
            "app.services.quality_gate.escalation.create_task",
            return_value={"id": "task-quality"},
        ) as mock_create,
    ):
        result = escalate_to_supervisor(conn, 123)

    assert result == "task-quality"
    kwargs = mock_create.call_args.kwargs
    assert kwargs["task_type"] == "bug"
    assert kwargs["execution_mode"] == "autonomous"
    assert kwargs["autonomous"] is True
    mock_mark.assert_called_once_with(conn, 123, "task-quality")
    conn.commit.assert_called_once()
