"""Tests for completion gate verification against task done_when criteria."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from app.tasks.autonomous.exec_modules.intent_check import (
    IntentCheckResult,
    _parse_gate_response,
    check_intent,
)


class TestCheckIntent:
    """Test check_intent() main entry point."""

    @patch("app.tasks.autonomous.exec_modules.intent_check.get_task_spirit")
    def test_no_spirit_data_returns_pass(self, mock_spirit: MagicMock) -> None:
        mock_spirit.return_value = None
        result = check_intent("task-1", "/tmp/project", "summitflow")
        assert result.passed
        assert "No spirit data" in result.summary

    @patch("app.tasks.autonomous.exec_modules.intent_check.get_task_spirit")
    def test_no_done_when_returns_pass(self, mock_spirit: MagicMock) -> None:
        mock_spirit.return_value = {"done_when": []}
        result = check_intent("task-1", "/tmp/project", "summitflow")
        assert result.passed
        assert "No done_when" in result.summary

    @patch("app.tasks.autonomous.exec_modules.intent_check._evaluate_completion_gate")
    @patch("app.tasks.autonomous.exec_modules.intent_check._get_diff_summary")
    @patch("app.tasks.autonomous.exec_modules.intent_check._read_modified_files")
    @patch("app.tasks.autonomous.exec_modules.intent_check._get_modified_files")
    @patch("app.tasks.autonomous.exec_modules.intent_check.task_store.get_task")
    @patch("app.tasks.autonomous.exec_modules.intent_check.get_task_spirit")
    def test_with_done_when_calls_evaluate(
        self,
        mock_spirit: MagicMock,
        mock_get_task: MagicMock,
        mock_modified: MagicMock,
        mock_read: MagicMock,
        mock_diff: MagicMock,
        mock_eval: MagicMock,
    ) -> None:
        mock_spirit.return_value = {
            "done_when": ["API endpoint exists"],
        }
        mock_get_task.return_value = {"id": "task-1", "task_type": "task", "description": "Build X"}
        mock_modified.return_value = ["app/api.py"]
        mock_read.return_value = "contents"
        mock_diff.return_value = "some diff"
        mock_eval.return_value = IntentCheckResult(
            passed=True, objective_met=True, spirit_violated=False,
            confidence=95, summary="All pass",
        )
        result = check_intent("task-1", "/tmp/project", "summitflow")
        assert result.passed
        mock_eval.assert_called_once()

    @patch("app.storage.subtasks.get_subtasks_for_task")
    @patch("app.tasks.autonomous.exec_modules.intent_check.task_store.get_task")
    @patch("app.tasks.autonomous.exec_modules.intent_check.get_task_spirit")
    def test_refactor_with_passed_subtasks_skips_llm_review(
        self,
        mock_spirit: MagicMock,
        mock_get_task: MagicMock,
        mock_get_subtasks: MagicMock,
    ) -> None:
        mock_spirit.return_value = {
            "done_when": [
                "All configured quality gates pass",
                "No functions exceed 50 lines",
                "No regressions - all existing tests pass",
            ],
        }
        mock_get_task.return_value = {"id": "task-1", "task_type": "refactor"}
        mock_get_subtasks.return_value = [
            {
                "id": "task-1-1.1",
                "passes": True,
                "steps_from_table": [],
            }
        ]

        result = check_intent("task-1", "/tmp/project", "summitflow")

        assert result.passed
        assert result.summary == "Passed using refactor step verification evidence"

    @patch("app.tasks.autonomous.exec_modules.intent_check._evaluate_completion_gate")
    @patch("app.tasks.autonomous.exec_modules.intent_check._get_diff_summary")
    @patch("app.tasks.autonomous.exec_modules.intent_check._read_modified_files")
    @patch("app.tasks.autonomous.exec_modules.intent_check._get_modified_files")
    @patch("app.storage.subtasks.get_subtasks_for_task")
    @patch("app.tasks.autonomous.exec_modules.intent_check.task_store.get_task")
    @patch("app.tasks.autonomous.exec_modules.intent_check.get_task_spirit")
    def test_refactor_with_unpassed_subtask_falls_back_to_llm_review(
        self,
        mock_spirit: MagicMock,
        mock_get_task: MagicMock,
        mock_get_subtasks: MagicMock,
        mock_modified: MagicMock,
        mock_read: MagicMock,
        mock_diff: MagicMock,
        mock_eval: MagicMock,
    ) -> None:
        mock_spirit.return_value = {
            "done_when": [
                "All configured quality gates pass",
                "No functions exceed 50 lines",
                "No regressions - all existing tests pass",
            ],
        }
        mock_get_task.return_value = {"id": "task-1", "task_type": "refactor", "description": "Refactor panes.py"}
        mock_get_subtasks.return_value = [
            {
                "id": "task-1-1.1",
                "passes": False,
                "steps_from_table": [],
            }
        ]
        mock_modified.return_value = ["app/panes.py"]
        mock_read.return_value = "contents"
        mock_diff.return_value = "some diff"
        mock_eval.return_value = IntentCheckResult(
            passed=True,
            objective_met=True,
            spirit_violated=False,
            confidence=95,
            summary="LLM reviewed",
        )

        result = check_intent("task-1", "/tmp/project", "summitflow")

        assert result.passed
        assert result.summary == "LLM reviewed"
        mock_eval.assert_called_once()

    @patch("app.tasks.autonomous.exec_modules.intent_check._evaluate_completion_gate")
    @patch("app.tasks.autonomous.exec_modules.intent_check._get_diff_summary")
    @patch("app.tasks.autonomous.exec_modules.intent_check._read_modified_files")
    @patch("app.tasks.autonomous.exec_modules.intent_check._get_modified_files")
    @patch("app.storage.subtasks.get_subtasks_for_task")
    @patch("app.tasks.autonomous.exec_modules.intent_check.task_store.get_task")
    @patch("app.tasks.autonomous.exec_modules.intent_check.get_task_spirit")
    def test_refactor_pass_falls_through_when_target_file_untouched(
        self,
        mock_spirit: MagicMock,
        mock_get_task: MagicMock,
        mock_get_subtasks: MagicMock,
        mock_modified: MagicMock,
        mock_read: MagicMock,
        mock_diff: MagicMock,
        mock_eval: MagicMock,
    ) -> None:
        """Refactor task names files_to_modify but agent never touched any of them.

        Even with all subtasks/steps marked passes=True, the deterministic pass must
        decline and fall through to the LLM completion gate. Regression for the false
        positive observed on sf task-3708d248 where the agent ran 81 turns without
        editing the target file and the worker swept up unrelated dirty paths.
        """
        mock_spirit.return_value = {
            "done_when": [
                "All configured quality gates pass",
                "File structure is meaningfully simplified where size was the issue",
                "No regressions - all existing tests pass",
            ],
            "context": {"files_to_modify": ["backend/cli/commands/check.py"]},
        }
        mock_get_task.return_value = {
            "id": "task-1",
            "task_type": "refactor",
            "description": "Refactor check.py",
        }
        mock_get_subtasks.return_value = [
            {"id": "task-1-1.1", "passes": True, "steps_from_table": []},
        ]
        mock_modified.return_value = ["backend/tasks/somewhere/notes.md"]
        mock_read.return_value = "contents"
        mock_diff.return_value = "some diff"
        mock_eval.return_value = IntentCheckResult(
            passed=False, objective_met=False, spirit_violated=False,
            confidence=95, summary="Target file not modified",
        )

        result = check_intent("task-1", "/tmp/project", "summitflow")

        mock_eval.assert_called_once()
        assert result.summary == "Target file not modified"

    @patch("app.storage.subtasks.get_subtasks_for_task")
    @patch("app.tasks.autonomous.exec_modules.intent_check._get_modified_files")
    @patch("app.tasks.autonomous.exec_modules.intent_check.task_store.get_task")
    @patch("app.tasks.autonomous.exec_modules.intent_check.get_task_spirit")
    def test_refactor_pass_when_target_file_in_diff(
        self,
        mock_spirit: MagicMock,
        mock_get_task: MagicMock,
        mock_modified: MagicMock,
        mock_get_subtasks: MagicMock,
    ) -> None:
        """files_to_modify is satisfied by the diff — deterministic pass applies."""
        mock_spirit.return_value = {
            "done_when": [
                "All configured quality gates pass",
                "File structure is meaningfully simplified where size was the issue",
            ],
            "context": {"files_to_modify": ["backend/cli/commands/check.py"]},
        }
        mock_get_task.return_value = {"id": "task-1", "task_type": "refactor"}
        mock_modified.return_value = [
            "backend/cli/commands/check.py",
            "backend/tests/cli/test_check.py",
        ]
        mock_get_subtasks.return_value = [
            {"id": "task-1-1.1", "passes": True, "steps_from_table": []},
        ]

        result = check_intent("task-1", "/tmp/project", "summitflow")

        assert result.passed
        assert result.summary == "Passed using refactor step verification evidence"


class TestParseGateResponse:
    """Test completion gate response parsing logic."""

    def test_all_met(self) -> None:
        content = """CRITERION_1: MET - Endpoint created at app/api.py:15
