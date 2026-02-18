"""Unit tests for step_builders module."""

from __future__ import annotations

from app.tasks.autonomous.step_builders import (
    calculate_target_lines,
    find_test_file,
    get_targeted_test_command,
)


class TestFindTestFile:
    """Tests for find_test_file function."""

    def test_nested_path_app(self) -> None:
        """Test nested path in app directory."""
        result = find_test_file("backend/app/tasks/autonomous/step_builders.py")
        assert result == "backend/tests/tasks/autonomous/test_step_builders.py"

    def test_nested_path_cli(self) -> None:
        """Test nested path in cli directory."""
        result = find_test_file("backend/cli/commands/step.py")
        assert result == "backend/tests/commands/test_step.py"

    def test_direct_app_path(self) -> None:
        """Test direct path in app directory (no subdirectories)."""
        result = find_test_file("backend/app/models.py")
        assert result == "backend/tests/test_models.py"

    def test_direct_cli_path(self) -> None:
        """Test direct path in cli directory (no subdirectories)."""
        result = find_test_file("backend/cli/utils.py")
        assert result == "backend/tests/test_utils.py"

    def test_non_matching_path_frontend(self) -> None:
        """Test frontend path returns None."""
        result = find_test_file("frontend/src/App.tsx")
        assert result is None

    def test_non_python_file(self) -> None:
        """Test non-Python file returns None."""
        result = find_test_file("README.md")
        assert result is None

    def test_root_level_main(self) -> None:
        """Test root-level Python file in app."""
        result = find_test_file("backend/app/main.py")
        assert result == "backend/tests/test_main.py"

    def test_deeply_nested_path(self) -> None:
        """Test deeply nested path."""
        result = find_test_file("backend/app/tasks/autonomous/exec_modules/steps.py")
        assert result == "backend/tests/tasks/autonomous/exec_modules/test_steps.py"

    def test_storage_module(self) -> None:
        """Test storage module path."""
        result = find_test_file("backend/app/storage/steps.py")
        assert result == "backend/tests/storage/test_steps.py"

    def test_no_backend_prefix(self) -> None:
        """Test path without backend prefix returns None."""
        result = find_test_file("app/tasks/foo.py")
        assert result is None

    def test_no_app_or_cli(self) -> None:
        """Test path without app or cli returns None."""
        result = find_test_file("backend/other/foo.py")
        assert result is None


class TestCalculateTargetLines:
    """Tests for calculate_target_lines function."""

    def test_small_file_no_refactor(self) -> None:
        """Files <= 150 lines should not be refactored."""
        assert calculate_target_lines(100) == 100
        assert calculate_target_lines(150) == 150

    def test_medium_small_files(self) -> None:
        """Files 151-300 lines should target 150."""
        assert calculate_target_lines(151) == 150
        assert calculate_target_lines(250) == 150
        assert calculate_target_lines(300) == 150

    def test_medium_files(self) -> None:
        """Files 301-500 lines should target 200."""
        assert calculate_target_lines(301) == 200
        assert calculate_target_lines(400) == 200
        assert calculate_target_lines(500) == 200

    def test_medium_large_files(self) -> None:
        """Files 501-1000 lines should target 300."""
        assert calculate_target_lines(501) == 300
        assert calculate_target_lines(750) == 300
        assert calculate_target_lines(1000) == 300

    def test_large_files(self) -> None:
        """Files > 1000 lines should target 500."""
        assert calculate_target_lines(1001) == 500
        assert calculate_target_lines(2000) == 500
        assert calculate_target_lines(5000) == 500


class TestGetTargetedTestCommand:
    """Tests for get_targeted_test_command function."""

    def test_nested_path_with_test_file(self) -> None:
        """Test command for nested path with test file."""
        cmd = get_targeted_test_command("backend/app/tasks/autonomous/step_builders.py")
        assert "backend/tests/tasks/autonomous/test_step_builders.py" in cmd
        assert "pytest" in cmd
        assert "--tb=short" in cmd

    def test_frontend_file(self) -> None:
        """Test command for frontend file."""
        cmd = get_targeted_test_command("frontend/src/App.tsx")
        assert "npm run build" in cmd
        assert "frontend" in cmd

    def test_direct_app_path_with_test_file(self) -> None:
        """Test command for direct app path."""
        cmd = get_targeted_test_command("backend/app/models.py")
        assert "backend/tests/test_models.py" in cmd
        assert "pytest" in cmd
