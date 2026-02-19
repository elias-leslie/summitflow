"""Review check functions for AI review task."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from app.logging_config import get_logger

from .ai_review_constants import API_CONTRACT_PATTERNS

# Re-export functions from other modules for backward compatibility
from .ai_review_quality import has_frontend_changes as _has_frontend_changes
from .ai_review_quality import run_code_quality_review as _run_code_quality_review
from .ai_review_quality import run_ui_review as _run_ui_review
from .ai_review_risk import classify_risk_level as _classify_risk_level
from .ai_review_risk import get_affected_files as _get_affected_files
from .ai_review_risk import run_security_risk_classification as _run_security_risk_classification
from .ai_review_tools import run_command as _run_command
from .ai_review_tools import run_precommit as _run_precommit
from .ai_review_tools import run_pytest as _run_pytest
from .ai_review_tools import run_types as _run_types

__all__ = [
    "_classify_risk_level", "_detect_api_contract_changes", "_get_affected_files",
    "_has_frontend_changes", "_run_breaking_change_detection", "_run_code_quality_review",
    "_run_command", "_run_precommit", "_run_pytest", "_run_security_risk_classification",
    "_run_types", "_run_ui_review", "_verify_step_completion",
]

logger = get_logger(__name__)


def detect_api_contract_changes(diff: str) -> tuple[bool, list[str]]:
    """Detect potential API contract changes (removed defs, exports, schemas) in a diff."""
    if not diff:
        return False, []

    detected: list[str] = []
    for line in diff.split("\n"):
        for pattern in API_CONTRACT_PATTERNS:
            if re.search(pattern, line):
                detected.append(line.strip()[:80])
                break

    return len(detected) > 0, detected


def _check_test_failures(result: dict[str, Any], pytest_result: dict[str, Any]) -> None:
    """Update result with test failure information if tests failed."""
    if pytest_result.get("status") == "fail":
        result["has_breaking_change"] = True
        result["reasons"].append("Test suite failed - changes may break existing functionality")
        result["test_output"] = pytest_result.get("output", "")[:500]


def _check_diff_contract_changes(
    result: dict[str, Any],
    task: dict[str, Any],
    project_path: Path,
) -> None:
    """Update result with API contract changes detected in the diff."""
    from app.services.git_service import capture_diff

    try:
        pre_merge_sha = task.get("pre_merge_sha")
        diff = capture_diff(project_path, base_sha=pre_merge_sha or "HEAD~1")
        has_contract_changes, patterns = detect_api_contract_changes(diff)
        if has_contract_changes:
            result["has_breaking_change"] = True
            result["reasons"].append(f"Detected {len(patterns)} potential API contract change(s)")
            result["api_changes"] = patterns[:10]
    except Exception as e:
        logger.warning("breaking_change_diff_failed", error=str(e))
        result["diff_error"] = str(e)


def run_breaking_change_detection(
    task: dict[str, Any],
    project_path: Path,
    pytest_result: dict[str, Any],
) -> dict[str, Any]:
    """Run breaking change detection combining test failures and diff analysis."""
    result: dict[str, Any] = {
        "status": "pass",
        "has_breaking_change": False,
        "reasons": [],
    }

    _check_test_failures(result, pytest_result)
    _check_diff_contract_changes(result, task, project_path)

    if result["has_breaking_change"]:
        result["status"] = "escalate"
        logger.info(
            "breaking_change_detected",
            task_id=task.get("id"),
            reasons=result["reasons"],
        )

    return result


def _count_steps(subtasks: list[dict[str, Any]]) -> tuple[int, int, list[Any]]:
    """Count total/passed steps and collect incomplete subtask IDs."""
    total_steps = 0
    passed_steps = 0
    incomplete_subtasks: list[Any] = []
    for subtask in subtasks:
        steps = subtask.get("steps_from_table", [])
        for step in steps:
            total_steps += 1
            if step.get("passes"):
                passed_steps += 1
        if not subtask.get("passes"):
            incomplete_subtasks.append(subtask.get("subtask_id"))

    return total_steps, passed_steps, incomplete_subtasks


def verify_step_completion(task: dict[str, Any]) -> dict[str, Any]:
    """Verify task completion by checking that all steps across all subtasks have passed."""
    task_id = task.get("id")
    if not task_id:
        return {"status": "error", "error": "No task id"}

    from app.storage.subtasks import get_subtasks_for_task

    subtasks = get_subtasks_for_task(task_id, include_steps=True)
    if not subtasks:
        return {"status": "skip", "reason": "No subtasks defined"}
    total_steps, passed_steps, incomplete_subtasks = _count_steps(subtasks)
    if total_steps == 0:
        return {"status": "skip", "reason": "No steps defined"}

    all_passed = passed_steps == total_steps
    return {
        "status": "pass" if all_passed else "fail",
        "verified": passed_steps,
        "total": total_steps,
        "missing": incomplete_subtasks if not all_passed else [],
    }


# Aliases for backward compatibility
_detect_api_contract_changes = detect_api_contract_changes
_run_breaking_change_detection = run_breaking_change_detection
_verify_step_completion = verify_step_completion