CRITERION_2: MET - Tests added at tests/test_api.py:10
CONFIDENCE: 95
GAPS: NONE
ANTI_CHECK: CLEAR"""
        result = _parse_gate_response(
            content, ["API endpoint exists", "Tests cover endpoint"]
        )
        assert result.passed
        assert result.objective_met
        assert not result.spirit_violated
        assert result.confidence == 95
        assert len(result.done_when_results) == 2
        assert result.done_when_results[0].status == "MET"
        assert result.done_when_results[1].status == "MET"

    def test_one_not_met(self) -> None:
        content = """CRITERION_1: MET - Done
CRITERION_2: NOT_MET - Not implemented
CONFIDENCE: 40
GAPS: Feature B missing
ANTI_CHECK: CLEAR"""
        result = _parse_gate_response(
            content, ["Feature A", "Feature B"]
        )
        assert not result.passed
        assert result.done_when_results[1].status == "NOT_MET"

    def test_spirit_violated(self) -> None:
        content = """CRITERION_1: MET - Done
CONFIDENCE: 95
GAPS: NONE
ANTI_CHECK: VIOLATED - Broke existing tests"""
        result = _parse_gate_response(content, ["Build X"])
        assert not result.passed
        assert result.spirit_violated

    def test_partial_items_pass(self) -> None:
        content = """CRITERION_1: MET - Done
CRITERION_2: PARTIAL - Partially implemented
CONFIDENCE: 92
GAPS: NONE
ANTI_CHECK: CLEAR"""
        result = _parse_gate_response(
            content, ["Feature A", "Feature B"]
        )
        assert result.passed
        assert result.done_when_results[1].status == "PARTIAL"

    def test_low_confidence_blocks(self) -> None:
        content = """CRITERION_1: MET - Done
CONFIDENCE: 50
GAPS: Uncertain about coverage
ANTI_CHECK: CLEAR"""
        result = _parse_gate_response(content, ["Feature A"])
        assert not result.passed
        assert result.confidence == 50
