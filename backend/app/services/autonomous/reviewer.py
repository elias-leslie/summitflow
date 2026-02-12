"""Opus reviewer service for autonomous task validation.

Provides the review gate that validates autonomous task execution
before marking tasks as complete. Uses Claude Opus for high-quality
code review with diff analysis.

Verdicts:
- APPROVE: Changes are good, can be merged
- REJECT: Changes have critical issues, revert needed
- REQUEST_FIX: Minor issues, feed back to agent for another iteration
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import cast

from ...logging_config import get_logger
from ...services.agent_hub_client import get_agent
from ...services.git_service import capture_diff, get_diff_stats
from .review_handlers import handle_approval, handle_fix_request, handle_rejection
from .review_parser import parse_review_response
from .review_prompt import build_review_prompt
from .review_types import DiffStats, ReviewResult, Task, Verdict
from .review_utils import get_project_path

logger = get_logger(__name__)

__all__ = [
    "Verdict",
    "handle_approval",
    "handle_fix_request",
    "handle_rejection",
    "opus_review",
]


def opus_review(
    task: Task,
    resolved_path: Path | str | None = None,
) -> ReviewResult:
    """Review task changes using Claude Opus.

    Gets the diff between pre_merge_sha and HEAD, analyzes with Opus,
    and returns a structured review result.

    Args:
        task: Task dict (must have pre_merge_sha)
        resolved_path: Path to git repo (defaults to project_id lookup)

    Returns:
        Review result dict with:
        - verdict: APPROVE | REJECT | REQUEST_FIX
        - summary: One sentence decision summary
        - issues: List of issues found
        - suggestions: List of improvement suggestions
        - confidence: 0.0-1.0 confidence score
        - diff_stats: Files changed, insertions, deletions
        - reviewed_at: Timestamp
    """
    resolved_path = get_project_path(task, resolved_path)

    pre_merge_sha = task.get("pre_merge_sha")
    if not pre_merge_sha:
        logger.error("review_no_sha", task_id=task.get("id"))
        return ReviewResult(
            verdict="REQUEST_FIX",
            summary="No pre_merge_sha found - cannot determine what changed",
            issues=["Missing pre_merge_sha in task"],
            suggestions=["Ensure pre_merge_sha is set before execution"],
            confidence=0.0,
            reviewed_at=datetime.now(UTC).isoformat(),
        )

    try:
        diff = capture_diff(resolved_path, pre_merge_sha)
        diff_stats = cast(DiffStats, get_diff_stats(resolved_path, pre_merge_sha))
    except RuntimeError as e:
        logger.error("review_diff_failed", error=str(e))
        return ReviewResult(
            verdict="REQUEST_FIX",
            summary=f"Failed to get diff: {e}",
            issues=[str(e)],
            suggestions=[],
            confidence=0.0,
            reviewed_at=datetime.now(UTC).isoformat(),
        )

    if not diff.strip():
        logger.info("review_no_changes", task_id=task.get("id"))
        return ReviewResult(
            verdict="APPROVE",
            summary="No changes detected",
            issues=[],
            suggestions=[],
            confidence=1.0,
            diff_stats=diff_stats,
            reviewed_at=datetime.now(UTC).isoformat(),
        )

    rules: list[str] = []
    prompt = build_review_prompt(diff, diff_stats, task, rules)

    try:
        agent = get_agent("reviewer")
        response = agent.generate(
            prompt=prompt,
            system="You are a senior code reviewer. Be thorough but fair. Output only valid JSON.",
            temperature=0.3,
        )
        response_text = response.content
    except Exception as e:
        logger.error("review_agent_failed", error=str(e))
        return ReviewResult(
            verdict="REQUEST_FIX",
            summary=f"Review agent error: {e}",
            issues=[str(e)],
            suggestions=[],
            confidence=0.0,
            reviewed_at=datetime.now(UTC).isoformat(),
        )

    result = parse_review_response(response_text)
    result["diff_stats"] = diff_stats
    result["reviewed_at"] = datetime.now(UTC).isoformat()

    logger.info(
        "review_complete",
        task_id=task.get("id"),
        verdict=result["verdict"],
        confidence=result["confidence"],
    )

    return result
