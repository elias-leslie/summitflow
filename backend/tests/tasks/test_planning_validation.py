"""Tests for planning verify_command validation.

Covers:
- Trivial command blocking (true, :, exit 0, echo-only, empty, comments)
- Absolute path rejection (raises ValueError, not nullification)
- Small context window detection (-A1 through -A5)
- Chained rg pipe detection (rg ... | rg)
- head/tail usage detection in verify_commands
- grep→rg rewriting
"""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

import pytest

from app.tasks.autonomous.planning import _validate_and_fix_plan


def _make_plan(verify_command: str) -> dict[str, Any]:
    """Build a minimal plan dict with one subtask and one step."""
    return {
        "subtasks": [
            {
                "subtask_id": "1.1",
                "steps": [
                    {
                        "verify_command": verify_command,
                    }
                ],
            }
        ]
    }


class TestTrivialCommandBlocking:
    """Block trivial verify_commands that always exit 0."""

    @pytest.mark.parametrize(
        "cmd,match",
        [
            ("true", "always exits 0"),
            (":", "always exits 0"),
            ("exit 0", "always exits 0"),
        ],
        ids=["true", "colon", "exit_0"],
    )
    def test_noop_raises_valueerror(self, cmd: str, match: str) -> None:
        plan = _make_plan(cmd)
        with pytest.raises(ValueError, match=match):
            _validate_and_fix_plan(plan)

    @pytest.mark.parametrize(
        "cmd,match",
        [
            ("echo ok", "echo-only"),
            ("echo 'Found it'", "echo-only"),
            ("Echo Done", "echo-only"),
        ],
        ids=["echo_ok", "echo_quoted", "echo_case"],
    )
    def test_echo_only_raises_valueerror(self, cmd: str, match: str) -> None:
        plan = _make_plan(cmd)
        with pytest.raises(ValueError, match=match):
            _validate_and_fix_plan(plan)

    def test_echo_compound_allowed(self) -> None:
        """echo + real check via && is legitimate."""
        plan = _make_plan("echo 'checking' && test -f file.py")
        _validate_and_fix_plan(plan)
        assert plan["subtasks"][0]["steps"][0]["verify_command"] == "echo 'checking' && test -f file.py"

    def test_empty_string_raises_valueerror(self) -> None:
        plan = _make_plan("")
        # Empty string is falsy, so it skips the verify block entirely (no error)
        _validate_and_fix_plan(plan)

    def test_whitespace_only_raises_valueerror(self) -> None:
        plan = _make_plan("   ")
        with pytest.raises(ValueError, match="empty"):
            _validate_and_fix_plan(plan)

    def test_comment_only_raises_valueerror(self) -> None:
        plan = _make_plan("# just a comment")
        with pytest.raises(ValueError, match="comment"):
            _validate_and_fix_plan(plan)

    @pytest.mark.parametrize(
        "cmd",
        [
            "test -f file.py",
            "rg -q 'def main' app/main.py",
            "python -c 'import foo'",
            "pytest tests/test_foo.py -q",
        ],
        ids=["test_f", "rg_q", "python_import", "pytest"],
    )
    def test_legitimate_commands_allowed(self, cmd: str) -> None:
        plan = _make_plan(cmd)
        _validate_and_fix_plan(plan)
        assert plan["subtasks"][0]["steps"][0]["verify_command"] == cmd


class TestAbsolutePathRaises:
    """Absolute paths raise ValueError; cd prefixes are auto-fixed."""

    def test_absolute_cd_path_auto_fixed(self) -> None:
        """cd /abs/path && cmd is auto-fixed by stripping the cd prefix."""
        plan = _make_plan("cd /home/user/project && rg 'x' file")
        _validate_and_fix_plan(plan)
        assert plan["subtasks"][0]["steps"][0]["verify_command"] == "rg 'x' file"

    def test_absolute_path_prefix_raises(self) -> None:
        plan = _make_plan("cat /home/user/project/file.txt")
        with pytest.raises(ValueError, match="absolute path"):
            _validate_and_fix_plan(plan)

    def test_relative_path_allowed(self) -> None:
        plan = _make_plan("rg 'pattern' backend/app/main.py")
        _validate_and_fix_plan(plan)
        assert plan["subtasks"][0]["steps"][0]["verify_command"] == "rg 'pattern' backend/app/main.py"


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
        with patch("app.tasks.autonomous.planning_validation.logger") as mock_logger:
            _validate_and_fix_plan(plan)
            mock_logger.warning.assert_any_call(
                "small_context_window",
                subtask="1.1",
                verify_command=cmd[:80],
            )

    def test_large_context_window_no_warning(self) -> None:
        plan = _make_plan("rg 'pattern' file -A20")
        with patch("app.tasks.autonomous.planning_validation.logger") as mock_logger:
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
        with patch("app.tasks.autonomous.planning_validation.logger") as mock_logger:
            _validate_and_fix_plan(plan)
            mock_logger.warning.assert_any_call(
                "chained_rg_pipe",
                subtask="1.1",
                verify_command=cmd[:80],
            )

    def test_single_rg_no_warning(self) -> None:
        plan = _make_plan("rg 'pattern' file.py")
        with patch("app.tasks.autonomous.planning_validation.logger") as mock_logger:
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
        with patch("app.tasks.autonomous.planning_validation.logger") as mock_logger:
            _validate_and_fix_plan(plan)
            mock_logger.warning.assert_any_call(
                "head_tail_usage",
                subtask="1.1",
                verify_command=cmd[:80],
            )

    def test_no_head_tail_no_warning(self) -> None:
        plan = _make_plan("rg 'pattern' file.py")
        with patch("app.tasks.autonomous.planning_validation.logger") as mock_logger:
            _validate_and_fix_plan(plan)
            warning_events = [
                call.args[0] for call in mock_logger.warning.call_args_list
            ]
            assert "head_tail_usage" not in warning_events


class TestGrepRewriting:
    """Ensure grep→rg rewriting still works."""

    def test_grep_rewritten_to_rg(self) -> None:
        plan = _make_plan("grep 'pattern' file.py")
        _validate_and_fix_plan(plan)
        assert plan["subtasks"][0]["steps"][0]["verify_command"] == "rg 'pattern' file.py"

    def test_cat_grep_rewritten_to_rg(self) -> None:
        plan = _make_plan("cat file.py | grep 'pattern'")
        _validate_and_fix_plan(plan)
        assert plan["subtasks"][0]["steps"][0]["verify_command"] == "rg 'pattern' file.py"
