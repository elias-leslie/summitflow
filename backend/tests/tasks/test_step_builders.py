"""Unit tests for step_builders module."""

from __future__ import annotations

from app.tasks.autonomous.step_builders import (
    build_refactor_steps,
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


class TestBuildRefactorSteps:
    """Tests for issue-aware build_refactor_steps."""

    def test_size_issue_includes_line_count_step(self) -> None:
        """Files with size issues get line count verification."""
        steps = build_refactor_steps(
            "backend/app/services/foo.py", "/abs/path", 400, 200, False,
            refactor_issues=["large_file", "has_long_functions"],
        )
        assert any("wc -l" in s["verify_command"] for s in steps)

    def test_no_size_issue_skips_line_count_step(self) -> None:
        """Files without size issues skip line count verification."""
        steps = build_refactor_steps(
            "backend/app/services/foo.py", "/abs/path", 200, 150, False,
            refactor_issues=["deep_nesting", "has_long_functions"],
        )
        assert not any("wc -l" in s["verify_command"] for s in steps)

    def test_structural_issues_get_ast_verification(self) -> None:
        """Structural issues generate stdlib ast-based verify commands."""
        steps = build_refactor_steps(
            "backend/app/services/foo.py", "/abs/path", 200, 150, False,
            refactor_issues=["has_long_functions", "deep_nesting"],
        )
        structural_step = [s for s in steps if "structural" in s["description"].lower()]
        assert len(structural_step) == 1
        cmd = structural_step[0]["verify_command"]
        assert "import ast" in cmd
        assert "col_offset" in cmd  # nesting depth check
        assert "end_lineno" in cmd  # function line check

    def test_too_many_functions_verified(self) -> None:
        """too_many_functions generates function count check."""
        steps = build_refactor_steps(
            "backend/app/services/foo.py", "/abs/path", 200, 150, False,
            refactor_issues=["too_many_functions"],
        )
        structural = [s for s in steps if "structural" in s["description"].lower()]
        assert len(structural) == 1
        cmd = structural[0]["verify_command"]
        assert "import ast" in cmd
        assert "<=20" in cmd
        assert "FunctionDef" in cmd

    def test_too_many_classes_verified(self) -> None:
        """too_many_classes generates class count check."""
        steps = build_refactor_steps(
            "backend/app/services/foo.py", "/abs/path", 200, 150, False,
            refactor_issues=["too_many_classes"],
        )
        structural = [s for s in steps if "structural" in s["description"].lower()]
        assert len(structural) == 1
        cmd = structural[0]["verify_command"]
        assert "import ast" in cmd
        assert "<=5" in cmd
        assert "ClassDef" in cmd

    def test_has_large_classes_verified(self) -> None:
        """has_large_classes generates method count check."""
        steps = build_refactor_steps(
            "backend/app/services/foo.py", "/abs/path", 200, 150, False,
            refactor_issues=["has_large_classes"],
        )
        structural = [s for s in steps if "structural" in s["description"].lower()]
        assert len(structural) == 1
        cmd = structural[0]["verify_command"]
        assert "import ast" in cmd
        assert ">10" in cmd
        assert "ClassDef" in cmd

    def test_too_many_imports_verified(self) -> None:
        """too_many_imports generates import count check."""
        steps = build_refactor_steps(
            "backend/app/services/foo.py", "/abs/path", 200, 150, False,
            refactor_issues=["too_many_imports"],
        )
        structural = [s for s in steps if "structural" in s["description"].lower()]
        assert len(structural) == 1
        assert "grep" in structural[0]["verify_command"]
        assert "30" in structural[0]["verify_command"]

    def test_quality_gate_always_present(self) -> None:
        """Quality gate step is always included."""
        steps = build_refactor_steps(
            "backend/app/services/foo.py", "/abs/path", 200, 150, False,
            refactor_issues=["deep_nesting"],
        )
        assert any("quality gate" in s["description"].lower() for s in steps)

    def test_frontend_browser_check(self) -> None:
        """Frontend files get browser verification step."""
        steps = build_refactor_steps(
            "frontend/components/Foo.tsx", "/abs/path", 400, 200, True,
            refactor_issues=["large_file"],
        )
        assert any("agent-browser" in s["verify_command"] for s in steps)

    def test_no_issues_falls_back_to_line_count(self) -> None:
        """Empty issues list falls back to line count check."""
        steps = build_refactor_steps(
            "backend/app/services/foo.py", "/abs/path", 400, 200, False,
            refactor_issues=[],
        )
        assert any("wc -l" in s["verify_command"] for s in steps)
