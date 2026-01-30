"""Review check functions for AI review task."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import Any

from app.logging_config import get_logger
from app.services.agent_hub_client import get_agent
from app.services.autonomous.reviewer import opus_review

from .ai_review_constants import (
    API_CONTRACT_PATTERNS,
    CONFIDENCE_THRESHOLD,
    HIGH_RISK_FILE_PATTERNS,
    MEDIUM_RISK_FILE_PATTERNS,
)
from .ai_review_models import RiskLevel

logger = get_logger(__name__)


def _run_command(
    cmd: list[str],
    cwd: Path,
    timeout: int = 300,
) -> tuple[bool, str]:
    """Run a command and return (success, output).

    Args:
        cmd: Command to run
        cwd: Working directory
        timeout: Timeout in seconds

    Returns:
        Tuple of (success, output)
    """
    try:
        result = subprocess.run(
            cmd,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        output = result.stdout + result.stderr
        return result.returncode == 0, output
    except subprocess.TimeoutExpired:
        return False, f"Command timed out after {timeout}s"
    except Exception as e:
        return False, str(e)


def _run_pytest(project_path: Path) -> dict[str, Any]:
    """Run pytest with coverage threshold.

    Args:
        project_path: Path to project root

    Returns:
        Check result dict
    """
    backend_path = project_path / "backend"
    if not backend_path.exists():
        return {"status": "skip", "reason": "No backend directory"}

    venv_pytest = backend_path / ".venv" / "bin" / "pytest"
    if not venv_pytest.exists():
        return {"status": "skip", "reason": "No pytest in venv"}

    success, output = _run_command(
        [str(venv_pytest), "--tb=short", "-q"],
        cwd=backend_path,
        timeout=300,
    )

    return {
        "status": "pass" if success else "fail",
        "output": output[-2000:] if len(output) > 2000 else output,
    }


def _run_precommit(project_path: Path) -> dict[str, Any]:
    """Run pre-commit hooks.

    Args:
        project_path: Path to project root

    Returns:
        Check result dict
    """
    success, output = _run_command(
        ["pre-commit", "run", "--all-files"],
        cwd=project_path,
        timeout=180,
    )

    return {
        "status": "pass" if success else "fail",
        "output": output[-2000:] if len(output) > 2000 else output,
    }


def _run_mypy(project_path: Path) -> dict[str, Any]:
    """Run mypy type checking.

    Args:
        project_path: Path to project root

    Returns:
        Check result dict
    """
    backend_path = project_path / "backend"
    if not backend_path.exists():
        return {"status": "skip", "reason": "No backend directory"}

    venv_mypy = backend_path / ".venv" / "bin" / "mypy"
    if not venv_mypy.exists():
        return {"status": "skip", "reason": "No mypy in venv"}

    success, output = _run_command(
        [str(venv_mypy), "app/", "--ignore-missing-imports"],
        cwd=backend_path,
        timeout=120,
    )

    return {
        "status": "pass" if success else "fail",
        "output": output[-2000:] if len(output) > 2000 else output,
    }


def _run_code_quality_review(
    task: dict[str, Any],
    project_path: Path,
) -> dict[str, Any]:
    """Run code quality scan using Claude Opus.

    Args:
        task: Task dict
        project_path: Path to project root

    Returns:
        Check result dict with verdict and analysis
    """
    try:
        result = opus_review(task, resolved_path=project_path)
        confidence = result.get("confidence", 0.0)
        verdict = result.get("verdict")
        issues = result.get("issues", [])
        suggestions = result.get("suggestions", [])

        # Apply confidence filtering: low-confidence reviews don't fail
        if confidence < CONFIDENCE_THRESHOLD:
            logger.info(
                "code_quality_low_confidence",
                confidence=confidence,
                threshold=CONFIDENCE_THRESHOLD,
                issues_count=len(issues),
            )
            # Still return issues for logging, but mark as low_confidence
            return {
                "status": "pass",
                "verdict": verdict,
                "summary": result.get("summary"),
                "issues": issues,
                "suggestions": suggestions,
                "confidence": confidence,
                "low_confidence": True,
                "filtered_reason": f"Review confidence {confidence:.0%} below {CONFIDENCE_THRESHOLD:.0%} threshold",
            }

        return {
            "status": "pass" if verdict == "APPROVE" else "fail",
            "verdict": verdict,
            "summary": result.get("summary"),
            "issues": issues,
            "suggestions": suggestions,
            "confidence": confidence,
        }
    except Exception as e:
        logger.error("code_quality_review_failed", error=str(e))
        return {
            "status": "error",
            "error": str(e),
        }


def _has_frontend_changes(task: dict[str, Any]) -> bool:
    """Check if task has frontend changes.

    Args:
        task: Task dict

    Returns:
        True if frontend files were modified
    """
    plan_content = task.get("plan_content") or {}
    affected_files = plan_content.get("context", {}).get("affected_files", [])

    frontend_patterns = ["frontend/", ".tsx", ".jsx", ".css", ".scss"]
    return any(any(pattern in f for pattern in frontend_patterns) for f in affected_files)


def _run_ui_review(
    task: dict[str, Any],
    project_path: Path,
) -> dict[str, Any]:
    """Run UI review using Gemini 3 Pro.

    Args:
        task: Task dict
        project_path: Path to project root (reserved for file-level analysis)

    Returns:
        Check result dict
    """
    if not _has_frontend_changes(task):
        return {"status": "skip", "reason": "No frontend changes"}

    try:
        reviewer = get_agent("reviewer")

        prompt = f"""Review this UI/frontend task for design quality:

