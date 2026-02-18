"""Tests for storage-layer verify_command validation.

Covers trivial command detection and absolute path rejection
in sanitize_verify_command().
"""

from __future__ import annotations

import pytest

from app.storage.steps_crud_validation import sanitize_verify_command


class TestSanitizePassthrough:
    """None and valid commands pass through unchanged."""

    def test_none_passes_through(self) -> None:
        assert sanitize_verify_command(None) is None

    def test_empty_string_passes_through(self) -> None:
        assert sanitize_verify_command("") == ""

    @pytest.mark.parametrize(
        "cmd",
        [
            "rg -q 'pattern' file.py",
            "test -f backend/app/main.py",
            "dt pytest tests/test_foo.py -q",
            "dt --quick --changed-only",
            "python -c 'import app.main'",
            "echo 'checking' && rg -q 'def main' app.py",
            "dt ruff check app/",
            "dt types app/main.py",
        ],
        ids=["rg", "test_f", "dt_pytest", "dt_quick", "python_import", "echo_compound", "dt_ruff", "dt_types"],
    )
    def test_valid_commands_pass_through(self, cmd: str) -> None:
        assert sanitize_verify_command(cmd) == cmd


class TestTrivialCommandRejection:
    """Trivial commands that always exit 0 are rejected."""

    @pytest.mark.parametrize(
        "cmd,match",
        [
            ("true", "always exits 0"),
            (":", "always exits 0"),
            ("exit 0", "always exits 0"),
        ],
        ids=["true", "colon", "exit_0"],
    )
    def test_noop_raises(self, cmd: str, match: str) -> None:
        with pytest.raises(ValueError, match=match):
            sanitize_verify_command(cmd)

    @pytest.mark.parametrize(
        "cmd",
        [
            "echo ok",
            "echo 'Found it'",
            "Echo Done",
            "echo hello world",
        ],
        ids=["echo_ok", "echo_quoted", "echo_case", "echo_multi_word"],
    )
    def test_echo_only_raises(self, cmd: str) -> None:
        with pytest.raises(ValueError, match="echo-only"):
            sanitize_verify_command(cmd)

    def test_echo_with_and_operator_allowed(self) -> None:
        cmd = "echo 'checking' && test -f file.py"
        assert sanitize_verify_command(cmd) == cmd

    def test_whitespace_only_raises(self) -> None:
        with pytest.raises(ValueError, match="empty"):
            sanitize_verify_command("   ")

    def test_comment_only_raises(self) -> None:
        with pytest.raises(ValueError, match="comment"):
            sanitize_verify_command("# just a note")


class TestRawToolRejection:
    """Raw tools that should be wrapped by dt are rejected."""

    @pytest.mark.parametrize(
        "cmd,tool",
        [
            ("pytest tests/test_foo.py -q", "pytest"),
            ("ty check app/main.py", "types"),
            ("ruff check app/", "ruff"),
            ("biome check src/", "biome"),
            ("tsc --noEmit", "tsc"),
            (".venv/bin/pytest tests/ -x", "pytest"),
            ("npx biome check .", "biome"),
            ("python -m pytest tests/", "pytest"),
        ],
        ids=["pytest", "types", "ruff", "biome", "tsc", "venv_pytest", "npx_biome", "python_m_pytest"],
    )
    def test_raw_tool_raises(self, cmd: str, tool: str) -> None:
        with pytest.raises(ValueError, match=f"Raw '{tool}'"):
            sanitize_verify_command(cmd)

    @pytest.mark.parametrize(
        "cmd",
        [
            "dt pytest tests/test_foo.py -q",
            "dt types app/main.py",
            "dt ruff check app/",
            "dt biome check src/",
            "dt tsc --noEmit",
            "dt --quick",
            "dt --fix && dt --quick --changed-only",
        ],
        ids=["dt_pytest", "dt_types", "dt_ruff", "dt_biome", "dt_tsc", "dt_quick", "dt_compound"],
    )
    def test_dt_wrapped_tools_allowed(self, cmd: str) -> None:
        assert sanitize_verify_command(cmd) == cmd


class TestAbsolutePathRejection:
    """Absolute paths that break worktree isolation are rejected."""

    @pytest.mark.parametrize(
        "cmd",
        [
            "cd /home/user/project && rg 'x' file",
            "cat /home/user/project/file.txt",
            "ls /tmp/test-output",
            "test -f /opt/app/config.yaml",
        ],
        ids=["cd_abs", "home_abs", "tmp_abs", "opt_abs"],
    )
    def test_absolute_path_raises(self, cmd: str) -> None:
        with pytest.raises(ValueError, match="absolute path"):
            sanitize_verify_command(cmd)
