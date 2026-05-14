"""Tests for issue-aware task builder functions.

Covers:
- _build_issue_aware_objective: objectives describe actual issues
- _build_issue_aware_done_when: criteria match detected issues
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from app.tasks.autonomous._subtask_builder import create_single_subtask_with_steps
from app.tasks.autonomous.task_builders import (
    _build_issue_aware_done_when,
    _build_issue_aware_objective,
    build_refactor_description,
    create_refactor_task,
)


class TestBuildIssueAwareObjective:
    """Tests for _build_issue_aware_objective."""

    def test_size_issue_omits_line_target(self) -> None:
        obj = _build_issue_aware_objective("foo.py", 400, 200, ["large_file"])
        assert "400" not in obj
        assert "200" not in obj
        assert "where that improves clarity" in obj.lower()

    def test_structural_issue_describes_problems(self) -> None:
        obj = _build_issue_aware_objective("foo.py", 200, 150, ["deep_nesting", "has_long_functions"])
        assert "nesting" in obj.lower()
        assert "function" in obj.lower()

    def test_no_size_issue_omits_line_target(self) -> None:
        obj = _build_issue_aware_objective("foo.py", 200, 150, ["deep_nesting"])
        assert "200 to" not in obj

    def test_preserves_behavior_mention(self) -> None:
        obj = _build_issue_aware_objective("foo.py", 200, 150, ["deep_nesting"])
        assert "preserving" in obj.lower()

    def test_limits_structural_labels_to_four(self) -> None:
        """Long issue lists are truncated to 4 labels."""
        issues = ["deep_nesting", "has_long_functions", "too_many_functions", "too_many_classes", "has_large_classes"]
        obj = _build_issue_aware_objective("foo.py", 200, 150, issues)
        # Should only mention first 4 structural issues (minus complexity/size)
        assert "resolving:" in obj


class TestBuildIssueAwareDoneWhen:
    """Tests for _build_issue_aware_done_when."""

    def test_always_includes_behavior_preservation(self) -> None:
        criteria = _build_issue_aware_done_when(400, 200, ["large_file"], False)
        assert any("behavior" in c.lower() and "preserved" in c.lower() for c in criteria)

    def test_uses_relevant_checks_without_line_targets(self) -> None:
        criteria = _build_issue_aware_done_when(400, 200, ["large_file"], False)
        assert not any("200" in c for c in criteria)
        assert any("relevant checks pass" in c.lower() for c in criteria)

    def test_keeps_criteria_lean_for_frontend_too(self) -> None:
        criteria = _build_issue_aware_done_when(400, 200, ["large_file"], True)
        assert criteria == [
            "Existing behavior is preserved.",
            "Relevant checks pass.",
            "The file is simpler where the change is worthwhile.",
        ]

    def test_multiple_issues_do_not_expand_into_measurement_theatre(self) -> None:
        criteria = _build_issue_aware_done_when(
            400, 200,
            ["large_file", "has_long_functions", "deep_nesting", "too_many_functions"],
            False,
        )
        assert len(criteria) == 3
        assert not any("measured" in c.lower() or "count" in c.lower() for c in criteria)


class TestBuildRefactorDescription:
    """Tests for the human-facing refactor description."""

    def test_line_target_is_guidance_not_hard_requirement(self) -> None:
        description = build_refactor_description("backend/app/foo.py", 400, 200, 12.0, "medium")
        assert "Lines: 400" in description
        assert "guideline" not in description.lower()
        assert "200" not in description

    def test_includes_promotion_evidence_when_provided(self) -> None:
        description = build_refactor_description(
            "backend/app/foo.py",
            400,
            200,
            12.0,
            "medium",
            promotion_reasons=["High hotspot score (160)", "Nearby test coverage is missing"],
            promotion_confidence="high",
        )
        assert "Promotion confidence: high" in description
        assert "Promotion evidence" in description
        assert "High hotspot score" in description


class TestCreateRefactorTask:
    """Tests for create_refactor_task wiring."""

    @patch("app.tasks.autonomous.task_builders.link_task_to_issue")
    @patch("app.tasks.autonomous.task_builders.create_task_with_spirit")
    @patch("app.tasks.autonomous.task_builders.create_refactor_issue")
    def test_uses_full_relative_path_and_no_generated_subtask(
        self,
        mock_issue: MagicMock,
        mock_create_task: MagicMock,
        mock_link: MagicMock,
    ) -> None:
        mock_issue.return_value = 42
        mock_create_task.return_value = "task-123"

        task_id, issue_id = create_refactor_task(
            project_id="summitflow",
            relative_path="backend/app/tasks/autonomous/task_generation.py",
            file_path="/home/testuser/summitflow/backend/app/tasks/autonomous/task_generation.py",
            reason="High complexity score",
            complexity=18.0,
            lines=420,
            target_lines=200,
            priority="high",
            tier=2,
            steps=[{"description": "step"}],
            refactor_issues=["large_file"],
            promotion_reasons=["High hotspot score (180)"],
            promotion_confidence="high",
        )

        assert task_id == "task-123"
        assert issue_id == 42
        assert "backend/app/tasks/autonomous/task_generation.py" in mock_create_task.call_args.kwargs["title"]
        assert mock_create_task.call_args.kwargs["context"] == {
            "files_to_modify": ["backend/app/tasks/autonomous/task_generation.py"],
            "upkeep": {
                "source_key": "upkeep:refactors:backend/app/tasks/autonomous/task_generation.py",
                "signal_type": "refactors",
            },
        }
        assert "preserving all existing behavior" in mock_create_task.call_args.kwargs["description"]
        mock_link.assert_called_once_with("task-123", 42)

    @patch("app.tasks.autonomous.task_builders.link_task_to_issue")
    @patch("app.tasks.autonomous.task_builders.create_task_with_spirit")
    @patch("app.tasks.autonomous.task_builders.create_refactor_issue")
    def test_ignores_generated_steps_for_refactor_tasks(
        self,
        mock_issue: MagicMock,
        mock_create_task: MagicMock,
        _mock_link: MagicMock,
    ) -> None:
        mock_issue.return_value = 42
        mock_create_task.return_value = "task-123"
        steps: list[dict[str, object]] = [
            {"description": "Refactor safely"},
            {
                "description": "Verify structure",
                "spec": {"verify_commands": ["st check --quick"]},
            },
        ]

        create_refactor_task(
            project_id="summitflow",
            relative_path="backend/app/tasks/autonomous/task_generation.py",
            file_path="/tmp/summitflow/backend/app/tasks/autonomous/task_generation.py",
            reason="High complexity score",
            complexity=18.0,
            lines=420,
            target_lines=200,
            priority="high",
            tier=2,
            steps=steps,
            refactor_issues=["large_file"],
        )

        assert mock_create_task.called


class TestCreateSingleSubtaskWithSteps:
    """Tests for subtask generation preserving plan-context steps."""

    @patch("app.tasks.autonomous._subtask_builder.bulk_create_subtasks")
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
