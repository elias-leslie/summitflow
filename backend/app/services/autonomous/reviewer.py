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
from typing import Any, Literal

from ...constants import CLAUDE_OPUS
from ...logging_config import get_logger
from ...services.agent_hub_client import get_agent
from ...services.git_service import capture_diff, get_diff_stats, revert_to
from ...storage import log_task_event
from ...storage import tasks as task_store

logger = get_logger(__name__)

Verdict = Literal["APPROVE", "REJECT", "REQUEST_FIX"]


def _get_project_path(task: dict[str, Any], resolved_path: Path | str | None) -> Path:
    """Get project path from explicit param or task's project_id."""
    if resolved_path:
        return Path(resolved_path)

    project_id = task.get("project_id")
    if not project_id:
        raise ValueError("Task missing project_id and no resolved_path provided")

    from app.storage.projects import get_project_root_path

    root = get_project_root_path(project_id)
    if not root:
        raise ValueError(f"Project {project_id} not found or has no root_path")
    return Path(root)


def _build_review_prompt(
    diff: str,
    diff_stats: dict[str, Any],
    task: dict[str, Any],
    rules: list[str],
) -> str:
    """Build the review prompt for Opus.

    Args:
        diff: Git diff output
        diff_stats: Dict with files_changed, insertions, deletions
        task: Task dict
        rules: List of relevant rule filenames

    Returns:
        Complete prompt string
    """
    lines: list[str] = []

    lines.append("# Code Review Request")
    lines.append("")
    lines.append("You are reviewing changes made by an autonomous agent.")
    lines.append("Your job is to ensure code quality, correctness, and adherence to project rules.")
    lines.append("")

    # Task context
    lines.append("## Task")
    lines.append(f"**Title:** {task.get('title', 'No title')}")
    if task.get("description"):
        lines.append(f"**Description:** {task['description']}")
    lines.append("")

    # Diff stats
    lines.append("## Change Summary")
    lines.append(f"- Files changed: {diff_stats.get('files_changed', 0)}")
    lines.append(f"- Lines added: {diff_stats.get('insertions', 0)}")
    lines.append(f"- Lines removed: {diff_stats.get('deletions', 0)}")
    lines.append("")

    # Rules to check
    if rules:
        lines.append("## Rules to Verify")
        lines.append("Check that changes comply with:")
        for rule in rules:
            lines.append(f"- {rule}")
        lines.append("")

    # Review checklist
    lines.append("## Review Checklist")
    lines.append("")
    lines.append("1. **Correctness**: Does the code do what the task requires?")
    lines.append("2. **Code Quality**: Is the code clean, readable, and maintainable?")
    lines.append("3. **Architecture**: Does it follow existing patterns? Any DRY violations?")
    lines.append("4. **Security**: Any security issues (injection, auth bypass, data exposure)?")
    lines.append("5. **Tests**: If tests were affected, do they make sense?")
    lines.append("6. **Dead Code**: Any commented-out or unused code added?")
    lines.append("")

    # The diff
    lines.append("## Diff to Review")
    lines.append("")
    lines.append("```diff")
    # Truncate very long diffs
    if len(diff) > 15000:
        lines.append(diff[:15000])
        lines.append("\n... (truncated, diff too long)")
    else:
        lines.append(diff)
    lines.append("```")
    lines.append("")

    # Output format
    lines.append("## Your Response")
    lines.append("")
    lines.append("Respond with a JSON object in this exact format:")
    lines.append("")
    lines.append("```json")
    lines.append("{")
    lines.append('  "verdict": "APPROVE" | "REJECT" | "REQUEST_FIX",')
    lines.append('  "summary": "One sentence summary of your decision",')
    lines.append('  "issues": ["Issue 1", "Issue 2"],  // Empty array if APPROVE')
    lines.append('  "suggestions": ["Suggestion 1"],   // Optional improvements')
    lines.append('  "confidence": 0.95                 // 0.0-1.0')
    lines.append("}")
    lines.append("```")
    lines.append("")
    lines.append("**Verdict Guidelines:**")
    lines.append("- APPROVE: Code is correct, follows rules, no critical issues")
    lines.append("- REQUEST_FIX: Minor issues that the agent can fix in another iteration")
    lines.append(
        "- REJECT: Critical issues (security, data loss risk, fundamentally wrong approach)"
    )
    lines.append("")

    return "\n".join(lines)


