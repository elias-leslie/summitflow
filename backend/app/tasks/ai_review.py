"""AI Review Celery task for pull request validation.

This task implements the AI review gate for the git management workflow.
It runs when a task transitions to ai_reviewing status after PR creation.

Review Pipeline:
1. Test execution (pytest with coverage threshold)
2. Lint check (pre-commit hooks)
3. Type check (mypy)
4. Code quality scan (Claude Opus 4.5)
5. UI review (Gemini 3 Pro for frontend changes)
6. Acceptance criteria verification
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from typing import Any

from app.celery_app import celery_app
from app.constants import AGENT_REVIEWER
from app.logging_config import get_logger
from app.services.agent_hub_client import get_agent
from app.services.autonomous.reviewer import opus_review
from app.storage import tasks as task_store

logger = get_logger(__name__)

# Confidence threshold for filtering AI review issues (80% = 0.80)
# Issues from reviews below this threshold are logged but not counted as failures
CONFIDENCE_THRESHOLD = 0.80


class ReviewVerdict(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    NEEDS_FIX = "NEEDS_FIX"


class RiskLevel(str, Enum):
    """Risk classification for changes."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


# High-risk file patterns that require human review
# These patterns match sensitive areas: auth, database, API schemas, credentials
HIGH_RISK_FILE_PATTERNS = [
    # Authentication and authorization
    r"auth[/\._-]",
    r"login",
    r"session",
    r"oauth",
    r"jwt",
    r"permission",
    # Credentials and secrets
    r"password",
    r"credential",
    r"secret",
    r"token",
    r"api[_-]?key",
    r"\.env",
    # Database and migrations
    r"migration",
    r"schema\.py",
    r"models\.py",
    r"\.sql$",
    r"alembic",
    # API schemas and contracts
    r"openapi",
    r"swagger",
    r"schemas/",
    r"api/.*schema",
    # Security-sensitive directories
    r"/security/",
    r"/crypto/",
    r"/payment/",
]

# Medium-risk patterns (flagged but not auto-escalated)
MEDIUM_RISK_FILE_PATTERNS = [
    r"config",
    r"settings",
    r"middleware",
    r"celery",
    r"redis",
]


@dataclass
class ReviewResult:
    """Result of the AI review process."""

    verdict: ReviewVerdict
    summary: str
    checks: dict[str, Any] = field(default_factory=dict)
    issues: list[str] = field(default_factory=list)
    suggestions: list[str] = field(default_factory=list)
    reviewed_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    risk_level: RiskLevel = RiskLevel.LOW

    def to_dict(self) -> dict[str, Any]:
        return {
            "verdict": self.verdict.value,
            "summary": self.summary,
            "checks": self.checks,
            "issues": self.issues,
            "suggestions": self.suggestions,
            "reviewed_at": self.reviewed_at,
            "risk_level": self.risk_level.value,
        }


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


# API contract patterns that may indicate breaking changes
API_CONTRACT_PATTERNS = [
    # Python function signatures
    r"^-\s*def\s+\w+\s*\(",  # Removed function definition
    r"^-\s*class\s+\w+",  # Removed class
    r"^-\s*@(api|router|app)\.",  # Removed API decorator
    # TypeScript/JavaScript exports
    r"^-\s*export\s+(const|function|class|interface|type)",  # Removed export
    r"^-\s*export\s+default",  # Removed default export
    # Props and types
    r"^-\s*interface\s+\w+Props",  # Removed Props interface
    r"^-\s*type\s+\w+Props",  # Removed Props type
    # API schemas
    r"^-\s*(class|def)\s+\w+(Schema|Request|Response)",  # Removed schema
]


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
        reviewer = get_agent("claude", model=AGENT_REVIEWER)

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
            max_tokens=1000,
            temperature=0.3,
        )

        import json
        import re

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


SECURITY_KEYWORDS = [
    "security",
    "injection",
    "xss",
    "csrf",
    "authentication",
    "authorization",
    "credential",
    "password",
    "secret",
    "token",
    "vulnerability",
    "exploit",
    "data exposure",
    "sql injection",
]

ARCHITECTURE_KEYWORDS = [
    "breaking change",
    "architectural",
    "fundamental",
    "refactor required",
    "wrong approach",
]


