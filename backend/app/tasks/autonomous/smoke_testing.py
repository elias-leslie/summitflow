"""Smoke testing for changed Python files.

Automatically detects and imports changed modules to catch import-time errors.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from ...core.debug import debug_error, debug_success
from ...logging_config import get_logger
from ...storage.projects import build_project_env
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