def _parse_review_response(response_text: str) -> dict[str, Any]:
    """Parse the review response from Opus.

    Args:
        response_text: Raw response text

    Returns:
        Parsed review dict with verdict, summary, issues, suggestions, confidence
    """
    import json
    import re

    # Try to extract JSON from response
    # Look for ```json ... ``` block first
    json_match = re.search(r"```json\s*(.*?)\s*```", response_text, re.DOTALL)
    if json_match:
        json_str = json_match.group(1)
    else:
        # Try to find raw JSON object
        json_match = re.search(r"\{[^{}]*\"verdict\"[^{}]*\}", response_text, re.DOTALL)
        if json_match:
            json_str = json_match.group(0)
        else:
            # Fallback: couldn't parse, assume approve but flag uncertainty
            logger.warning("review_parse_failed", response_preview=response_text[:200])
            return {
                "verdict": "REQUEST_FIX",
                "summary": "Could not parse review response - requesting manual review",
                "issues": ["Review response was not in expected format"],
                "suggestions": [],
                "confidence": 0.0,
                "raw_response": response_text,
            }

    try:
        parsed: dict[str, Any] = json.loads(json_str)
        # Validate verdict
        if parsed.get("verdict") not in ("APPROVE", "REJECT", "REQUEST_FIX"):
            parsed["verdict"] = "REQUEST_FIX"
            parsed.setdefault("issues", []).append("Invalid verdict in response")

        # Ensure required fields
        parsed.setdefault("summary", "No summary provided")
        parsed.setdefault("issues", [])
        parsed.setdefault("suggestions", [])
        parsed.setdefault("confidence", 0.5)

        return parsed
    except json.JSONDecodeError as e:
        logger.warning("review_json_decode_failed", error=str(e))
        return {
            "verdict": "REQUEST_FIX",
            "summary": f"JSON parse error: {e}",
            "issues": ["Could not parse review JSON"],
            "suggestions": [],
            "confidence": 0.0,
            "raw_response": response_text,
        }


