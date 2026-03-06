"""Pattern memory utilities for fix agent.

Handles retrieval and storage of successful fix patterns for future reuse.
"""

from __future__ import annotations

import asyncio
from typing import Any

from ...logging_config import get_logger
from ...services.self_healing import PatternMemoryService, StoredPattern
from ...workflows._model_constants import DEFAULT_PROJECT_ID

logger = get_logger(__name__)

# Project-scoped pattern memory services (lazy initialized)
_pattern_memory_by_project: dict[str, PatternMemoryService] = {}


def _get_pattern_memory(project_id: str | None = None) -> PatternMemoryService:
    """Get or create the pattern memory service for a project."""
    effective_project_id = project_id or DEFAULT_PROJECT_ID
    if effective_project_id not in _pattern_memory_by_project:
        _pattern_memory_by_project[effective_project_id] = PatternMemoryService(
            project_id=effective_project_id,
        )
    return _pattern_memory_by_project[effective_project_id]


def _run_async(coro: Any) -> Any:
    """Run async code from sync context.

    Handles the case where we're already inside an event loop
    (e.g., FastAPI request handler) by running in a thread pool.
    """
    import concurrent.futures

    try:
        asyncio.get_running_loop()  # Check if loop is running
        # Already in an event loop - run in thread pool
        with concurrent.futures.ThreadPoolExecutor() as pool:
            future = pool.submit(asyncio.run, coro)
            return future.result(timeout=30)
    except RuntimeError:
        # No event loop running - can use asyncio.run directly
        return asyncio.run(coro)


def get_similar_patterns(
    check_type: str,
    error_code: str,
    error_message: str,
    project_id: str | None = None,
) -> list[StoredPattern]:
    """Retrieve similar fix patterns from memory.

    Args:
        check_type: Type of check (ruff, types, etc.)
        error_code: Error code (F401, etc.)
        error_message: Error message

    Returns:
        List of similar patterns, empty if retrieval fails
    """
    try:
        pattern_memory = _get_pattern_memory(project_id)
        patterns: list[StoredPattern] = _run_async(
            pattern_memory.get_similar_patterns(
                check_type=check_type,
                error_code=error_code,
                error_message=error_message,
                min_similarity=0.3,
                limit=3,
            )
        )
        if patterns:
            logger.info(
                "patterns_found",
                count=len(patterns),
                check_type=check_type,
                error_code=error_code,
            )
        return patterns
    except Exception as e:
        logger.warning("pattern_retrieval_failed", error=str(e))
        return []


def _compute_fix_diff(original_content: str, fixed_content: str) -> str:
    """Compute a simple line-by-line diff between original and fixed content.

    Args:
        original_content: Original file content
        fixed_content: Fixed file content

    Returns:
        Diff string truncated to 20 changed lines
    """
    diff_lines = []
    orig_lines = original_content.splitlines()
    fixed_lines = fixed_content.splitlines()

    # Simple line-by-line diff (not a full unified diff)
    for orig, fixed in zip(orig_lines, fixed_lines, strict=False):
        if orig != fixed:
            diff_lines.append(f"- {orig}")
            diff_lines.append(f"+ {fixed}")

    return "\n".join(diff_lines[:20])  # Limit diff size


def store_successful_pattern(
    check_type: str,
    check_name: str,
    error_message: str,
    file_path: str | None,
    original_content: str,
    fixed_content: str,
    project_id: str | None = None,
) -> None:
    """Store a successful fix pattern in memory.

    Called after a fix is verified to work. Stores the pattern
    for future retrieval when similar errors occur.

    Args:
        check_type: Type of check (ruff, types, etc.)
        check_name: Error code/rule name
        error_message: Original error message
        file_path: File that was fixed
        original_content: Original file content
        fixed_content: Fixed file content
    """
    try:
        fix_diff = _compute_fix_diff(original_content, fixed_content)
        pattern_memory = _get_pattern_memory(project_id)
        _run_async(
            pattern_memory.store_fix_pattern(
                check_type=check_type,
                error_code=check_name,
                error_message=error_message,
                file_path=file_path,
                fix_diff=fix_diff,
                root_cause_summary=f"Fixed {check_type}:{check_name} error",
            )
        )
        logger.info(
            "pattern_stored",
            check_type=check_type,
            check_name=check_name,
        )
    except Exception as e:
        # Pattern storage failure should not fail the fix
        logger.warning("pattern_storage_failed", error=str(e))


def format_patterns_for_prompt(patterns: list[StoredPattern]) -> str:
    """Format similar patterns for injection into the fix prompt.

    Args:
        patterns: List of similar patterns

    Returns:
        Formatted string for prompt injection
    """
    if not patterns:
        return ""

    lines = [
        "",
        "## Previous Successful Fixes for Similar Errors",
        "",
    ]

    for i, pattern in enumerate(patterns, 1):
        lines.append(f"### Fix #{i} (similarity: {pattern.similarity_score:.0%})")
        lines.append(f"**Root cause:** {pattern.root_cause_summary}")
        if pattern.fix_diff:
            lines.append("**Fix applied:**")
            lines.append("```diff")
            lines.append(pattern.fix_diff[:500])  # Truncate long diffs
            lines.append("```")
        lines.append("")

    lines.append("Consider these previous fixes when determining your approach.")
    lines.append("")

    return "\n".join(lines)


def format_attempt_history_for_prompt(approaches: list[dict[str, Any]]) -> str:
    """Format attempt history for injection into SUPERVISOR prompts.

    Tells the SUPERVISOR what approaches have already been tried and failed,
    so it can try a different approach.

    Args:
        approaches: List of previous approach dicts from AttemptHistory

    Returns:
        Formatted string for prompt injection
    """
    if not approaches:
        return ""

    lines = [
        "",
        "## Previous Fix Attempts (ALL FAILED)",
        "",
        "The following approaches have already been tried and failed.",
        "**Do NOT repeat these approaches** - try something different!",
        "",
    ]

    for approach in approaches:
        level = approach.get("escalation_level", "WORKER")
        model = approach.get("model", "unknown")
        summary = approach.get("approach_summary", "No summary")
        attempt_num = approach.get("attempt_number", "?")

        lines.append(f"### Attempt #{attempt_num} ({level} - {model})")
        lines.append(f"**Approach tried:** {summary}")
        lines.append(f"**Result:** {approach.get('outcome', 'failed')}")
        lines.append("")

    lines.append("**Your task:** Find a DIFFERENT approach that wasn't tried above.")
    lines.append("")

    return "\n".join(lines)