Task: {task.get("title", "No title")}
Description: {task.get("description", "No description")}

Consider:
1. Component structure and reusability
2. Accessibility (a11y) concerns
3. Responsive design patterns
4. State management patterns
5. Error handling and loading states

Respond with JSON:
{{
    "verdict": "APPROVE" | "REQUEST_FIX" | "REJECT",
    "summary": "One sentence summary",
    "issues": ["Issue 1", ...],
    "suggestions": ["Suggestion 1", ...],
    "confidence": 0.95
}}"""

        response = reviewer.generate(
            prompt=prompt,
            system="You are a UI/UX code reviewer. Output only valid JSON.",
            temperature=0.3,
        )

        import json

        json_match = re.search(r"\{.*\}", response.content, re.DOTALL)
        if json_match:
            parsed = json.loads(json_match.group(0))
            confidence = parsed.get("confidence", 0.5)
            verdict = parsed.get("verdict")
            issues = parsed.get("issues", [])
            suggestions = parsed.get("suggestions", [])

            # Apply confidence filtering
            if confidence < CONFIDENCE_THRESHOLD:
                logger.info(
                    "ui_review_low_confidence",
                    confidence=confidence,
                    threshold=CONFIDENCE_THRESHOLD,
                    issues_count=len(issues),
                )
                return {
                    "status": "pass",
                    "verdict": verdict,
                    "summary": parsed.get("summary"),
                    "issues": issues,
                    "suggestions": suggestions,
                    "confidence": confidence,
                    "low_confidence": True,
                    "filtered_reason": f"Review confidence {confidence:.0%} below {CONFIDENCE_THRESHOLD:.0%} threshold",
                }

            return {
                "status": "pass" if verdict == "APPROVE" else "fail",
                "verdict": verdict,
                "summary": parsed.get("summary"),
                "issues": issues,
                "suggestions": suggestions,
                "confidence": confidence,
            }
        else:
            return {"status": "error", "error": "Could not parse response"}

    except Exception as e:
        logger.error("ui_review_failed", error=str(e))
        return {"status": "error", "error": str(e)}


def _get_affected_files(task: dict[str, Any]) -> list[str]:
    """Extract affected files from task plan_content.

    Args:
        task: Task dict

    Returns:
        List of affected file paths
    """
    plan_content = task.get("plan_content") or {}
    files = plan_content.get("context", {}).get("affected_files", [])
    return list(files) if files else []


def _classify_risk_level(
    task: dict[str, Any],
    project_path: Path | None = None,
) -> tuple[RiskLevel, list[str]]:
    """Classify risk level of changes based on file patterns.

    This is the security gate that runs early in the review pipeline.
    High-risk changes involving auth, database, credentials, or API schemas
    are flagged for human review.

    Args:
        task: Task dict
        project_path: Optional path to project root (for future file content analysis)

    Returns:
        Tuple of (risk_level, list of reasons for the classification)
    """
    affected_files = _get_affected_files(task)
    if not affected_files:
        return RiskLevel.LOW, ["No affected files detected"]

    high_risk_matches: list[str] = []
    medium_risk_matches: list[str] = []

    for file_path in affected_files:
        file_lower = file_path.lower()

        # Check high-risk patterns
        for pattern in HIGH_RISK_FILE_PATTERNS:
            if re.search(pattern, file_lower):
                high_risk_matches.append(f"{file_path} matches pattern '{pattern}'")
                break  # One match per file is enough

        # Check medium-risk patterns (only if not already high-risk)
        if not any(file_path in m for m in high_risk_matches):
            for pattern in MEDIUM_RISK_FILE_PATTERNS:
                if re.search(pattern, file_lower):
                    medium_risk_matches.append(f"{file_path} matches pattern '{pattern}'")
                    break

    # Determine overall risk level
    if high_risk_matches:
        return RiskLevel.HIGH, high_risk_matches
    elif medium_risk_matches:
        return RiskLevel.MEDIUM, medium_risk_matches
    else:
        return RiskLevel.LOW, ["No sensitive file patterns detected"]


def _run_security_risk_classification(
    task: dict[str, Any],
    project_path: Path,
) -> dict[str, Any]:
    """Run security risk classification check.

    This check runs early in the review pipeline and can short-circuit
    to human_review for high-risk changes.

    Args:
        task: Task dict
        project_path: Path to project root

    Returns:
        Check result dict with risk_level and matches
    """
    risk_level, reasons = _classify_risk_level(task, project_path)

    result = {
        "status": "pass" if risk_level != RiskLevel.HIGH else "escalate",
        "risk_level": risk_level.value,
        "reasons": reasons,
    }

    if risk_level == RiskLevel.HIGH:
        result["escalation_reason"] = (
            f"High-risk changes detected: {len(reasons)} sensitive file(s)"
        )
        logger.info(
            "security_gate_high_risk",
            task_id=task.get("id"),
            risk_level=risk_level.value,
            matches=len(reasons),
        )

    return result


def _detect_api_contract_changes(
    diff: str,
) -> tuple[bool, list[str]]:
    """Detect potential API contract changes in a diff.

    Looks for patterns that may indicate breaking changes:
    - Removed function/class definitions
    - Removed exports
    - Changed Props interfaces
    - Removed API schemas

    Args:
        diff: Git diff output

    Returns:
        Tuple of (has_breaking_changes, list of detected patterns)
    """
    if not diff:
        return False, []

    detected: list[str] = []

    for line in diff.split("\n"):
        for pattern in API_CONTRACT_PATTERNS:
            if re.search(pattern, line):
                detected.append(line.strip()[:80])
                break

    return len(detected) > 0, detected


def _run_breaking_change_detection(
    task: dict[str, Any],
    project_path: Path,
    pytest_result: dict[str, Any],
) -> dict[str, Any]:
    """Run breaking change detection.

    Combines test failure analysis with semantic diff analysis.

    Args:
        task: Task dict
        project_path: Path to project root
        pytest_result: Result from pytest check

    Returns:
        Check result dict with breaking_change flag and details
    """
    from app.services.git_service import capture_diff

    result: dict[str, Any] = {
        "status": "pass",
        "has_breaking_change": False,
        "reasons": [],
    }

    # Step 1: Check test results - test failures indicate potential breaking changes
    if pytest_result.get("status") == "fail":
        result["has_breaking_change"] = True
        result["reasons"].append("Test suite failed - changes may break existing functionality")
        result["test_output"] = pytest_result.get("output", "")[:500]

    # Step 2: Analyze diff for API contract changes
    try:
        # Get the diff from main branch or pre_merge_sha
        pre_merge_sha = task.get("pre_merge_sha")
        if pre_merge_sha:
            diff = capture_diff(project_path, base_sha=pre_merge_sha)
        else:
            diff = capture_diff(project_path, base_sha="HEAD~1")

        has_contract_changes, patterns = _detect_api_contract_changes(diff)

        if has_contract_changes:
            result["has_breaking_change"] = True
            result["reasons"].append(f"Detected {len(patterns)} potential API contract change(s)")
            result["api_changes"] = patterns[:10]  # Limit to 10

    except Exception as e:
        logger.warning("breaking_change_diff_failed", error=str(e))
        result["diff_error"] = str(e)

    # Set final status
    if result["has_breaking_change"]:
        result["status"] = "escalate"
        logger.info(
            "breaking_change_detected",
            task_id=task.get("id"),
            reasons=result["reasons"],
        )

    return result


def _verify_step_completion(task: dict[str, Any]) -> dict[str, Any]:
    """Verify task completion by checking step status.

    Verification happens at the step level via verify_command.
    This function checks if all steps across all subtasks are passed.

    Args:
        task: Task dict

    Returns:
        Check result dict
    """
    task_id = task.get("id")
    if not task_id:
        return {"status": "error", "error": "No task id"}

    from app.storage.subtasks import get_subtasks_for_task

    subtasks = get_subtasks_for_task(task_id, include_steps=True)
    if not subtasks:
        return {"status": "skip", "reason": "No subtasks defined"}

    total_steps = 0
    passed_steps = 0
    incomplete_subtasks = []

    for subtask in subtasks:
        steps = subtask.get("steps_from_table", [])
        for step in steps:
            total_steps += 1
            if step.get("passes"):
                passed_steps += 1
        if not subtask.get("passes"):
            incomplete_subtasks.append(subtask.get("subtask_id"))

    if total_steps == 0:
        return {"status": "skip", "reason": "No steps defined"}

    all_passed = passed_steps == total_steps
    return {
        "status": "pass" if all_passed else "fail",
        "verified": passed_steps,
        "total": total_steps,
        "missing": incomplete_subtasks if not all_passed else [],
    }