def opus_review(
    task: dict[str, Any],
    resolved_path: Path | str | None = None,
) -> dict[str, Any]:
    """Review task changes using Claude Opus.

    Gets the diff between pre_merge_sha and HEAD, analyzes with Opus,
    and returns a structured review result.

    Args:
        task: Task dict (must have pre_merge_sha)
        resolved_path: Path to git repo (defaults to ~/summitflow)

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
    resolved_path = _get_project_path(task, resolved_path)

    pre_merge_sha = task.get("pre_merge_sha")
    if not pre_merge_sha:
        logger.error("review_no_sha", task_id=task.get("id"))
        return {
            "verdict": "REQUEST_FIX",
            "summary": "No pre_merge_sha found - cannot determine what changed",
            "issues": ["Missing pre_merge_sha in task"],
            "suggestions": ["Ensure pre_merge_sha is set before execution"],
            "confidence": 0.0,
            "reviewed_at": datetime.now(UTC).isoformat(),
        }

    # Get diff and stats
    try:
        diff = capture_diff(resolved_path, pre_merge_sha)
        diff_stats = get_diff_stats(resolved_path, pre_merge_sha)
    except RuntimeError as e:
        logger.error("review_diff_failed", error=str(e))
        return {
            "verdict": "REQUEST_FIX",
            "summary": f"Failed to get diff: {e}",
            "issues": [str(e)],
            "suggestions": [],
            "confidence": 0.0,
            "reviewed_at": datetime.now(UTC).isoformat(),
        }

    # No changes to review
    if not diff.strip():
        logger.info("review_no_changes", task_id=task.get("id"))
        return {
            "verdict": "APPROVE",
            "summary": "No changes detected",
            "issues": [],
            "suggestions": [],
            "confidence": 1.0,
            "diff_stats": diff_stats,
            "reviewed_at": datetime.now(UTC).isoformat(),
        }

    # Rules consolidated into CLAUDE.md - no longer filter by files
    rules: list[str] = []

    # Build and execute review prompt
    prompt = _build_review_prompt(diff, diff_stats, task, rules)

    try:
        opus = get_agent("claude", model=CLAUDE_OPUS)
        response = opus.generate(
            prompt=prompt,
            system="You are a senior code reviewer. Be thorough but fair. Output only valid JSON.",
            temperature=0.3,  # Lower temperature for more consistent reviews
        )
        response_text = response.content
    except Exception as e:
        logger.error("review_agent_failed", error=str(e))
        return {
            "verdict": "REQUEST_FIX",
            "summary": f"Review agent error: {e}",
            "issues": [str(e)],
            "suggestions": [],
            "confidence": 0.0,
            "reviewed_at": datetime.now(UTC).isoformat(),
        }

    # Parse response
    result = _parse_review_response(response_text)
    result["diff_stats"] = diff_stats
    result["reviewed_at"] = datetime.now(UTC).isoformat()

    logger.info(
        "review_complete",
        task_id=task.get("id"),
        verdict=result["verdict"],
        confidence=result["confidence"],
    )

    return result


def _extract_files_from_diff(diff: str) -> list[str]:
    """Extract file paths from a git diff.

    Args:
        diff: Git diff output

    Returns:
        List of file paths mentioned in diff
    """
    import re

    files: set[str] = set()

    # Match "--- a/path/to/file" and "+++ b/path/to/file"
    for match in re.finditer(r"^(?:---|\+\+\+) [ab]/(.+)$", diff, re.MULTILINE):
        path = match.group(1)
        if path != "/dev/null":
            files.add(path)

    return list(files)


def handle_approval(
    task: dict[str, Any],
    review_result: dict[str, Any],
    auto_push: bool = False,
    resolved_path: Path | str | None = None,
) -> dict[str, Any]:
    """Handle an approved task.

    Marks the task as completed and optionally pushes to remote.

    Args:
        task: Task dict
        review_result: Review result from opus_review
        auto_push: Whether to push changes to remote (default False)
        resolved_path: Path to git repo

    Returns:
        Updated task dict
    """
    resolved_path = _get_project_path(task, resolved_path)

    task_id = task.get("id")
    if not task_id:
        raise ValueError("Task must have an id")

    # Merge review result with existing execution metrics (iterations, consulted, etc.)
    existing_result = task.get("review_result") or {}
    merged_result = {**existing_result, **review_result}
    task_store.update_task(task_id, review_result=merged_result)

    # Mark complete
    updated = task_store.update_task_status(task_id, "completed")

    logger.info("task_approved", task_id=task_id)

    if auto_push:
        from ...services.git_service import get_current_branch, push_branch

        try:
            branch = get_current_branch(resolved_path)
            push_branch(branch, resolved_path)
            logger.info("task_pushed", task_id=task_id, branch=branch)
        except RuntimeError as e:
            logger.warning("task_push_failed", task_id=task_id, error=str(e))

    return updated or task


def handle_rejection(
    task: dict[str, Any],
    review_result: dict[str, Any],
    resolved_path: Path | str | None = None,
) -> dict[str, Any]:
    """Handle a rejected task.

    Reverts changes to pre_merge_sha and marks task for human review.

    Args:
        task: Task dict
        review_result: Review result from opus_review
        resolved_path: Path to git repo

    Returns:
        Updated task dict
    """
    resolved_path = _get_project_path(task, resolved_path)

    task_id = task.get("id")
    if not task_id:
        raise ValueError("Task must have an id")

    # Revert changes
    pre_merge_sha = task.get("pre_merge_sha")
    if pre_merge_sha:
        try:
            revert_to(resolved_path, pre_merge_sha)
            logger.info("task_reverted", task_id=task_id, sha=pre_merge_sha[:8])
        except RuntimeError as e:
            logger.error("task_revert_failed", task_id=task_id, error=str(e))

    # Merge review result with existing execution metrics (iterations, consulted, etc.)
    existing_result = task.get("review_result") or {}
    merged_result = {**existing_result, **review_result}
    task_store.update_task(task_id, review_result=merged_result)

    # Add needs-human label
    current_labels = task.get("labels", []) or []
    if "needs-human-review" not in current_labels:
        current_labels.append("needs-human-review")
        task_store.update_task(task_id, labels=current_labels)

    # Mark as failed with review summary
    error_msg = f"Rejected by Opus review: {review_result.get('summary', 'No summary')}"
    updated = task_store.update_task_status(task_id, "failed", error_message=error_msg)

    logger.info("task_rejected", task_id=task_id, summary=review_result.get("summary"))

    return updated or task


def handle_fix_request(
    task: dict[str, Any],
    review_result: dict[str, Any],
) -> dict[str, Any]:
    """Handle a fix request.

    Appends review feedback to task and resets to running for another iteration.

    Args:
        task: Task dict
        review_result: Review result from opus_review

    Returns:
        Updated task dict
    """
    task_id = task.get("id")
    if not task_id:
        raise ValueError("Task must have an id")

    # Merge review result with existing execution metrics (iterations, consulted, etc.)
    existing_result = task.get("review_result") or {}
    merged_result = {**existing_result, **review_result}
    task_store.update_task(task_id, review_result=merged_result)

    # Append feedback to progress log
    issues = review_result.get("issues", [])
    suggestions = review_result.get("suggestions", [])

    feedback_parts = ["Review requested fixes:"]
    if issues:
        feedback_parts.append(f"Issues: {', '.join(issues)}")
    if suggestions:
        feedback_parts.append(f"Suggestions: {', '.join(suggestions)}")

    feedback = " | ".join(feedback_parts)
    log_task_event(task_id, feedback)

    # Reset to pending so it can be picked up again
    # Note: Don't revert - let agent try to fix from current state
    updated = task_store.update_task_status(task_id, "pending", validate_transition=False)

    logger.info("task_fix_requested", task_id=task_id, issues=len(issues))

    return updated or task
