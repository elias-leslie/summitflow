"""Single-subtask creation keeps rich step guidance."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from app.tasks.subtask_builder import create_single_subtask_with_steps


class TestCreateSingleSubtaskWithSteps:
    """Tests for subtask generation preserving plan-context steps."""

    @patch("app.tasks.subtask_builder.bulk_create_subtasks")
    def test_preserves_steps_for_plan_context_sync(self, mock_bulk_create: MagicMock) -> None:
        steps: list[dict[str, object]] = [
            {"description": "Keep behavior stable"},
            {
                "description": "Run checks",
                "spec": {"verify_commands": ["st check --quick --changed-only"]},
            },
        ]
        mock_bulk_create.return_value = [{"id": "task-123-1.1"}]

        result = create_single_subtask_with_steps(
            task_id="task-123",
            subtask_id="1.1",
            phase="backend",
            description="Refactor target file",
            steps=steps,
            subtask_type="refactor",
        )

        assert result == "task-123-1.1"
        assert mock_bulk_create.call_args.args[1][0]["steps"] == steps
