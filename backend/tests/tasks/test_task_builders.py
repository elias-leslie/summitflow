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

    def test_size_issue_includes_line_target(self) -> None:
        obj = _build_issue_aware_objective("foo.py", 400, 200, ["large_file"])
        assert "400" in obj
        assert "200" in obj
        assert "aim" in obj.lower()

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

    def test_always_includes_quality_gates(self) -> None:
        criteria = _build_issue_aware_done_when(400, 200, ["large_file"], False)
        assert any("quality gates" in c.lower() for c in criteria)

    def test_always_includes_no_regressions(self) -> None:
        criteria = _build_issue_aware_done_when(400, 200, ["large_file"], False)
        assert any("regressions" in c.lower() for c in criteria)

    def test_size_issue_includes_line_count_criterion(self) -> None:
        criteria = _build_issue_aware_done_when(400, 200, ["large_file"], False)
        assert any("200" in c for c in criteria)
        assert any("only where it improves clarity" in c.lower() for c in criteria)

    def test_no_size_issue_omits_line_count_criterion(self) -> None:
        criteria = _build_issue_aware_done_when(200, 150, ["deep_nesting"], False)
        assert not any("reduced to" in c.lower() for c in criteria)

    def test_long_functions_criterion(self) -> None:
        criteria = _build_issue_aware_done_when(200, 150, ["has_long_functions"], False)
        assert any("largest functions" in c.lower() for c in criteria)

    def test_deep_nesting_criterion(self) -> None:
        criteria = _build_issue_aware_done_when(200, 150, ["deep_nesting"], False)
        assert any("deep nesting" in c.lower() for c in criteria)

    def test_too_many_functions_criterion(self) -> None:
        criteria = _build_issue_aware_done_when(200, 150, ["too_many_functions"], False)
        assert any("function count" in c.lower() for c in criteria)

    def test_too_many_classes_criterion(self) -> None:
        criteria = _build_issue_aware_done_when(200, 150, ["too_many_classes"], False)
        assert any("class count" in c.lower() for c in criteria)

    def test_large_classes_criterion(self) -> None:
        criteria = _build_issue_aware_done_when(200, 150, ["has_large_classes"], False)
        assert any("large classes" in c.lower() for c in criteria)

    def test_magic_strings_criterion(self) -> None:
        criteria = _build_issue_aware_done_when(200, 150, ["magic_strings"], False)
        assert any("magic strings" in c.lower() for c in criteria)

    def test_too_many_imports_criterion(self) -> None:
        criteria = _build_issue_aware_done_when(200, 150, ["too_many_imports"], False)
        assert any("imports" in c.lower() and "measured" in c.lower() for c in criteria)

    def test_frontend_includes_browser_check(self) -> None:
        criteria = _build_issue_aware_done_when(400, 200, ["large_file"], True)
        assert any("console errors" in c.lower() for c in criteria)

    def test_backend_omits_browser_check(self) -> None:
        criteria = _build_issue_aware_done_when(400, 200, ["large_file"], False)
        assert not any("console errors" in c.lower() for c in criteria)

    def test_multiple_issues_all_covered(self) -> None:
        """Multiple issues all generate their own criteria."""
        criteria = _build_issue_aware_done_when(
            400, 200,
            ["large_file", "has_long_functions", "deep_nesting", "too_many_functions"],
            False,
        )
        assert any("200" in c for c in criteria)  # line count
        assert any("largest functions" in c.lower() for c in criteria)
        assert any("deep nesting" in c.lower() for c in criteria)
        assert any("function count" in c.lower() for c in criteria)


class TestBuildRefactorDescription:
    """Tests for the human-facing refactor description."""

    def test_line_target_is_guidance_not_hard_requirement(self) -> None:
        description = build_refactor_description("backend/app/foo.py", 400, 200, 12.0, "medium")
        assert "Lines: 400" in description
        assert "guideline" in description.lower()
        assert "200" in description

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

    @patch("app.tasks.autonomous.task_builders.create_single_subtask_with_steps")
    @patch("app.tasks.autonomous.task_builders.link_task_to_issue")
    @patch("app.tasks.autonomous.task_builders.create_task_with_spirit")
    @patch("app.tasks.autonomous.task_builders.create_refactor_issue")
    def test_uses_full_relative_path_and_refactor_subtask_type(
        self,
        mock_issue: MagicMock,
        mock_create_task: MagicMock,
        mock_link: MagicMock,
        mock_create_subtask: MagicMock,
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
            "files_to_modify": ["backend/app/tasks/autonomous/task_generation.py"]
        }
        assert mock_create_subtask.call_args.kwargs["subtask_type"] == "refactor"
        assert "reduce size toward <200 lines only if it improves clarity" in mock_create_subtask.call_args.kwargs["description"]
        assert "preserving all existing behavior" in mock_create_task.call_args.kwargs["description"]
        mock_link.assert_called_once_with("task-123", 42)

    @patch("app.tasks.autonomous.task_builders.create_single_subtask_with_steps")
    @patch("app.tasks.autonomous.task_builders.link_task_to_issue")
    @patch("app.tasks.autonomous.task_builders.create_task_with_spirit")
    @patch("app.tasks.autonomous.task_builders.create_refactor_issue")
    def test_passes_generated_steps_to_subtask_creation(
        self,
        mock_issue: MagicMock,
        mock_create_task: MagicMock,
        _mock_link: MagicMock,
        mock_create_subtask: MagicMock,
    ) -> None:
        mock_issue.return_value = 42
        mock_create_task.return_value = "task-123"
        steps = [
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

        assert mock_create_subtask.call_args.kwargs["steps"] == steps


class TestCreateSingleSubtaskWithSteps:
    """Tests for subtask generation preserving plan-context steps."""

    @patch("app.tasks.autonomous._subtask_builder.bulk_create_subtasks")
    def test_preserves_steps_for_plan_context_sync(self, mock_bulk_create: MagicMock) -> None:
        steps = [
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
