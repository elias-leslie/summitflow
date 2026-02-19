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


def _make_error_result(summary: str, issue: str) -> ReviewResult:
    """Build a REQUEST_FIX ReviewResult for error conditions."""
    return ReviewResult(
        verdict="REQUEST_FIX",
        summary=summary,
        issues=[issue],
        suggestions=[],
        confidence=0.0,
        reviewed_at=datetime.now(UTC).isoformat(),
    )


def _get_diff_data(
    resolved_path: Path | str,
    pre_merge_sha: str,
) -> tuple[str, DiffStats] | ReviewResult:
    """Capture diff and stats; return (diff, stats) or an error ReviewResult."""
    try:
        diff = capture_diff(resolved_path, pre_merge_sha)
        diff_stats = cast(DiffStats, get_diff_stats(resolved_path, pre_merge_sha))
        return diff, diff_stats
    except RuntimeError as e:
        logger.error("review_diff_failed", error=str(e))
        return _make_error_result(f"Failed to get diff: {e}", str(e))


def _call_review_agent(prompt: str) -> str | ReviewResult:
    """Run the reviewer agent; return response text or an error ReviewResult."""
    try:
        agent = get_agent("reviewer")
        response = agent.generate(
            prompt=prompt,
            system="You are a senior code reviewer. Be thorough but fair. Output only valid JSON.",
            temperature=0.3,
        )
        return response.content
    except Exception as e:
        logger.error("review_agent_failed", error=str(e))
        return _make_error_result(f"Review agent error: {e}", str(e))


def _approve_no_changes(diff_stats: DiffStats, task_id: str | None) -> ReviewResult:
    """Build an APPROVE ReviewResult when no diff is present."""
    logger.info("review_no_changes", task_id=task_id)
    return ReviewResult(
        verdict="APPROVE",
        summary="No changes detected",
        issues=[],
        suggestions=[],
        confidence=1.0,
        diff_stats=diff_stats,
        reviewed_at=datetime.now(UTC).isoformat(),
    )


def _validate_sha(task: Task) -> str | ReviewResult:
    """Return pre_merge_sha from task or an error ReviewResult if missing."""
    pre_merge_sha = task.get("pre_merge_sha")
    if not pre_merge_sha:
        logger.error("review_no_sha", task_id=task.get("id"))
        result = _make_error_result(
            "No pre_merge_sha found - cannot determine what changed",
            "Missing pre_merge_sha in task",
        )
        result["suggestions"] = ["Ensure pre_merge_sha is set before execution"]
        return result
    return pre_merge_sha


def opus_review(
    task: Task,
    resolved_path: Path | str | None = None,
) -> ReviewResult:
    """Review task changes using Claude Opus.

    Args:
        task: Task dict (must have pre_merge_sha)
        resolved_path: Path to git repo (defaults to project_id lookup)

    Returns:
        ReviewResult with verdict, summary, issues, suggestions, confidence,
        diff_stats, reviewed_at.
    """
    resolved_path = get_project_path(task, resolved_path)

    sha_or_error = _validate_sha(task)
    if isinstance(sha_or_error, dict):
        return sha_or_error
    pre_merge_sha = cast(str, sha_or_error)

    diff_data = _get_diff_data(resolved_path, pre_merge_sha)
    if isinstance(diff_data, dict):
        return diff_data
    diff, diff_stats = cast(tuple[str, DiffStats], diff_data)

    if not diff.strip():
        return _approve_no_changes(diff_stats, task.get("id"))

    prompt = build_review_prompt(diff, diff_stats, task, [])
    response_text = _call_review_agent(prompt)
    if isinstance(response_text, dict):
        return response_text

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