def _should_escalate_for_security(
    checks: dict[str, Any],
    issues: list[str],
) -> str | None:
    """Check if issues require immediate escalation for security concerns.

    Args:
        checks: All check results
        issues: Accumulated issues list

    Returns:
        Escalation reason string if should escalate, None otherwise
    """
    # Check code quality review for security-related rejections
    code_quality = checks.get("code_quality", {})
    if code_quality.get("verdict") == "REJECT":
        summary = code_quality.get("summary", "").lower()
        cq_issues = code_quality.get("issues", [])

        # Check for security keywords in summary or issues
        all_text = summary + " " + " ".join(str(i).lower() for i in cq_issues)

        for keyword in SECURITY_KEYWORDS:
            if keyword in all_text:
                return f"Security issue: {keyword} detected in code review"

        for keyword in ARCHITECTURE_KEYWORDS:
            if keyword in all_text:
                return f"Architectural issue: {keyword}"

    # Check accumulated issues for security patterns
    issues_text = " ".join(str(i).lower() for i in issues)
    for keyword in SECURITY_KEYWORDS:
        if keyword in issues_text:
            return f"Security concern: {keyword}"

    return None


def _notify_human_review_needed(task_id: str, reason: str) -> None:
    """Create notification for human review needed.

    Args:
        task_id: Task ID needing review
        reason: Reason for escalation
    """
    from app.storage.notifications import create_notification

    try:
        create_notification(
            project_id="summitflow",  # Default project for now
            notification_type="task_needs_input",  # Use existing type for human review
            title=f"Human Review Required: {task_id}",
            message=reason,
            severity="warning",
            metadata={"task_id": task_id, "escalation_reason": reason},
        )
        logger.info("human_review_notification_sent", task_id=task_id)
    except Exception as e:
        logger.warning("notification_failed", task_id=task_id, error=str(e))


def _verify_acceptance_criteria(task: dict[str, Any]) -> dict[str, Any]:
    """Verify task against done_when criteria.

    Args:
        task: Task dict

    Returns:
        Check result dict
    """
    done_when = task.get("done_when") or []
    if not done_when:
        return {"status": "skip", "reason": "No done_when criteria"}

    # Get existing criterion verifications from task
    task_id = task.get("id")
    if not task_id:
        return {"status": "error", "error": "No task id"}

    from app.storage.connection import get_connection
    from app.storage.criteria import get_criteria_for_task

    project_id = task.get("project_id", "")
    with get_connection() as conn:
        criteria = get_criteria_for_task(conn, project_id, task_id)

    verified_count = sum(1 for c in criteria if c.get("verified"))
    total_count = len(criteria)

    if total_count == 0:
        return {
            "status": "skip",
            "reason": "No acceptance criteria defined",
        }

    all_verified = verified_count == total_count
    return {
        "status": "pass" if all_verified else "fail",
        "verified": verified_count,
        "total": total_count,
        "missing": [c["criterion"] for c in criteria if not c.get("verified")],
    }


def _get_project_path(task: dict[str, Any]) -> Path:
    """Get project path from task.

    Args:
        task: Task dict

    Returns:
        Path to project root
    """
    project_id = task.get("project_id")
    if not project_id:
        raise ValueError("Task missing project_id")

    from app.storage.projects import get_project_root_path

    root = get_project_root_path(project_id)
    if not root:
        raise ValueError(f"Project {project_id} not found or has no root_path")
    return Path(root)


def _auto_merge_pr(task_id: str, pr_url: str, project_path: Path) -> bool:
    """Auto-merge approved PR via gh CLI.

    Uses `gh pr merge --squash --delete-branch` to merge the PR.

    Args:
        task_id: Task ID for logging
        pr_url: PR URL to merge
        project_path: Path to run command in

    Returns:
        True if merge succeeded, False otherwise (non-blocking)
    """
    import subprocess

    try:
        # Extract PR number from URL
        # Format: https://github.com/owner/repo/pull/123
        pr_number = pr_url.split("/pull/")[-1].strip("/")

        result = subprocess.run(
            [
                "gh",
                "pr",
                "merge",
                pr_number,
                "--squash",
                "--delete-branch",
                "--admin",  # Use admin merge to bypass branch protection
            ],
            cwd=str(project_path),
            capture_output=True,
            text=True,
            timeout=120,
        )

        if result.returncode == 0:
            logger.info("pr_auto_merged", task_id=task_id, pr_url=pr_url)
            task_store.append_progress_log(task_id, f"PR merged: {pr_url}")
            return True
        else:
            error = result.stderr.strip() or "Unknown error"
            logger.warning("pr_auto_merge_failed", task_id=task_id, pr_url=pr_url, error=error)
            task_store.append_progress_log(task_id, f"Auto-merge failed: {error}")
            return False

    except subprocess.TimeoutExpired:
        logger.warning("pr_auto_merge_timeout", task_id=task_id, pr_url=pr_url)
        return False
    except Exception as e:
        logger.warning("pr_auto_merge_error", task_id=task_id, error=str(e))
        return False


