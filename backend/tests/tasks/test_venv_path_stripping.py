"""Tests for .venv path stripping in command expansion.

Ensures all .venv/bin/X patterns are rewritten to bare X when venv is on PATH.
This prevents exit 127 failures in worktrees where .venv doesn't exist locally.

Regression test for: 873ad45f removed _resolve_venv_paths() and replaced with
build_project_env() PATH injection, but didn't add command-text stripping.
"""

from __future__ import annotations

from app.tasks.autonomous.verification_helpers import expand_command, strip_venv_paths


class TestStripVenvPaths:
    """strip_venv_paths() must remove all .venv/bin/X -> X patterns."""

    # --- Pattern 1: bare .venv/bin/X ---

    def test_bare_venv_bin(self) -> None:
        assert strip_venv_paths(".venv/bin/ruff check app/") == "ruff check app/"

    def test_bare_venv_bin_python(self) -> None:
        assert strip_venv_paths(".venv/bin/python -c 'import foo'") == "python -c 'import foo'"

    def test_bare_venv_bin_pytest(self) -> None:
        assert strip_venv_paths(".venv/bin/pytest tests/ -v") == "pytest tests/ -v"

    def test_bare_venv_bin_mypy(self) -> None:
        assert strip_venv_paths(".venv/bin/mypy app --strict") == "mypy app --strict"

    def test_bare_venv_bin_alembic(self) -> None:
        assert strip_venv_paths(".venv/bin/alembic current") == "alembic current"

    def test_bare_venv_bin_pip(self) -> None:
        assert strip_venv_paths(".venv/bin/pip show foo") == "pip show foo"

    # --- Pattern 2: backend/.venv/bin/X ---

    def test_backend_venv_bin(self) -> None:
        assert strip_venv_paths("backend/.venv/bin/pytest tests/ -q") == "pytest tests/ -q"

    def test_backend_venv_bin_ruff(self) -> None:
        assert strip_venv_paths("backend/.venv/bin/ruff check app/storage/steps.py") == (
            "ruff check app/storage/steps.py"
        )

    # --- Pattern 3: cd backend && .venv/bin/X ---

    def test_cd_backend_then_venv(self) -> None:
        assert strip_venv_paths("cd backend && .venv/bin/ruff check app/storage/steps.py") == (
            "cd backend && ruff check app/storage/steps.py"
        )

    def test_cd_backend_then_venv_mypy(self) -> None:
        assert strip_venv_paths("cd backend && .venv/bin/mypy app") == "cd backend && mypy app"

    def test_cd_backend_then_venv_pytest(self) -> None:
        assert strip_venv_paths("cd backend && .venv/bin/pytest tests/ -v") == (
            "cd backend && pytest tests/ -v"
        )

    def test_cd_backend_then_venv_python(self) -> None:
        cmd = "cd backend && .venv/bin/python -c 'from app.storage import steps'"
        expected = "cd backend && python -c 'from app.storage import steps'"
        assert strip_venv_paths(cmd) == expected

    # --- Pattern 4: source .venv/bin/activate && X ---

    def test_source_activate_stripped(self) -> None:
        cmd = "cd backend && source .venv/bin/activate && python -c 'import foo'"
        expected = "cd backend && python -c 'import foo'"
        assert strip_venv_paths(cmd) == expected

    def test_source_activate_with_dot(self) -> None:
        cmd = ". .venv/bin/activate && pytest tests/"
        expected = "pytest tests/"
        assert strip_venv_paths(cmd) == expected

    def test_source_backend_activate(self) -> None:
        cmd = "source backend/.venv/bin/activate && python -m pytest"
        expected = "python -m pytest"
        assert strip_venv_paths(cmd) == expected

    # --- Pattern 5: no .venv -- passthrough ---

    def test_no_venv_unchanged(self) -> None:
        cmd = "dt --quick"
        assert strip_venv_paths(cmd) == cmd

    def test_echo_unchanged(self) -> None:
        cmd = "echo hello"
        assert strip_venv_paths(cmd) == cmd

    def test_git_log_unchanged(self) -> None:
        cmd = "git log --oneline -1"
        assert strip_venv_paths(cmd) == cmd

    # --- Pattern 6: multiple .venv references in one command ---

    def test_multiple_venv_refs(self) -> None:
        cmd = ".venv/bin/ruff check app/ && .venv/bin/mypy app/"
        expected = "ruff check app/ && mypy app/"
        assert strip_venv_paths(cmd) == expected

    # --- Pattern 7: DEBUG=true prefix with .venv ---

    def test_env_var_prefix_with_venv(self) -> None:
        cmd = "cd backend && DEBUG=true .venv/bin/python -c 'print(1)'"
        expected = "cd backend && DEBUG=true python -c 'print(1)'"
        assert strip_venv_paths(cmd) == expected


class TestExpandCommandWithVenvStripping:
    """expand_command() must also strip .venv paths."""

    def test_expand_strips_venv(self) -> None:
        cmd = "cd backend && .venv/bin/ruff check app/"
        result = expand_command(cmd)
        assert ".venv" not in result
        assert result == "cd backend && ruff check app/"

    def test_expand_alias_and_strip(self) -> None:
        cmd = ".venv/bin/pytest tests/ -v"
        result = expand_command(cmd)
        assert result == "pytest tests/ -v"
