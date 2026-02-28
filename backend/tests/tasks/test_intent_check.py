"""Tests for intent verification against task spirit."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.tasks.autonomous.exec_modules.intent_check import (
    DoneWhenResult,
    IntentCheckResult,
    _parse_intent_response,
    check_intent,
)


class TestCheckIntent:
    """Test check_intent() main entry point."""

    @patch("app.tasks.autonomous.exec_modules.intent_check.get_task_spirit")
    def test_no_spirit_data_returns_pass(self, mock_spirit: MagicMock) -> None:
        mock_spirit.return_value = None
        result = check_intent("task-1", "/tmp/project", "summitflow")
        assert result.passed is True
        assert "No spirit data" in result.summary

    @patch("app.tasks.autonomous.exec_modules.intent_check.get_task_spirit")
    def test_no_done_when_returns_pass(self, mock_spirit: MagicMock) -> None:
        mock_spirit.return_value = {"objective": "Build X", "done_when": []}
        result = check_intent("task-1", "/tmp/project", "summitflow")
        assert result.passed is True
        assert "No done_when" in result.summary

    @patch("app.tasks.autonomous.exec_modules.intent_check._evaluate_intent")
    @patch("app.tasks.autonomous.exec_modules.intent_check._get_diff_summary")
    @patch("app.tasks.autonomous.exec_modules.intent_check.get_task_spirit")
    def test_with_done_when_calls_evaluate(
        self, mock_spirit: MagicMock, mock_diff: MagicMock, mock_eval: MagicMock
    ) -> None:
        mock_spirit.return_value = {
            "objective": "Build X",
            "spirit_anti": "",
            "done_when": ["API endpoint exists"],
        }
        mock_diff.return_value = "some diff"
        mock_eval.return_value = IntentCheckResult(
            passed=True, objective_met=True, spirit_violated=False,
            summary="All pass",
        )
        result = check_intent("task-1", "/tmp/project", "summitflow")
        assert result.passed is True
        mock_eval.assert_called_once()


class TestParseIntentResponse:
    """Test response parsing logic."""

    def test_all_pass(self) -> None:
        content = """DONE_WHEN_1: PASS - Endpoint created
DONE_WHEN_2: PASS - Tests added
OBJECTIVE_MET: YES
SPIRIT_VIOLATED: NO
SUMMARY: All criteria met"""
        result = _parse_intent_response(
            content, ["API endpoint exists", "Tests cover endpoint"], "Build API", ""
        )
        assert result.passed is True
        assert result.objective_met is True
        assert result.spirit_violated is False
        assert len(result.done_when_results) == 2
        assert result.done_when_results[0].status == "pass"
        assert result.done_when_results[1].status == "pass"

    def test_one_fail(self) -> None:
        content = """DONE_WHEN_1: PASS - Done
DONE_WHEN_2: FAIL - Not implemented
OBJECTIVE_MET: NO
SPIRIT_VIOLATED: NO
SUMMARY: Missing feature"""
        result = _parse_intent_response(
            content, ["Feature A", "Feature B"], "Build both", ""
        )
        assert result.passed is False
        assert result.done_when_results[1].status == "fail"

    def test_spirit_violated(self) -> None:
        content = """DONE_WHEN_1: PASS - Done
OBJECTIVE_MET: YES
SPIRIT_VIOLATED: YES
SUMMARY: Broke existing tests"""
        result = _parse_intent_response(content, ["Build X"], "Build X", "Don't break tests")
        assert result.passed is False
        assert result.spirit_violated is True

    def test_unclear_items_pass(self) -> None:
        content = """DONE_WHEN_1: PASS - Done
DONE_WHEN_2: UNCLEAR - Cannot determine from diff
OBJECTIVE_MET: YES
SPIRIT_VIOLATED: NO
SUMMARY: Mostly done"""
        result = _parse_intent_response(
            content, ["Feature A", "Feature B"], "Build both", ""
        )
        assert result.passed is True
        assert result.done_when_results[1].status == "unclear"
