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
