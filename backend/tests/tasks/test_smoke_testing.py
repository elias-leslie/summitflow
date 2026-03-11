"""Unit tests for smoke_testing module."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

from app.tasks.autonomous.smoke_testing import (
    run_smoke_tests,
    run_targeted_tests,
    smoke_test_module,
)


class TestSmokeTestModule:
    """Tests for smoke_test_module function."""

    @patch("app.tasks.autonomous.smoke_testing.subprocess.run")
    def test_successful_import(self, mock_run: MagicMock) -> None:
        """Test successful module import."""
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")

        result = smoke_test_module(
            "/home/user/project",
            "app.models",
            {"PATH": "/usr/bin"},
        )

        assert result is None
        mock_run.assert_called_once()
        assert "import app.models" in mock_run.call_args[0][0]

    @patch("app.tasks.autonomous.smoke_testing.subprocess.run")
    def test_import_error(self, mock_run: MagicMock) -> None:
        """Test module import failure."""
        mock_run.return_value = MagicMock(
            returncode=1,
            stdout="",
            stderr="ImportError: No module named 'foo'",
        )

        result = smoke_test_module(
            "/home/user/project",
            "app.models",
            {"PATH": "/usr/bin"},
        )

        assert result is not None
        assert result["module"] == "app.models"
        assert "ImportError" in result["error"]

    @patch("app.tasks.autonomous.smoke_testing.subprocess.run")
    def test_import_timeout(self, mock_run: MagicMock) -> None:
        """Test module import timeout."""
        import subprocess
        mock_run.side_effect = subprocess.TimeoutExpired("python", 30)

        result = smoke_test_module(
            "/home/user/project",
            "app.models",
            {"PATH": "/usr/bin"},
        )

        assert result is not None
        assert result["module"] == "app.models"
        assert "timed out" in result["error"]


class TestRunSmokeTests:
    """Tests for run_smoke_tests function."""

    @patch("app.tasks.autonomous.smoke_testing.detect_changed_files")
    @patch("app.tasks.autonomous.smoke_testing.build_project_env")
    def test_no_changed_files(self, mock_env: MagicMock, mock_detect: MagicMock) -> None:
        """Test with no changed files."""
        mock_detect.return_value = []
        mock_env.return_value = {}

        result = run_smoke_tests("/home/user/project")

        assert result.passed
        assert result.files_tested == []
        assert result.failures == []

    @patch("app.tasks.autonomous.smoke_testing.smoke_test_module")
    @patch("app.tasks.autonomous.smoke_testing.file_to_module")
    @patch("app.tasks.autonomous.smoke_testing.build_project_env")
    def test_successful_smoke_tests(
        self, mock_env: MagicMock, mock_file_to_module: MagicMock, mock_smoke: MagicMock
    ) -> None:
        """Test successful smoke tests for changed files."""
        mock_env.return_value = {}
        mock_file_to_module.side_effect = lambda proj, f: (
            "app.models" if f == "backend/app/models.py" else None
        )
        mock_smoke.return_value = None  # Success

        result = run_smoke_tests(
            "/home/user/project",
            changed_files=["backend/app/models.py"],
        )

        assert result.passed
        assert "app.models" in result.files_tested
        assert result.failures == []

    @patch("app.tasks.autonomous.smoke_testing.smoke_test_module")
    @patch("app.tasks.autonomous.smoke_testing.file_to_module")
    @patch("app.tasks.autonomous.smoke_testing.build_project_env")
    def test_failed_smoke_test(
        self, mock_env: MagicMock, mock_file_to_module: MagicMock, mock_smoke: MagicMock
    ) -> None:
        """Test failed smoke test for changed file."""
        mock_env.return_value = {}
        mock_file_to_module.return_value = "app.models"
        mock_smoke.return_value = {
            "module": "app.models",
            "error": "ImportError: No module named 'foo'",
        }

        result = run_smoke_tests(
            "/home/user/project",
            changed_files=["backend/app/models.py"],
        )

        assert not result.passed
        assert "app.models" in result.files_tested
        assert len(result.failures) == 1
        assert result.failures[0]["module"] == "app.models"

    @patch("app.tasks.autonomous.smoke_testing.smoke_test_module")
    @patch("app.tasks.autonomous.smoke_testing.file_to_module")
    @patch("app.tasks.autonomous.smoke_testing.build_project_env")
    def test_skip_non_python_files(
        self, mock_env: MagicMock, mock_file_to_module: MagicMock, mock_smoke: MagicMock
    ) -> None:
        """Test that non-Python files are skipped."""
        mock_env.return_value = {}
        mock_file_to_module.return_value = None  # Non-Python file

        result = run_smoke_tests(
            "/home/user/project",
            changed_files=["README.md", "frontend/src/App.tsx"],
        )

        assert result.passed
        assert result.files_tested == []
        mock_smoke.assert_not_called()


class TestRunTargetedTests:
    """Tests for run_targeted_tests function."""

    @patch("app.tasks.autonomous.smoke_testing.detect_changed_files")
    @patch("app.tasks.autonomous.smoke_testing.build_project_env")
    def test_no_changed_files(self, mock_env: MagicMock, mock_detect: MagicMock) -> None:
        """Test with no changed files."""
        mock_detect.return_value = []
        mock_env.return_value = {}

        result = run_targeted_tests("/home/user/project")

        assert result.passed
        assert result.tests_run == []
        assert result.tests_skipped == []

    @patch("app.tasks.autonomous.smoke_testing.subprocess.run")
    @patch("app.tasks.autonomous.smoke_testing.find_test_file")
    @patch("app.tasks.autonomous.smoke_testing.build_project_env")
    @patch("app.tasks.autonomous.smoke_testing.Path")
    def test_successful_targeted_tests(
        self,
        mock_path_cls: MagicMock,
        mock_env: MagicMock,
        mock_find: MagicMock,
        mock_run: MagicMock,
    ) -> None:
        """Test successful targeted tests for changed files."""
        mock_env.return_value = {}
        mock_find.return_value = "backend/tests/test_models.py"

        # Mock Path for backend directory check
        mock_backend_path = MagicMock()
        mock_backend_path.is_dir.return_value = True

        # Mock Path for test file existence check
        mock_test_file = MagicMock()
        mock_test_file.is_file.return_value = True

        def path_side_effect(p: Any) -> MagicMock:
            if p == "backend":
                return mock_backend_path
            elif "backend/tests/test_models.py" in str(p):
                return mock_test_file
            return MagicMock()

        mock_path_cls.side_effect = path_side_effect

        # Mock successful pytest run
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")

        result = run_targeted_tests(
            "/home/user/project",
            changed_files=["backend/app/models.py"],
        )

        assert result.passed
        assert "tests/test_models.py" in result.tests_run
        assert result.failures == []

    @patch("app.tasks.autonomous.smoke_testing.subprocess.run")
    @patch("app.tasks.autonomous.smoke_testing.find_test_file")
    @patch("app.tasks.autonomous.smoke_testing.build_project_env")
    @patch("app.tasks.autonomous.smoke_testing.Path")
    def test_failed_targeted_tests(
        self,
        mock_path_cls: MagicMock,
        mock_env: MagicMock,
        mock_find: MagicMock,
        mock_run: MagicMock,
    ) -> None:
        """Test failed targeted tests for changed files."""
        mock_env.return_value = {}
        mock_find.return_value = "backend/tests/test_models.py"

        # Mock Path for backend directory check
        mock_backend_path = MagicMock()
        mock_backend_path.is_dir.return_value = True

        # Mock Path for test file existence check
        mock_test_file = MagicMock()
        mock_test_file.is_file.return_value = True

        def path_side_effect(p: Any) -> MagicMock:
            if p == "backend":
                return mock_backend_path
            elif "backend/tests/test_models.py" in str(p):
                return mock_test_file
            return MagicMock()

        mock_path_cls.side_effect = path_side_effect

        # Mock failed pytest run
        mock_run.return_value = MagicMock(
            returncode=1,
            stdout="FAILED tests/test_models.py::test_foo - AssertionError",
            stderr="",
        )

        result = run_targeted_tests(
            "/home/user/project",
            changed_files=["backend/app/models.py"],
        )

        assert not result.passed
        assert "tests/test_models.py" in result.tests_run
        assert len(result.failures) == 1

    @patch("app.tasks.autonomous.smoke_testing.find_test_file")
    @patch("app.tasks.autonomous.smoke_testing.build_project_env")
    def test_skip_files_without_tests(self, mock_env: MagicMock, mock_find: MagicMock) -> None:
        """Test that files without corresponding test files are skipped."""
        mock_env.return_value = {}
        mock_find.return_value = None  # No test file found

        result = run_targeted_tests(
            "/home/user/project",
            changed_files=["backend/app/models.py"],
        )

        assert result.passed
        assert result.tests_run == []
        assert "backend/app/models.py" in result.tests_skipped

    @patch("app.tasks.autonomous.smoke_testing.find_test_file")
    @patch("app.tasks.autonomous.smoke_testing.build_project_env")
    @patch("app.tasks.autonomous.smoke_testing.Path")
    def test_skip_files_with_nonexistent_test_file(
        self, mock_path_cls: MagicMock, mock_env: MagicMock, mock_find: MagicMock
    ) -> None:
        """Test that files with test path but file doesn't exist are skipped."""
        mock_env.return_value = {}
        mock_find.return_value = "backend/tests/test_models.py"

        # Mock the Path instances
        # First call: Path(project_path) / "backend" -> for cwd check
        mock_backend_path = MagicMock(**{"__str__": lambda self: "/home/user/project/backend"})
        mock_backend_path.is_dir.return_value = True
        mock_backend_path.__truediv__ = MagicMock(return_value=mock_backend_path)

        # Second call: Path(project_path) / test_path -> for file existence check
        mock_test_file_path = MagicMock()
        mock_test_file_path.is_file.return_value = False  # File doesn't exist
        mock_test_file_path.is_dir.return_value = True

        # Setup Path class mock to return different objects
        mock_project_path = MagicMock()
        mock_project_path.__truediv__ = MagicMock(side_effect=[mock_backend_path, mock_test_file_path])

        mock_path_cls.return_value = mock_project_path

        result = run_targeted_tests(
            "/home/user/project",
            changed_files=["backend/app/models.py"],
        )

        assert result.passed
        assert result.tests_run == []
        assert "backend/app/models.py" in result.tests_skipped

    @patch("app.tasks.autonomous.smoke_testing.find_test_file")
    @patch("app.tasks.autonomous.smoke_testing.build_project_env")
    def test_skip_non_python_files(self, mock_env: MagicMock, mock_find: MagicMock) -> None:
        """Test that non-Python files are skipped."""
        mock_env.return_value = {}

        result = run_targeted_tests(
            "/home/user/project",
            changed_files=["README.md", "frontend/src/App.tsx"],
        )

        assert result.passed
        assert result.tests_run == []
        mock_find.assert_not_called()

    @patch("app.tasks.autonomous.smoke_testing.subprocess.run")
    @patch("app.tasks.autonomous.smoke_testing.find_test_file")
    @patch("app.tasks.autonomous.smoke_testing.build_project_env")
    @patch("app.tasks.autonomous.smoke_testing.Path")
    def test_pytest_timeout(
        self,
        mock_path_cls: MagicMock,
        mock_env: MagicMock,
        mock_find: MagicMock,
        mock_run: MagicMock,
    ) -> None:
        """Test pytest timeout handling."""
        import subprocess
        mock_env.return_value = {}
        mock_find.return_value = "backend/tests/test_models.py"

        # Mock Path for checks
        mock_backend_path = MagicMock()
        mock_backend_path.is_dir.return_value = True
        mock_test_file = MagicMock()
        mock_test_file.is_file.return_value = True

        def path_side_effect(p: Any) -> MagicMock:
            if p == "backend":
                return mock_backend_path
            elif "backend/tests/test_models.py" in str(p):
                return mock_test_file
            return MagicMock()

        mock_path_cls.side_effect = path_side_effect

        # Mock timeout
        mock_run.side_effect = subprocess.TimeoutExpired("pytest", 120)

        result = run_targeted_tests(
            "/home/user/project",
            changed_files=["backend/app/models.py"],
        )

        assert not result.passed
        assert len(result.failures) == 1
        assert "timed out" in result.failures[0]["error"]
