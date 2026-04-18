"""Quality check orchestration for subtask execution.

Relocated from the removed steps module. Runs smoke tests and targeted
tests as the primary verification signal.
"""

from __future__ import annotations

import subprocess
from typing import Any

from ....logging_config import get_logger
from ....storage.task_spirit import get_task_spirit
from ....storage.tasks import get_task
from ..smoke_testing import run_targeted_tests
from ..verification import run_smoke_tests
from .events import emit_log

logger = get_logger(__name__)

_NO_CODE_MARKERS = (
    "no code edits",
    "no product code edits",
    "do not modify product code",
    "workflow validation only",
    "workflow-only",
    "temporary validation task only",
)


def _detect_base_branch(project_path: str) -> str:
    """Detect the default branch (main, master, etc.) for a repository."""
    result = subprocess.run(
        ["git", "symbolic-ref", "refs/remotes/origin/HEAD"],
        cwd=project_path, capture_output=True, text=True, timeout=5,
    )
    if result.returncode == 0 and result.stdout.strip():
        return result.stdout.strip().rsplit("/", 1)[-1]
    return "main"


def _has_work_product(project_path: str) -> bool:
    """Check if the checkout contains branch-local work to verify."""
    try:
        base_branch = _detect_base_branch(project_path)
        commits = subprocess.run(
            ["git", "log", "--oneline", f"{base_branch}..HEAD"],
            cwd=project_path, capture_output=True, text=True, timeout=10,
        )
        if commits.returncode == 0 and commits.stdout and commits.stdout.strip():
            return True

        status = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=project_path, capture_output=True, text=True, timeout=10,
        )
        return bool(status.stdout and status.stdout.strip())
    except (subprocess.TimeoutExpired, OSError):
        return True


def _allows_no_code_verification(task_id: str) -> bool:
    """Return True when a task is explicitly scoped as workflow/no-code validation."""
    task = get_task(task_id) or {}
    spirit = get_task_spirit(task_id) or {}

    fields = [
        task.get("title", ""),
        task.get("description", ""),
        spirit.get("objective", ""),
        spirit.get("spirit_anti", ""),
        *(spirit.get("constraints") or []),
        *(spirit.get("done_when") or []),
    ]
    haystack = " ".join(str(field).lower() for field in fields if field)
    return any(marker in haystack for marker in _NO_CODE_MARKERS)


def _append_smoke_failure(
    task_id: str,
    project_id: str,
    step_results: list[dict[str, Any]],
    failure: dict[str, Any],
) -> None:
    """Record a single smoke test failure into step_results and emit a log."""
    step_results.append({
        "step_number": 999,
        "passed": False,
        "output": f"Import failed: {failure['error']}",
        "reason": f"smoke_test_failed:{failure['module']}",
        "returncode": 1,
    })
    emit_log(
        task_id, "error",
        f"Smoke test failed: {failure['module']} - {failure['error'][:100]}",
        source="verify", project_id=project_id,
    )


def _run_smoke_tests(
    task_id: str,
    project_path: str,
    project_id: str,
    step_results: list[dict[str, Any]],
) -> bool:
    """Run smoke tests and populate step_results on failure. Returns True if passed."""
    emit_log(
        task_id, "info", "Running smoke tests on changed files...",
        source="verify", project_id=project_id,
    )

    smoke_result = run_smoke_tests(project_path, project_id=project_id)

    if not smoke_result.passed:
        for failure in smoke_result.failures:
            _append_smoke_failure(task_id, project_id, step_results, failure)
        return False

    tested_count = len(smoke_result.files_tested)
    if tested_count > 0:
        emit_log(
            task_id, "info", f"Smoke tests passed ({tested_count} modules)",
            source="verify", project_id=project_id,
        )
    return True


def _append_targeted_failure(
    task_id: str,
    project_id: str,
    step_results: list[dict[str, Any]],
    failure: dict[str, Any],
) -> None:
    """Record a single targeted test failure into step_results and emit a log."""
    step_results.append({
        "step_number": 998,
        "passed": False,
        "output": f"Tests failed: {failure['error'][:500]}",
        "reason": f"targeted_test_failed:{failure['test_files'][:100]}",
        "returncode": 1,
    })
    emit_log(
        task_id, "error",
        f"Targeted tests failed: {failure['test_files'][:80]}",
        source="verify", project_id=project_id,
    )


def _run_targeted_tests(
    task_id: str,
    project_path: str,
    project_id: str,
    step_results: list[dict[str, Any]],
) -> bool:
    """Run targeted tests and populate step_results on failure. Returns True if passed."""
    emit_log(
        task_id, "info", "Running targeted tests for changed files...",
        source="verify", project_id=project_id,
    )

    test_result = run_targeted_tests(project_path, project_id=project_id)

    if not test_result.tests_run:
        return True

    if not test_result.passed:
        for failure in test_result.failures:
            _append_targeted_failure(task_id, project_id, step_results, failure)
        return False

    emit_log(
        task_id, "info",
        f"Targeted tests passed ({len(test_result.tests_run)} test files, "
        f"{len(test_result.tests_skipped)} skipped)",
        source="verify", project_id=project_id,
    )
    return True


def _run_smoke_and_targeted_tests(
    task_id: str,
    project_path: str,
    project_id: str,
    step_results: list[dict[str, Any]],
) -> bool:
    """Run smoke tests and targeted tests on changed files."""
    smoke_passed = _run_smoke_tests(task_id, project_path, project_id, step_results)
    if not smoke_passed:
        return False
    return _run_targeted_tests(task_id, project_path, project_id, step_results)


def run_execution_quality_check(
    task_id: str,
    subtask_id: str,
    steps: list[dict[str, Any]],
    project_path: str,
    project_id: str,
) -> tuple[bool, list[dict[str, Any]]]:
    """Run quality check via smoke and targeted tests.

    Steps are no longer used as individual progress trackers. The function
    signature is preserved for compatibility with the retry loop.

    Returns:
        Tuple of (all_passed, step_results)
    """
    step_results: list[dict[str, Any]] = []

    # Fail if no work product exists unless the task is explicitly no-code validation.
    if not _has_work_product(project_path) and not _allows_no_code_verification(task_id):
        logger.warning("No commits on branch - marking as failed",
                       task_id=task_id, subtask_id=subtask_id)
        step_results.append({
            "step_number": 0,
            "passed": False,
            "reason": "no_work_product",
            "output": "No commits found on branch beyond main",
            "returncode": 1,
        })
        return False, step_results

    all_passed = _run_smoke_and_targeted_tests(
        task_id, project_path, project_id, step_results
    )

    if not all_passed and not step_results:
        step_results.append({
            "step_number": 0,
            "passed": False,
            "reason": "smoke_test_failure",
            "output": "",
            "returncode": 1,
        })

    return all_passed, step_results
