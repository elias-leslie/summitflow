"""Smoke testing and targeted test execution for changed Python files.

Automatically detects and imports changed modules to catch import-time errors.
Also runs existing pytest test files for changed source files.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from ...core.debug import debug_error, debug_success
from ...logging_config import get_logger
from ...storage.projects import build_project_env
from .step_builders import find_test_file
from .verification_helpers import detect_changed_files, file_to_module

logger = get_logger(__name__)


@dataclass
class SmokeTestResult:
    """Result of a smoke test on changed files."""

    passed: bool
    files_tested: list[str] = field(default_factory=list)
    failures: list[dict[str, str]] = field(default_factory=list)


def smoke_test_module(
    project_path: str,
    module_name: str,
    env: dict[str, str],
) -> dict[str, str] | None:
    """Attempt to import a module to catch import-time errors.

    Uses the resolved project env (with correct venv on PATH) so bare
    'python' resolves to the project's interpreter.

    Args:
        project_path: Project root (or worktree path)
        module_name: Dotted module name like 'cli.output'
        env: Pre-built environment dict from build_project_env()

    Returns:
        Error dict with 'module' and 'error' keys, or None if passed.
    """
    backend_path = Path(project_path) / "backend"
    import_cmd = f"import {module_name}"

    try:
        result = subprocess.run(
            ["python", "-c", import_cmd],
            cwd=str(backend_path) if backend_path.exists() else project_path,
            capture_output=True,
            text=True,
            timeout=30,
            env=env,
        )

        if result.returncode != 0:
            error_msg = result.stderr.strip()
            # Extract the actual error from traceback
            if "Error:" in error_msg:
                error_lines = error_msg.split("\n")
                error_msg = next(
                    (line for line in reversed(error_lines) if "Error:" in line),
                    error_msg[-500:],
                )
            return {"module": module_name, "error": error_msg[:500]}

        return None

    except subprocess.TimeoutExpired:
        return {"module": module_name, "error": "import timed out after 30s"}
    except Exception as e:
        return {"module": module_name, "error": str(e)[:500]}


def run_smoke_tests(
    project_path: str,
    changed_files: list[str] | None = None,
    project_id: str | None = None,
) -> SmokeTestResult:
    """Run smoke tests on changed Python files.

    Automatically detects changed files if not provided.
    Tests each file by attempting to import its module.

    Args:
        project_path: Project root path
        changed_files: Optional list of changed files (auto-detected if None)
        project_id: Project ID for resolving venv

    Returns:
        SmokeTestResult with pass/fail status and any failures.
    """
    if changed_files is None:
        changed_files = detect_changed_files(project_path)

    if not changed_files:
        logger.info("smoke_test_skipped", reason="no changed files")
        return SmokeTestResult(passed=True)

    env = build_project_env(project_id)
    failures: list[dict[str, str]] = []
    tested: list[str] = []

    for file_path in changed_files:
        module_name = file_to_module(project_path, file_path)
        if not module_name:
            continue

        tested.append(module_name)
        error = smoke_test_module(project_path, module_name, env)
        if error:
            failures.append(error)
            logger.warning(
                "smoke_test_failed",
                module=module_name,
                error=error["error"][:200],
            )
        else:
            debug_success(f"Smoke test passed: {module_name}")

    passed = len(failures) == 0
    if passed:
        logger.info("smoke_tests_passed", tested=len(tested))
    else:
        logger.error(
            "smoke_tests_failed",
            tested=len(tested),
            failed=len(failures),
            failures=failures,
        )
        debug_error(
            "Smoke tests failed",
            tested=len(tested),
            failed=len(failures),
        )

    return SmokeTestResult(
        passed=passed,
        files_tested=tested,
        failures=failures,
    )


@dataclass
class TargetedTestResult:
    """Result of running targeted tests for changed files."""

    passed: bool
    tests_run: list[str] = field(default_factory=list)
    tests_skipped: list[str] = field(default_factory=list)
    failures: list[dict[str, str]] = field(default_factory=list)


def run_targeted_tests(
    project_path: str,
    changed_files: list[str] | None = None,
    project_id: str | None = None,
) -> TargetedTestResult:
    """Run existing pytest test files for changed source files.

    For each changed Python file, finds the corresponding test file
    (e.g., app/storage/steps.py -> tests/storage/test_steps.py).
    Runs pytest only if the test file exists. Files without tests are skipped.

    Args:
        project_path: Project root path
        changed_files: Optional list of changed files (auto-detected if None)
        project_id: Project ID for resolving venv

    Returns:
        TargetedTestResult with pass/fail status and details.
    """
    if changed_files is None:
        changed_files = detect_changed_files(project_path)

    if not changed_files:
        logger.info("targeted_tests_skipped", reason="no changed files")
        return TargetedTestResult(passed=True)

    env = build_project_env(project_id)
    backend_path = Path(project_path) / "backend"
    cwd = str(backend_path) if backend_path.is_dir() else project_path

    # Collect unique test files to run
    test_files: dict[str, str] = {}  # test_path -> source_path
    skipped: list[str] = []

    for file_path in changed_files:
        if not file_path.endswith(".py"):
            continue

        test_path = find_test_file(file_path)
        if not test_path:
            skipped.append(file_path)
            continue

        # Resolve absolute path to check existence
        abs_test = Path(project_path) / test_path
        if not abs_test.is_file():
            skipped.append(file_path)
            continue

        # Strip backend/ prefix for pytest cwd
        pytest_path = test_path
        if pytest_path.startswith("backend/") and backend_path.is_dir():
            pytest_path = pytest_path[len("backend/"):]

        test_files[pytest_path] = file_path

    if not test_files:
        logger.info("targeted_tests_skipped", reason="no test files found", skipped=len(skipped))
        return TargetedTestResult(passed=True, tests_skipped=skipped)

    # Run all test files in a single pytest invocation
    test_paths = list(test_files.keys())
    logger.info("targeted_tests_running", count=len(test_paths), tests=test_paths[:5])

    try:
        result = subprocess.run(
            ["pytest", *test_paths, "-q", "--tb=short", "-x"],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=120,
            env=env,
        )

        if result.returncode == 0:
            logger.info("targeted_tests_passed", count=len(test_paths))
            return TargetedTestResult(
                passed=True,
                tests_run=test_paths,
                tests_skipped=skipped,
            )

        # Parse failure output
        error_output = result.stdout[-1000:] if result.stdout else result.stderr[-1000:]
        failures = [{"test_files": ", ".join(test_paths), "error": error_output}]

        logger.warning(
            "targeted_tests_failed",
            count=len(test_paths),
            returncode=result.returncode,
            output=error_output[:300],
        )
        debug_error(
            "Targeted tests failed",
            tests=len(test_paths),
            returncode=result.returncode,
        )

        return TargetedTestResult(
            passed=False,
            tests_run=test_paths,
            tests_skipped=skipped,
            failures=failures,
        )

    except subprocess.TimeoutExpired:
        logger.warning("targeted_tests_timeout", tests=test_paths[:5])
        return TargetedTestResult(
            passed=False,
            tests_run=test_paths,
            tests_skipped=skipped,
            failures=[{"test_files": ", ".join(test_paths), "error": "pytest timed out after 120s"}],
        )
    except Exception as e:
        logger.warning("targeted_tests_error", error=str(e))
        return TargetedTestResult(
            passed=False,
            tests_run=test_paths,
            tests_skipped=skipped,
            failures=[{"test_files": ", ".join(test_paths), "error": str(e)[:500]}],
        )
