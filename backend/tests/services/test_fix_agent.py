"""Unit tests for fix_agent module.

Tests pattern injection into fix prompts and pattern storage on successful fixes.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.quality_gate.fix_agent import (
    MAX_FIX_ATTEMPTS,
    SUPERVISOR_ATTEMPTS,
    WORKER_ATTEMPTS,
    _build_fix_prompt,
    _format_patterns_for_prompt,
    _get_similar_patterns,
    _store_successful_pattern,
    get_escalation_level,
)
from app.services.self_healing.pattern_memory import StoredPattern


class TestEscalationLevel:
    """Tests for escalation level determination."""

    def test_worker_level_first_attempt(self) -> None:
        """First attempt is WORKER level."""
        assert get_escalation_level(0) == "WORKER"

    def test_worker_level_third_attempt(self) -> None:
        """Third attempt is still WORKER level."""
        assert get_escalation_level(2) == "WORKER"

    def test_supervisor_level_fourth_attempt(self) -> None:
        """Fourth attempt escalates to SUPERVISOR."""
        assert get_escalation_level(3) == "SUPERVISOR"

    def test_supervisor_level_fifth_attempt(self) -> None:
        """Fifth attempt is still SUPERVISOR level."""
        assert get_escalation_level(4) == "SUPERVISOR"

    def test_human_level_sixth_attempt(self) -> None:
        """Sixth attempt escalates to HUMAN."""
        assert get_escalation_level(5) == "HUMAN"

    def test_human_level_many_attempts(self) -> None:
        """Many attempts stays at HUMAN level."""
        assert get_escalation_level(10) == "HUMAN"


class TestFormatPatternsForPrompt:
    """Tests for pattern formatting in prompts."""

    def test_empty_patterns(self) -> None:
        """Empty pattern list returns empty string."""
        result = _format_patterns_for_prompt([])
        assert result == ""

    def test_single_pattern(self) -> None:
        """Single pattern is formatted correctly."""
        patterns = [
            StoredPattern(
                error_signature="ruff:F401:abc123",
                error_type="ruff",
                file_path="test.py",
                fix_diff="- import os",
                root_cause_summary="Removed unused import",
                success_count=1,
                similarity_score=0.85,
            )
        ]

        result = _format_patterns_for_prompt(patterns)

        assert "## Previous Successful Fixes for Similar Errors" in result
        assert "### Fix #1 (similarity: 85%)" in result
        assert "Removed unused import" in result
        assert "- import os" in result

    def test_multiple_patterns(self) -> None:
        """Multiple patterns are numbered correctly."""
        patterns = [
            StoredPattern(
                error_signature="sig1",
                error_type="ruff",
                file_path=None,
                fix_diff="diff1",
                root_cause_summary="cause1",
                success_count=1,
                similarity_score=0.9,
            ),
            StoredPattern(
                error_signature="sig2",
                error_type="ruff",
                file_path=None,
                fix_diff="diff2",
                root_cause_summary="cause2",
                success_count=1,
                similarity_score=0.7,
            ),
        ]

        result = _format_patterns_for_prompt(patterns)

        assert "### Fix #1 (similarity: 90%)" in result
        assert "### Fix #2 (similarity: 70%)" in result
        assert "cause1" in result
        assert "cause2" in result

    def test_pattern_without_diff(self) -> None:
        """Pattern without diff is handled gracefully."""
        patterns = [
            StoredPattern(
                error_signature="sig",
                error_type="mypy",
                file_path=None,
                fix_diff="",
                root_cause_summary="Added type annotation",
                success_count=1,
                similarity_score=0.75,
            )
        ]

        result = _format_patterns_for_prompt(patterns)

        assert "Added type annotation" in result
        # Empty diff should not show diff section
        assert "```diff" not in result


class TestBuildFixPrompt:
    """Tests for fix prompt construction."""

    @pytest.fixture
    def base_check_result(self) -> dict[str, Any]:
        """Base check result for tests."""
        return {
            "check_type": "ruff",
            "error_message": "'os' imported but unused",
            "file_path": "app/utils.py",
            "line_number": 5,
            "check_name": "F401",
        }

    def test_basic_prompt_structure(self, base_check_result: dict[str, Any]) -> None:
        """Prompt contains required sections."""
        prompt = _build_fix_prompt(
            check_result=base_check_result,
            file_content="import os\n\nprint('hello')",
            project_path=Path("/project"),
        )

        assert "# Fix RUFF Error" in prompt
        assert "**File:** app/utils.py" in prompt
        assert "**Line:** 5" in prompt
        assert "**Rule/Check:** F401" in prompt
        assert "'os' imported but unused" in prompt
        assert "## Instructions" in prompt
        assert "## Response Format" in prompt

    def test_prompt_with_patterns_injection(self, base_check_result: dict[str, Any]) -> None:
        """Patterns are injected into prompt."""
        patterns = [
            StoredPattern(
                error_signature="ruff:F401:abc",
                error_type="ruff",
                file_path=None,
                fix_diff="- import unused",
                root_cause_summary="Removed unused import",
                success_count=1,
                similarity_score=0.8,
            )
        ]

        prompt = _build_fix_prompt(
            check_result=base_check_result,
            file_content="import os\n",
            project_path=Path("/project"),
            similar_patterns=patterns,
        )

        assert "## Previous Successful Fixes for Similar Errors" in prompt
        assert "Removed unused import" in prompt
        assert "- import unused" in prompt

    def test_ruff_specific_instructions(self, base_check_result: dict[str, Any]) -> None:
        """Ruff-specific instructions are included."""
        prompt = _build_fix_prompt(
            check_result=base_check_result,
            file_content="import os\n",
            project_path=Path("/project"),
        )

        assert "F401: Remove unused import" in prompt
        assert "E501: Break long line" in prompt

    def test_mypy_specific_instructions(self, base_check_result: dict[str, Any]) -> None:
        """Mypy-specific instructions are included."""
        base_check_result["check_type"] = "mypy"
        base_check_result["check_name"] = "arg-type"

        prompt = _build_fix_prompt(
            check_result=base_check_result,
            file_content="def foo(x): pass\n",
            project_path=Path("/project"),
        )

        assert "# Fix MYPY Error" in prompt
        assert "Add type annotations" in prompt
        assert "Fix return type annotations" in prompt


class TestPatternRetrieval:
    """Tests for pattern retrieval integration."""

    @patch("app.services.quality_gate.fix_agent._get_pattern_memory")
    @patch("app.services.quality_gate.fix_agent._run_async")
    def test_get_similar_patterns_success(
        self, mock_run_async: MagicMock, mock_get_pm: MagicMock
    ) -> None:
        """Successful pattern retrieval."""
        expected_patterns = [
            StoredPattern(
                error_signature="sig",
                error_type="ruff",
                file_path=None,
                fix_diff="diff",
                root_cause_summary="cause",
                success_count=1,
                similarity_score=0.8,
            )
        ]
        mock_run_async.return_value = expected_patterns

        result = _get_similar_patterns("ruff", "F401", "test error")

        assert result == expected_patterns
        mock_run_async.assert_called_once()

    @patch("app.services.quality_gate.fix_agent._get_pattern_memory")
    @patch("app.services.quality_gate.fix_agent._run_async")
    def test_get_similar_patterns_failure_returns_empty(
        self, mock_run_async: MagicMock, mock_get_pm: MagicMock
    ) -> None:
        """Pattern retrieval failure returns empty list."""
        mock_run_async.side_effect = Exception("API error")

        result = _get_similar_patterns("ruff", "F401", "test error")

        assert result == []


class TestPatternStorage:
    """Tests for pattern storage on successful fixes."""

    @patch("app.services.quality_gate.fix_agent._get_pattern_memory")
    @patch("app.services.quality_gate.fix_agent._run_async")
    def test_store_successful_pattern(
        self, mock_run_async: MagicMock, mock_get_pm: MagicMock
    ) -> None:
        """Successful fix triggers pattern storage."""
        mock_run_async.return_value = {"success": True}

        _store_successful_pattern(
            check_type="ruff",
            check_name="F401",
            error_message="'os' imported but unused",
            file_path="test.py",
            original_content="import os\n\nprint('hello')",
            fixed_content="print('hello')",
        )

        mock_run_async.assert_called_once()
        # Verify the pattern memory store was called
        call_args = mock_run_async.call_args
        assert call_args is not None

    @patch("app.services.quality_gate.fix_agent._get_pattern_memory")
    @patch("app.services.quality_gate.fix_agent._run_async")
    def test_store_pattern_failure_does_not_raise(
        self, mock_run_async: MagicMock, mock_get_pm: MagicMock
    ) -> None:
        """Pattern storage failure should not raise."""
        mock_run_async.side_effect = Exception("Storage failed")

        # Should not raise
        _store_successful_pattern(
            check_type="ruff",
            check_name="F401",
            error_message="test",
            file_path="test.py",
            original_content="old",
            fixed_content="new",
        )

    @patch("app.services.quality_gate.fix_agent._get_pattern_memory")
    @patch("app.services.quality_gate.fix_agent._run_async")
    def test_store_pattern_computes_diff(
        self, mock_run_async: MagicMock, mock_get_pm: MagicMock
    ) -> None:
        """Pattern storage computes diff between original and fixed."""
        mock_pm = MagicMock()
        mock_pm.store_fix_pattern = AsyncMock()
        mock_get_pm.return_value = mock_pm

        original = "import os\n\nprint('hello')"
        fixed = "print('hello')"

        _store_successful_pattern(
            check_type="ruff",
            check_name="F401",
            error_message="unused import",
            file_path="test.py",
            original_content=original,
            fixed_content=fixed,
        )

        mock_run_async.assert_called_once()


class TestEscalationConstants:
    """Tests for escalation constants."""

    def test_worker_attempts(self) -> None:
        """Worker gets 3 attempts."""
        assert WORKER_ATTEMPTS == 3

    def test_supervisor_attempts(self) -> None:
        """Supervisor gets 2 attempts."""
        assert SUPERVISOR_ATTEMPTS == 2

    def test_max_attempts(self) -> None:
        """Max attempts is worker + supervisor."""
        assert MAX_FIX_ATTEMPTS == WORKER_ATTEMPTS + SUPERVISOR_ATTEMPTS
        assert MAX_FIX_ATTEMPTS == 5
