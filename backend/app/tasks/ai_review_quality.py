"""Code quality and UI review functions for AI review."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from app.logging_config import get_logger
from app.services.agent_hub_client import get_agent
from app.services.autonomous.reviewer import opus_review

from .ai_review_constants import CONFIDENCE_THRESHOLD

logger = get_logger(__name__)


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


def has_frontend_changes(task: dict[str, Any]) -> bool:
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
