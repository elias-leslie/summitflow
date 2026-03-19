"""Tests for autonomous planning storage persistence."""

from __future__ import annotations

from unittest.mock import MagicMock, patch


class TestSavePlanToDatabase:
    @patch("app.tasks.autonomous.planning_storage.sync_task_execution_readiness")
    @patch("app.tasks.autonomous.planning_storage.ensure_second_opinion_tracking")
    @patch("app.tasks.autonomous.planning_storage.task_store")
    @patch("app.tasks.autonomous.planning_storage.bulk_add_subtask_dependencies")
    @patch("app.tasks.autonomous.planning_storage.bulk_create_subtasks")
    @patch("app.tasks.autonomous.planning_storage.update_task_spirit")
    @patch("app.tasks.autonomous.planning_storage.get_task_spirit")
    @patch("app.tasks.autonomous.planning_storage.create_task_spirit")
    def test_save_plan_to_database_persists_full_spirit_and_step_specs(
        self,
        mock_create_spirit: MagicMock,
        mock_get_spirit: MagicMock,
        mock_update_spirit: MagicMock,
        mock_bulk_create: MagicMock,
        mock_bulk_add_deps: MagicMock,
        mock_task_store: MagicMock,
        mock_second_opinion: MagicMock,
        mock_sync_readiness: MagicMock,
    ) -> None:
        from app.tasks.autonomous.planning_storage import save_plan_to_database

        mock_get_spirit.return_value = {
            "done_when": ["Current API still works"],
            "context": {"files_to_modify": ["backend/app/existing.py"]},
        }
        mock_task_store.get_task.return_value = {"id": "task-1", "complexity": "STANDARD"}

        plan_data = {
            "objective": "Planner reworded objective",
            "spirit_anti": "Do not broaden the feature",
            "done_when": ["UI renders the new field"],
            "decisions": [{"id": "d1", "title": "Reuse service", "outcome": "reuse"}],
            "constraints": ["Avoid schema changes"],
            "context": {
                "files_to_modify": ["frontend/app/page.tsx"],
                "files_to_create": ["frontend/lib/stats.ts"],
            },
            "subtasks": [
                {
                    "subtask_id": "1.1",
                    "phase": "frontend",
                    "subtask_type": "frontend",
                    "description": "Implement the UI update",
                    "steps": [
                        {
                            "description": "Wire the component",
                            "spec": {"verify_commands": ["dt --quick"]},
                        }
                    ],
                }
            ],
        }

        save_plan_to_database("task-1", plan_data)

        mock_create_spirit.assert_not_called()
        mock_update_spirit.assert_called_once_with(
            "task-1",
            done_when=["Current API still works", "UI renders the new field"],
            context={
                "files_to_modify": ["backend/app/existing.py", "frontend/app/page.tsx"],
                "files_to_create": ["frontend/lib/stats.ts"],
            },
        )
        mock_bulk_create.assert_called_once_with(
            "task-1",
            [
                {
                    "subtask_id": "1.1",
                    "phase": "frontend",
                    "subtask_type": "frontend",
                    "description": "Implement the UI update",
                    "steps": [
                        {
                            "description": "Wire the component",
                            "spec": {"verify_commands": ["dt --quick"]},
                        }
                    ],
                }
            ],
        )
        mock_bulk_add_deps.assert_not_called()
        mock_second_opinion.assert_called_once()
        mock_sync_readiness.assert_called_once_with("task-1", "planning")
