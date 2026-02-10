"""Tests for planning verify_command validation warnings.

Covers:
- Small context window detection (-A1 through -A5)
- Chained rg pipe detection (rg ... | rg)
- head/tail usage detection in verify_commands
- Existing checks: absolute paths, grep→rg rewriting, generic expected_output
"""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

import pytest

from app.tasks.autonomous.planning import _validate_and_fix_plan


def _make_plan(verify_command: str, expected_output: str = "some output") -> dict[str, Any]:
    """Build a minimal plan dict with one subtask and one step."""
    return {
        "subtasks": [
            {
                "subtask_id": "1.1",
                "steps": [
                    {
                        "verify_command": verify_command,
                        "expected_output": expected_output,
                    }
                ],
            }
        ]
    }


class TestSmallContextWindowWarning:
    """Warn when verify_command uses -A1 through -A5 (too narrow)."""

    @pytest.mark.parametrize(
        "cmd",
        [
            "rg 'pattern' file -A1",
            "rg 'pattern' file -A2",
            "rg 'pattern' file -A3",
            "rg 'pattern' file -A4",
            "rg 'pattern' file -A5",
        ],
        ids=["A1", "A2", "A3", "A4", "A5"],
    )
    def test_small_context_window_logs_warning(self, cmd: str) -> None:
        plan = _make_plan(cmd)
        with patch("app.tasks.autonomous.planning.logger") as mock_logger:
            _validate_and_fix_plan(plan)
            mock_logger.warning.assert_any_call(
                "small_context_window",
                subtask="1.1",
                verify_command=cmd[:80],
            )

    def test_large_context_window_no_warning(self) -> None:
        plan = _make_plan("rg 'pattern' file -A20")
        with patch("app.tasks.autonomous.planning.logger") as mock_logger:
            _validate_and_fix_plan(plan)
            warning_events = [
                call.args[0] for call in mock_logger.warning.call_args_list
            ]
            assert "small_context_window" not in warning_events

    def test_small_context_window_does_not_nullify(self) -> None:
        """Warning only — verify_command should remain intact."""
        plan = _make_plan("rg 'pattern' file -A3")
        _validate_and_fix_plan(plan)
        assert plan["subtasks"][0]["steps"][0]["verify_command"] == "rg 'pattern' file -A3"


class TestChainedRgPipeWarning:
    """Warn when verify_command pipes rg output to another rg."""

    @pytest.mark.parametrize(
        "cmd",
        [
            "rg 'foo' file.py | rg 'bar'",
            "rg -A10 file.py | rg pattern",
            "rg something dir/ | rg 'filter'",
        ],
        ids=["basic_pipe", "with_flag", "with_dir"],
    )
    def test_chained_rg_pipe_logs_warning(self, cmd: str) -> None:
        plan = _make_plan(cmd)
        with patch("app.tasks.autonomous.planning.logger") as mock_logger:
            _validate_and_fix_plan(plan)
            mock_logger.warning.assert_any_call(
                "chained_rg_pipe",
                subtask="1.1",
                verify_command=cmd[:80],
            )

    def test_single_rg_no_warning(self) -> None:
        plan = _make_plan("rg 'pattern' file.py")
        with patch("app.tasks.autonomous.planning.logger") as mock_logger:
            _validate_and_fix_plan(plan)
            warning_events = [
                call.args[0] for call in mock_logger.warning.call_args_list
            ]
            assert "chained_rg_pipe" not in warning_events


class TestHeadTailWarning:
    """Warn when verify_command uses head or tail (brittle positional)."""

    @pytest.mark.parametrize(
        "cmd",
        [
            "head -5 file.py",
            "tail -n 10 file.py",
            "cat file.py | head",
            "rg 'pattern' file | tail -1",
        ],
        ids=["head_basic", "tail_basic", "pipe_head", "pipe_tail"],
    )
    def test_head_tail_logs_warning(self, cmd: str) -> None:
        plan = _make_plan(cmd)
        with patch("app.tasks.autonomous.planning.logger") as mock_logger:
            _validate_and_fix_plan(plan)
            mock_logger.warning.assert_any_call(
                "head_tail_usage",
                subtask="1.1",
                verify_command=cmd[:80],
            )

    def test_no_head_tail_no_warning(self) -> None:
        plan = _make_plan("rg 'pattern' file.py")
        with patch("app.tasks.autonomous.planning.logger") as mock_logger:
            _validate_and_fix_plan(plan)
            warning_events = [
                call.args[0] for call in mock_logger.warning.call_args_list
            ]
            assert "head_tail_usage" not in warning_events


class TestExistingValidation:
    """Ensure existing checks still work after adding new patterns."""

    def test_absolute_cd_path_nullifies_command(self) -> None:
        plan = _make_plan("cd /home/user/project && rg 'x' file")
        _validate_and_fix_plan(plan)
        assert plan["subtasks"][0]["steps"][0]["verify_command"] is None

    def test_grep_rewritten_to_rg(self) -> None:
        plan = _make_plan("grep 'pattern' file.py")
        _validate_and_fix_plan(plan)
        assert plan["subtasks"][0]["steps"][0]["verify_command"] == "rg 'pattern' file.py"

    def test_generic_expected_output_logs_warning(self) -> None:
        plan = _make_plan("rg 'x' file", expected_output="success")
        with patch("app.tasks.autonomous.planning.logger") as mock_logger:
            _validate_and_fix_plan(plan)
            mock_logger.warning.assert_any_call(
                "generic_expected_output",
                subtask="1.1",
                expected="success",
            )
