"""Smoke and targeted test verification for steps."""

from __future__ import annotations

from typing import Any

from ..smoke_testing import run_targeted_tests
from ..verification import run_smoke_tests
from .events import emit_log


def run_smoke_and_targeted_tests(
    task_id: str,
    project_path: str,
    project_id: str,
    step_results: list[dict[str, Any]],
) -> bool:
    """Run smoke tests and targeted tests on changed files.

    Args:
        task_id: Task identifier
        project_path: Path to project root
        project_id: Project identifier
        step_results: List to append test failure results to

    Returns:
        True if all tests passed, False otherwise
    """
    all_passed = True

    # Run smoke tests
    emit_log(
        task_id,
        "info",
        "Running smoke tests on changed files...",
        source="verify",
        project_id=project_id,
    )

    smoke_result = run_smoke_tests(project_path, project_id=project_id)
    if not smoke_result.passed:
        all_passed = False
        _append_smoke_test_failures(task_id, smoke_result.failures, step_results, project_id)
    else:
        tested_count = len(smoke_result.files_tested)
        if tested_count > 0:
            emit_log(
                task_id,
                "info",
                f"Smoke tests passed ({tested_count} modules)",
                source="verify",
                project_id=project_id,
            )

    # Run targeted tests
    if all_passed:
        emit_log(
            task_id,
            "info",
            "Running targeted tests for changed files...",
            source="verify",
            project_id=project_id,
        )

        test_result = run_targeted_tests(project_path, project_id=project_id)
        if test_result.tests_run:
            if not test_result.passed:
                all_passed = False
                _append_targeted_test_failures(
                    task_id, test_result.failures, step_results, project_id
                )
            else:
                emit_log(
                    task_id,
                    "info",
                    f"Targeted tests passed ({len(test_result.tests_run)} test files, "
                    f"{len(test_result.tests_skipped)} skipped)",
                    source="verify",
                    project_id=project_id,
                )

    return all_passed


def _append_smoke_test_failures(
    task_id: str,
    failures: list[dict[str, Any]],
    step_results: list[dict[str, Any]],
    project_id: str,
) -> None:
    """Append smoke test failures to step results."""
    for failure in failures:
        step_results.append(
            {
                "step_number": 999,
                "passed": False,
                "output": f"Import failed: {failure['error']}",
                "reason": f"smoke_test_failed:{failure['module']}",
                "returncode": 1,
            }
        )
        emit_log(
            task_id,
            "error",
            f"Smoke test failed: {failure['module']} - {failure['error'][:100]}",
            source="verify",
            project_id=project_id,
        )


def _append_targeted_test_failures(
    task_id: str,
    failures: list[dict[str, Any]],
    step_results: list[dict[str, Any]],
    project_id: str,
) -> None:
    """Append targeted test failures to step results."""
    for failure in failures:
        step_results.append(
            {
                "step_number": 998,
                "passed": False,
                "output": f"Tests failed: {failure['error'][:500]}",
                "reason": f"targeted_test_failed:{failure['test_files'][:100]}",
                "returncode": 1,
            }
        )
        emit_log(
            task_id,
            "error",
            f"Targeted tests failed: {failure['test_files'][:80]}",
            source="verify",
            project_id=project_id,
        )
