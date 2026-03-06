"""Code quality and UI review functions for AI review."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

from app.logging_config import get_logger
from app.services.agent_hub_client import get_agent
from app.services.autonomous.review_types import Task
from app.services.autonomous.reviewer import opus_review

from .ai_review_constants import CONFIDENCE_THRESHOLD

logger = get_logger(__name__)


def _build_review_result(
    parsed: dict[str, Any],
    low_conf_log_event: str,
) -> dict[str, Any]:
    """Build a standardised review result dict, applying confidence filtering."""
    confidence = parsed.get("confidence", 0.0)
    verdict = parsed.get("verdict")
    issues = parsed.get("issues", [])
    suggestions = parsed.get("suggestions", [])
    summary = parsed.get("summary")

    if confidence < CONFIDENCE_THRESHOLD:
        logger.info(
            low_conf_log_event,
            confidence=confidence,
            threshold=CONFIDENCE_THRESHOLD,
            issues_count=len(issues),
        )
        return {
            "status": "pass",
            "verdict": verdict,
            "summary": summary,
            "issues": issues,
            "suggestions": suggestions,
            "confidence": confidence,
            "low_confidence": True,
            "filtered_reason": (
                f"Review confidence {confidence:.0%} below {CONFIDENCE_THRESHOLD:.0%} threshold"
            ),
        }

    return {
        "status": "pass" if verdict == "APPROVE" else "fail",
        "verdict": verdict,
        "summary": summary,
        "issues": issues,
        "suggestions": suggestions,
        "confidence": confidence,
    }


def run_code_quality_review(
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
        result = opus_review(cast(Task, task), resolved_path=project_path)
        # opus_review returns error results (verdict=REQUEST_FIX, confidence=0)
        # for pre-review failures (missing SHA, diff errors, etc.).
        # Propagate these as errors instead of feeding them into
        # _build_review_result where low confidence would mask the failure.
        if result.get("confidence", 0.0) == 0.0 and result.get("verdict") == "REQUEST_FIX":
            error_msg = result.get("summary", "Review pre-check failed")
            logger.error("code_quality_review_pre_check_failed", error=error_msg)
            return {"status": "error", "error": error_msg}
        return _build_review_result(result, "code_quality_low_confidence")
    except Exception as e:
        logger.error("code_quality_review_failed", error=str(e))
        return {"status": "error", "error": str(e)}


def has_frontend_changes(task: dict[str, Any]) -> bool:
    """Check if task has frontend changes.

    Args:
        task: Task dict (needs 'id' field)

    Returns:
        True if frontend files were modified
    """
    from .ai_review_risk import get_affected_files

    affected_files = get_affected_files(task)
    frontend_patterns = ["frontend/", ".tsx", ".jsx", ".css", ".scss"]
    return any(any(pattern in f for pattern in frontend_patterns) for f in affected_files)


def run_ui_review(
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
    if not has_frontend_changes(task):
        return {"status": "skip", "reason": "No frontend changes"}

    try:
        reviewer = get_agent("reviewer")

        prompt = f"""Task: {task.get("title", "No title")}
Description: {task.get("description", "No description")}"""

        response = reviewer.generate(
            prompt=prompt,
            system="You are a UI/UX code reviewer. Output only valid JSON.",
            temperature=0.3,
        )

        # Use raw_decode for balanced JSON extraction (handles nested braces)
        decoder = json.JSONDecoder()
        brace_idx = response.content.find("{")
        if brace_idx == -1:
            return {"status": "error", "error": "Could not parse response"}

        parsed, _ = decoder.raw_decode(response.content, brace_idx)
        return _build_review_result(parsed, "ui_review_low_confidence")

    except Exception as e:
        logger.error("ui_review_failed", error=str(e))
        return {"status": "error", "error": str(e)}
