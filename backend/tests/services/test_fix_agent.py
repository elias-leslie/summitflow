"""Unit tests for fix_agent module.

Tests pattern injection into fix prompts and pattern storage on successful fixes.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.constants import CLAUDE_SONNET, GEMINI_FLASH, GEMINI_PRO
from app.services.model_registry import ModelFactory, ModelRegistry
from app.services.quality_gate.fix_agent import (
    MAX_FIX_ATTEMPTS,
    SUPERVISOR_ATTEMPTS,
    WORKER_ATTEMPTS,
    _build_fix_prompt,
    _format_attempt_history_for_prompt,
    _format_patterns_for_prompt,
    _get_similar_patterns,
    _store_successful_pattern,
    get_escalation_level,
    get_supervisor_model,
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


class TestDualModelSupervisor:
    """Tests for dual-model SUPERVISOR escalation (d13 decision)."""

    @pytest.fixture
    def factory(self) -> ModelFactory:
        """Create a fresh factory for each test."""
        return ModelFactory(registry=ModelRegistry())

    def test_supervisor_first_attempt_uses_sonnet(self, factory: ModelFactory) -> None:
        """First SUPERVISOR attempt (attempt 4) uses Claude Sonnet."""
        model, provider = get_supervisor_model(WORKER_ATTEMPTS, factory=factory)  # attempts=3
        assert model == CLAUDE_SONNET
        assert provider == "claude"

    def test_supervisor_second_attempt_uses_gemini_pro(self, factory: ModelFactory) -> None:
        """Second SUPERVISOR attempt (attempt 5) uses Gemini Pro."""
        model, provider = get_supervisor_model(WORKER_ATTEMPTS + 1, factory=factory)  # attempts=4
        assert model == GEMINI_PRO
        assert provider == "gemini"

    def test_supervisor_uses_gemini_pro_not_flash(self, factory: ModelFactory) -> None:
        """SUPERVISOR uses Pro (reasoning) not Flash."""
        model, _ = get_supervisor_model(WORKER_ATTEMPTS + 1, factory=factory)
        assert model == GEMINI_PRO
        assert model != GEMINI_FLASH

    def test_both_supervisor_attempts_complete_before_human(self, factory: ModelFactory) -> None:
        """Both SUPERVISOR models must be tried before HUMAN escalation."""
        # Attempt 3 (index 3) is first SUPERVISOR
        assert get_escalation_level(3) == "SUPERVISOR"
        model1, _provider1 = get_supervisor_model(3, factory=factory)
        assert model1 == CLAUDE_SONNET

        # Attempt 4 (index 4) is second SUPERVISOR
        assert get_escalation_level(4) == "SUPERVISOR"
        model2, _provider2 = get_supervisor_model(4, factory=factory)
        assert model2 == GEMINI_PRO

        # Attempt 5 (index 5) escalates to HUMAN
        assert get_escalation_level(5) == "HUMAN"

    def test_escalation_uses_model_factory(self, factory: ModelFactory) -> None:
        """Verify escalation properly uses ModelFactory for model selection."""
        # WORKER uses factory
        worker_selection = factory.get_model_for_escalation(level="WORKER", attempt=1)
        assert worker_selection.model_id == GEMINI_FLASH
        assert worker_selection.provider == "gemini"

        # SUPERVISOR attempt 1 uses factory
        sup1_selection = factory.get_model_for_escalation(level="SUPERVISOR", attempt=1)
        assert sup1_selection.model_id == CLAUDE_SONNET
        assert sup1_selection.provider == "claude"

        # SUPERVISOR attempt 2 uses factory
        sup2_selection = factory.get_model_for_escalation(level="SUPERVISOR", attempt=2)
        assert sup2_selection.model_id == GEMINI_PRO
        assert sup2_selection.provider == "gemini"


class TestAttemptHistoryFormatting:
    """Tests for attempt history formatting in SUPERVISOR prompts."""

    def test_empty_approaches(self) -> None:
        """Empty approach list returns empty string."""
        result = _format_attempt_history_for_prompt([])
        assert result == ""

    def test_single_approach(self) -> None:
        """Single approach is formatted correctly."""
        approaches = [
            {
                "attempt_number": 1,
                "approach_summary": "Removed unused import",
                "outcome": "failed",
                "model": "gemini-flash",
                "escalation_level": "WORKER",
            }
        ]

        result = _format_attempt_history_for_prompt(approaches)

        assert "## Previous Fix Attempts (ALL FAILED)" in result
        assert "### Attempt #1 (WORKER - gemini-flash)" in result
        assert "Removed unused import" in result
        assert "Do NOT repeat these approaches" in result

    def test_multiple_approaches(self) -> None:
        """Multiple approaches are all listed."""
        approaches = [
            {
                "attempt_number": 1,
                "approach_summary": "First approach",
                "outcome": "failed",
                "model": "gemini-flash",
                "escalation_level": "WORKER",
            },
            {
                "attempt_number": 2,
                "approach_summary": "Second approach",
                "outcome": "failed",
                "model": "gemini-flash",
                "escalation_level": "WORKER",
            },
            {
                "attempt_number": 3,
                "approach_summary": "Third approach",
                "outcome": "failed",
                "model": "gemini-flash",
                "escalation_level": "WORKER",
            },
        ]

        result = _format_attempt_history_for_prompt(approaches)

        assert "### Attempt #1" in result
        assert "### Attempt #2" in result
        assert "### Attempt #3" in result
        assert "First approach" in result
        assert "Second approach" in result
        assert "Third approach" in result

    def test_includes_try_different_instruction(self) -> None:
        """Output includes instruction to try different approach."""
        approaches = [
            {
                "attempt_number": 1,
                "approach_summary": "Test",
                "outcome": "failed",
            }
        ]

        result = _format_attempt_history_for_prompt(approaches)

        assert "Find a DIFFERENT approach" in result


class TestEscalateToHumanWorktree:
    """Tests for worktree preservation on HUMAN escalation."""

    @patch("app.services.quality_gate.fix_agent.qcr_store")
    @patch("app.services.quality_gate.fix_agent.create_task")
    def test_escalation_includes_worktree_path(
        self, mock_create_task: MagicMock, mock_qcr: MagicMock
    ) -> None:
        """Escalation task includes worktree path when provided."""
        from app.services.quality_gate.fix_agent import escalate_to_human

        mock_qcr.get_check_result.return_value = {
            "id": 1,
            "project_id": "test-project",
            "check_type": "ruff",
            "file_path": "test.py",
            "line_number": 10,
            "error_message": "Test error",
            "check_name": "F401",
        }
        mock_create_task.return_value = {"id": "task-123"}

        mock_conn = MagicMock()
        worktree_path = "/tmp/summitflow-worktrees/test-project/task-fix-123"

        escalate_to_human(mock_conn, result_id=1, worktree_path=worktree_path)

        # Verify description includes worktree info
        call_args = mock_create_task.call_args
        description = call_args.kwargs["description"]

        assert "## Worktree Preserved for Inspection" in description
        assert worktree_path in description
        assert "attempt_history.json" in description
        assert "git log" in description

    @patch("app.services.quality_gate.fix_agent.qcr_store")
    @patch("app.services.quality_gate.fix_agent.create_task")
    def test_escalation_without_worktree_path(
        self, mock_create_task: MagicMock, mock_qcr: MagicMock
    ) -> None:
        """Escalation works without worktree path."""
        from app.services.quality_gate.fix_agent import escalate_to_human

        mock_qcr.get_check_result.return_value = {
            "id": 1,
            "project_id": "test-project",
            "check_type": "ruff",
            "file_path": "test.py",
            "error_message": "Test error",
        }
        mock_create_task.return_value = {"id": "task-123"}

        mock_conn = MagicMock()

        # Call without worktree_path
        escalate_to_human(mock_conn, result_id=1)

        # Verify description does NOT include worktree info
        call_args = mock_create_task.call_args
        description = call_args.kwargs["description"]

        assert "## Worktree Preserved" not in description
