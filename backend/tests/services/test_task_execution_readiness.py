"""Unit tests for task execution readiness helpers."""

from __future__ import annotations

from app.services.task_execution_readiness import assess_task_execution_readiness


class TestAssessTaskExecutionReadiness:
    """Execution-readiness classification."""

    def test_nontrivial_task_requires_full_agent_plan(self) -> None:
        readiness = assess_task_execution_readiness(
            {"task_type": "refactor", "complexity": "STANDARD", "description": "Refactor module"},
            {"objective": "Refactor foo.py", "done_when": ["Tests pass"]},
            [],
        )

        assert readiness.ready is False
        assert "spirit_anti" in readiness.missing_fields
        assert "subtasks" in readiness.missing_fields

    def test_nontrivial_task_with_subtasks_requires_steps(self) -> None:
        readiness = assess_task_execution_readiness(
            {"task_type": "feature", "complexity": "STANDARD", "description": "Add endpoint"},
            {
                "objective": "Add health endpoint",
                "done_when": ["Endpoint returns 200"],
                "spirit_anti": "Do not break existing routes",
            },
            [{"subtask_id": "1.1", "description": "Implement API", "steps_from_table": []}],
        )

        assert readiness.ready is False
        assert "steps" in readiness.missing_fields

    def test_ready_task_is_execution_ready(self) -> None:
        readiness = assess_task_execution_readiness(
            {"task_type": "feature", "complexity": "STANDARD", "description": "Add endpoint"},
            {
                "objective": "Add health endpoint",
                "done_when": ["Endpoint returns 200", "Tests pass"],
                "spirit_anti": "Do not break existing routes",
                "context": {"files_to_modify": ["backend/app/main.py"]},
            },
            [
                {
                    "subtask_id": "1.1",
                    "description": "Implement API",
                    "steps_from_table": [{"step_number": 1, "description": "Add route"}],
                }
            ],
        )

        assert readiness.ready is True
        assert readiness.plan_status == "approved"
        assert readiness.issues == []

    def test_complex_task_requires_completed_second_opinion(self) -> None:
        readiness = assess_task_execution_readiness(
            {
                "task_type": "feature",
                "complexity": "COMPLEX",
                "description": "Migrate critical auth flow",
                "priority": 1,
                "labels": ["auth", "backend"],
            },
            {
                "objective": "Ship auth migration safely",
                "done_when": ["Migration works", "Tests pass"],
                "spirit_anti": "Do not break login",
                "decisions": [{"id": "d1", "title": "Keep API stable", "outcome": "compat shim"}],
                "context": {"files_to_modify": ["backend/app/auth.py"]},
            },
            [
                {
                    "subtask_id": "1.1",
                    "description": "Implement migration",
                    "steps_from_table": [{"step_number": 1, "description": "Update flow"}],
                }
            ],
        )

        assert readiness.ready is False
        assert "second_opinion" in readiness.missing_fields
        assert any("second opinion" in issue.lower() for issue in readiness.issues)

    def test_completed_second_opinion_satisfies_complex_task_gate(self) -> None:
        readiness = assess_task_execution_readiness(
            {
                "task_type": "feature",
                "complexity": "COMPLEX",
                "description": "Migrate critical auth flow",
                "priority": 1,
                "labels": ["auth", "backend"],
            },
            {
                "objective": "Ship auth migration safely",
                "done_when": ["Migration works", "Tests pass"],
                "spirit_anti": "Do not break login",
                "decisions": [{"id": "d1", "title": "Keep API stable", "outcome": "compat shim"}],
                "context": {
                    "files_to_modify": ["backend/app/auth.py"],
                    "second_opinion": {
                        "required": True,
                        "stage": "task_shape",
                        "status": "completed",
                        "summary": "Plan covers migration and rollback risks.",
                    },
                },
            },
            [
                {
                    "subtask_id": "1.1",
                    "description": "Implement migration",
                    "steps_from_table": [{"step_number": 1, "description": "Update flow"}],
                }
            ],
        )

        assert readiness.ready is True
