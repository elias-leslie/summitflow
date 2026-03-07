"""Tests for compact task context output."""

from __future__ import annotations

from cli._output_formatters import format_context_subtasks, format_context_task


class TestFormatContextTask:
    """Tests for compact task context formatting."""

    def test_includes_title_and_description_when_present(self) -> None:
        task = {
            "id": "task-123",
            "status": "running",
            "priority": 2,
            "task_type": "bug",
            "complexity": "SIMPLE",
            "title": "Repair ST workflow phase 2",
            "description": "Complete task closure flow follow-through.",
        }

        output = format_context_task(task)

        assert "TASK:task-123|running|P2|bug|SIMPLE" in output
        assert "TITLE:Repair ST workflow phase 2" in output
        assert "DESCRIPTION:Complete task closure flow follow-through." in output

    def test_omits_empty_workflow_markers(self) -> None:
        task = {
            "id": "task-456",
            "status": "pending",
            "priority": 3,
            "task_type": "task",
            "complexity": "SIMPLE",
            "title": "Validate context output",
            "description": "Keep only useful default fields.",
            "decisions": [],
        }

        output = format_context_task(task)

        assert "WORKFLOW:decisions:0" not in output

    def test_omits_empty_subtasks_marker(self) -> None:
        output = format_context_subtasks([])

        assert output == ""
