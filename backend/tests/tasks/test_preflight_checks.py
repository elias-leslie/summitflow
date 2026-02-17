"""Tests for pre-flight verify_command red checks.

Covers check_verify_commands_red() which runs verify_commands before
implementation to detect tautological commands (warning-only, never blocking).
"""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

from app.tasks.autonomous.exec_modules.preflight import check_verify_commands_red


def _make_steps(*cmds: str | None) -> list[dict[str, Any]]:
    """Build step list from verify_commands."""
    return [
        {"step_number": i + 1, "verify_command": cmd}
        for i, cmd in enumerate(cmds)
    ]


class TestPreflightRedCheck:
    """Pre-flight: detect verify_commands that pass before implementation."""

    def test_command_exits_zero_produces_warning(self, tmp_path: Any) -> None:
        """A command that succeeds before implementation is flagged."""
        # test -f on a file that exists → tautological
        (tmp_path / "existing.py").write_text("pass")
        steps = _make_steps("test -f existing.py")

        warnings = check_verify_commands_red(steps, str(tmp_path))

        assert len(warnings) == 1
        assert warnings[0]["step_number"] == 1
        assert "tautological" in warnings[0]["warning"]

    def test_command_exits_nonzero_no_warning(self, tmp_path: Any) -> None:
        """A command that fails before implementation is good — real check."""
        steps = _make_steps("test -f nonexistent_file.py")

        warnings = check_verify_commands_red(steps, str(tmp_path))

        assert len(warnings) == 0

    def test_none_verify_command_skipped(self, tmp_path: Any) -> None:
        """Steps without verify_command are skipped."""
        steps = _make_steps(None)

        warnings = check_verify_commands_red(steps, str(tmp_path))

        assert len(warnings) == 0

    def test_plan_defect_step_skipped(self, tmp_path: Any) -> None:
        """Steps marked plan_defect are skipped."""
        steps = [{"step_number": 1, "verify_command": "true", "status": "plan_defect"}]

        warnings = check_verify_commands_red(steps, str(tmp_path))

        assert len(warnings) == 0

    def test_timeout_silently_ignored(self, tmp_path: Any) -> None:
        """Commands that timeout are silently skipped."""
        steps = _make_steps("sleep 30")

        warnings = check_verify_commands_red(steps, str(tmp_path), timeout=1)

        assert len(warnings) == 0

    def test_multiple_steps_mixed(self, tmp_path: Any) -> None:
        """Mix of passing and failing commands."""
        (tmp_path / "exists.txt").write_text("hello")
        steps = _make_steps(
            "test -f exists.txt",       # passes → warning
            "test -f missing.txt",       # fails → no warning
        )

        warnings = check_verify_commands_red(steps, str(tmp_path))

        assert len(warnings) == 1
        assert warnings[0]["step_number"] == 1

    def test_subprocess_error_silently_ignored(self, tmp_path: Any) -> None:
        """Generic subprocess errors are silently skipped."""
        steps = _make_steps("some_command")

        with patch("subprocess.run", side_effect=OSError("mock error")):
            warnings = check_verify_commands_red(steps, str(tmp_path))

        assert len(warnings) == 0