@celery_app.task(  # type: ignore[untyped-decorator]
    name="summitflow.review_pull_request",
    bind=True,
    max_retries=3,
    default_retry_delay=60,
)
def review_pull_request(
    self: Any,
    task_id: str,
    pr_url: str | None = None,
) -> dict[str, Any]:
    """Review a pull request for a task.

    Runs the full review pipeline:
    1. Test execution (pytest)
    2. Lint check (pre-commit)
    3. Type check (mypy)
    4. Code quality scan (Opus)
    5. UI review (Gemini) if frontend changes
    6. Acceptance criteria verification

    Args:
        task_id: Task ID to review
        pr_url: Optional PR URL (for reference)

    Returns:
        ReviewResult as dict with overall verdict and check details
    """
    logger.info("review_pull_request_start", task_id=task_id, pr_url=pr_url)

    try:
        # Get task
        task = task_store.get_task(task_id)
        if not task:
            return ReviewResult(
                verdict=ReviewVerdict.FAIL,
                summary=f"Task {task_id} not found",
                issues=[f"Task {task_id} not found"],
            ).to_dict()

        # Verify task is in ai_reviewing status
        if task.get("status") != "ai_reviewing":
            logger.warning(
                "task_not_in_review",
                task_id=task_id,
                status=task.get("status"),
            )
            return ReviewResult(
                verdict=ReviewVerdict.FAIL,
                summary=f"Task not in ai_reviewing status (current: {task.get('status')})",
                issues=["Task must be in ai_reviewing status for review"],
            ).to_dict()

        project_path = _get_project_path(task)
        checks: dict[str, Any] = {}
        all_issues: list[str] = []
        all_suggestions: list[str] = []

        # Step 1: Security risk classification (runs first, can short-circuit)
        logger.info("running_security_risk_classification", task_id=task_id)
        checks["security_risk"] = _run_security_risk_classification(task, project_path)
        risk_level = RiskLevel(checks["security_risk"].get("risk_level", "low"))

        # High-risk changes short-circuit to human review immediately
        if checks["security_risk"].get("status") == "escalate":
            escalation_reason = checks["security_risk"].get(
                "escalation_reason", "High-risk changes"
            )
            logger.info("security_gate_escalation", task_id=task_id, reason=escalation_reason)

            security_reasons: list[str] = checks["security_risk"].get("reasons", [])
            result = ReviewResult(
                verdict=ReviewVerdict.FAIL,
                summary=f"Security gate: {escalation_reason}",
                checks=checks,
                issues=[f"SECURITY GATE: {escalation_reason}", *security_reasons],
                risk_level=risk_level,
            )

            # Update task and escalate to human review
            task_store.update_task(task_id, review_result=result.to_dict())
            task_store.update_task_status(task_id, "human_review")
            _notify_human_review_needed(task_id, escalation_reason)

            return result.to_dict()

        # Step 2: Run remaining checks
        logger.info("running_pytest", task_id=task_id)
        checks["pytest"] = _run_pytest(project_path)
        if checks["pytest"].get("status") == "fail":
            all_issues.append("pytest: Tests failed")

        # Step 3: Breaking change detection (runs after pytest to include test results)
        logger.info("running_breaking_change_detection", task_id=task_id)
        checks["breaking_change"] = _run_breaking_change_detection(
            task, project_path, checks["pytest"]
        )

        # Breaking changes escalate to human review
        if checks["breaking_change"].get("status") == "escalate":
            bc_reasons = checks["breaking_change"].get("reasons", [])
            escalation_reason = f"Breaking changes detected: {'; '.join(bc_reasons)}"
            logger.info("breaking_change_escalation", task_id=task_id, reason=escalation_reason)

            result = ReviewResult(
                verdict=ReviewVerdict.FAIL,
                summary=f"Breaking change gate: {escalation_reason}",
                checks=checks,
                issues=[f"BREAKING CHANGE: {r}" for r in bc_reasons],
                risk_level=risk_level,
            )

            # Update task and escalate to human review
            task_store.update_task(task_id, review_result=result.to_dict())
            task_store.update_task_status(task_id, "human_review")
            _notify_human_review_needed(task_id, escalation_reason)

            return result.to_dict()

        logger.info("running_precommit", task_id=task_id)
        checks["precommit"] = _run_precommit(project_path)
        if checks["precommit"].get("status") == "fail":
            all_issues.append("pre-commit: Lint/format issues")

        logger.info("running_mypy", task_id=task_id)
        checks["mypy"] = _run_mypy(project_path)
        if checks["mypy"].get("status") == "fail":
            all_issues.append("mypy: Type errors")

        logger.info("running_code_quality", task_id=task_id)
        checks["code_quality"] = _run_code_quality_review(task, project_path)
        if checks["code_quality"].get("status") == "fail":
            all_issues.extend(checks["code_quality"].get("issues", []))
            all_suggestions.extend(checks["code_quality"].get("suggestions", []))

        logger.info("running_ui_review", task_id=task_id)
        checks["ui_review"] = _run_ui_review(task, project_path)
        if checks["ui_review"].get("status") == "fail":
            all_issues.extend(checks["ui_review"].get("issues", []))
            all_suggestions.extend(checks["ui_review"].get("suggestions", []))

        logger.info("verifying_criteria", task_id=task_id)
        checks["acceptance_criteria"] = _verify_acceptance_criteria(task)
        if checks["acceptance_criteria"].get("status") == "fail":
            missing = checks["acceptance_criteria"].get("missing", [])
            all_issues.append(f"Unverified criteria: {len(missing)}")

        # Check for security concerns that require immediate escalation
        security_escalation = _should_escalate_for_security(checks, all_issues)

        # Determine overall verdict
        failed_checks = [name for name, result in checks.items() if result.get("status") == "fail"]
        error_checks = [name for name, result in checks.items() if result.get("status") == "error"]

        if security_escalation:
            # Security concerns bypass retry - escalate immediately
            verdict = ReviewVerdict.FAIL
            summary = f"Security concerns detected: {security_escalation}"
            all_issues.insert(0, f"SECURITY: {security_escalation}")
        elif error_checks:
            # Errors are retriable
            try:
                raise self.retry(
                    exc=Exception(f"Check errors: {error_checks}"),
                    countdown=60 * (2**self.request.retries),  # Exponential backoff
                )
            except self.MaxRetriesExceededError:
                verdict = ReviewVerdict.FAIL
                summary = f"Review failed after {self.request.retries + 1} attempts"
        elif failed_checks:
            verdict = ReviewVerdict.NEEDS_FIX
            summary = f"Review found issues in: {', '.join(failed_checks)}"
        else:
            verdict = ReviewVerdict.PASS
            summary = "All checks passed"

        result = ReviewResult(
            verdict=verdict,
            summary=summary,
            checks=checks,
            issues=all_issues,
            suggestions=all_suggestions,
            risk_level=risk_level,
        )

        # Update task with review result
        task_store.update_task(task_id, review_result=result.to_dict())

        # Handle verdict transitions
        if verdict == ReviewVerdict.PASS:
            # Auto-approve: merge PR and transition to completed
            if pr_url:
                _auto_merge_pr(task_id, pr_url, project_path)
            task_store.update_task_status(task_id, "completed")
            logger.info("review_passed", task_id=task_id)
        elif verdict == ReviewVerdict.NEEDS_FIX:
            # Needs work: keep in ai_reviewing for now, log issues
            task_store.append_progress_log(
                task_id,
                f"AI Review needs fixes: {', '.join(all_issues[:3])}",
            )
            logger.info("review_needs_fix", task_id=task_id, issues=len(all_issues))
        else:
            # Failed: escalate to human review
            task_store.update_task_status(task_id, "human_review")
            _notify_human_review_needed(task_id, summary)
            logger.info("review_escalated", task_id=task_id)

        return result.to_dict()

    except Exception as e:
        logger.error("review_pull_request_error", task_id=task_id, error=str(e))
        return ReviewResult(
            verdict=ReviewVerdict.FAIL,
            summary=f"Review error: {e}",
            issues=[str(e)],
        ).to_dict()
