"""Risk classification and security checks for AI review."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from app.logging_config import get_logger

from .ai_review_constants import HIGH_RISK_FILE_PATTERNS, MEDIUM_RISK_FILE_PATTERNS
from .ai_review_models import RiskLevel

logger = get_logger(__name__)


def get_affected_files(task: dict[str, Any]) -> list[str]:
    """Extract affected files from task_spirit context.

    Args:
        task: Task dict (needs 'id' field)

    Returns:
        List of affected file paths
    """
    from ..storage.task_spirit import get_task_spirit

    task_id = task.get("id")
    if not task_id:
        return []
    spirit = get_task_spirit(task_id)
    if not spirit:
        return []
    context = spirit.get("context") or {}
    files_modify = context.get("files_to_modify") or []
    files_create = context.get("files_to_create") or []
    return list(files_modify) + list(files_create)


def _match_first_pattern(file_lower: str, patterns: list[str]) -> str | None:
    """Return the first pattern that matches file_lower, or None."""
    for pattern in patterns:
        if re.search(pattern, file_lower):
            return pattern
    return None


def _classify_file_risk(
    file_path: str,
    high_risk_matches: list[str],
) -> tuple[str | None, str | None]:
    """Classify a single file as high-risk, medium-risk, or neither.

    Returns:
        Tuple of (high_risk_reason, medium_risk_reason) where at most one is set.
    """
    file_lower = file_path.lower()

    high_pattern = _match_first_pattern(file_lower, HIGH_RISK_FILE_PATTERNS)
    if high_pattern is not None:
        return f"{file_path} matches pattern '{high_pattern}'", None

    already_high = any(file_path in m for m in high_risk_matches)
    if already_high:
        return None, None

    medium_pattern = _match_first_pattern(file_lower, MEDIUM_RISK_FILE_PATTERNS)
    if medium_pattern is not None:
        return None, f"{file_path} matches pattern '{medium_pattern}'"

    return None, None


def classify_risk_level(
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
    affected_files = get_affected_files(task)
    if not affected_files:
        return RiskLevel.LOW, ["No affected files detected"]

    high_risk_matches: list[str] = []
    medium_risk_matches: list[str] = []

    for file_path in affected_files:
        high_reason, medium_reason = _classify_file_risk(file_path, high_risk_matches)
        if high_reason is not None:
            high_risk_matches.append(high_reason)
        elif medium_reason is not None:
            medium_risk_matches.append(medium_reason)

    # Determine overall risk level
    if high_risk_matches:
        return RiskLevel.HIGH, high_risk_matches
    if medium_risk_matches:
        return RiskLevel.MEDIUM, medium_risk_matches
    return RiskLevel.LOW, ["No sensitive file patterns detected"]


def run_security_risk_classification(
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
    risk_level, reasons = classify_risk_level(task, project_path)

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
