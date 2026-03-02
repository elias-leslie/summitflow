"""Review prompt builder for Opus code reviews.

Constructs structured prompts that guide the review process with
task context, diff analysis, and clear output format requirements.
"""

from __future__ import annotations

from .review_types import DiffStats, Task

_MAX_DIFF_LENGTH = 15000


def _build_header_section(task: Task, diff_stats: DiffStats) -> list[str]:
    """Build the header, task, and change summary sections."""
    lines: list[str] = []

    lines.append("# Code Review Request")
    lines.append("")
    lines.append("You are reviewing changes made by an autonomous agent.")
    lines.append(
        "Your job is to ensure code quality, correctness, and adherence to project rules."
    )
    lines.append("")

    lines.append("## Task")
    lines.append(f"**Title:** {task.get('title', 'No title')}")
    if task.get("description"):
        lines.append(f"**Description:** {task['description']}")
    lines.append("")

    lines.append("## Change Summary")
    lines.append(f"- Files changed: {diff_stats.get('files_changed', 0)}")
    lines.append(f"- Lines added: {diff_stats.get('insertions', 0)}")
    lines.append(f"- Lines removed: {diff_stats.get('deletions', 0)}")
    lines.append("")

    return lines


def _build_rules_section(rules: list[str]) -> list[str]:
    """Build the rules verification section, or empty list if no rules."""
    if not rules:
        return []

    lines: list[str] = []
    lines.append("## Rules to Verify")
    lines.append("Check that changes comply with:")
    for rule in rules:
        lines.append(f"- {rule}")
    lines.append("")
    return lines


def _build_checklist_section() -> list[str]:
    """Build the review checklist section."""
    lines: list[str] = []
    lines.append("## Review Checklist")
    lines.append("")
    lines.append("1. **Correctness**: Does the code do what the task requires?")
    lines.append("2. **Code Quality**: Is the code clean, readable, and maintainable?")
    lines.append("3. **Architecture**: Does it follow existing patterns? Any DRY violations?")
    lines.append(
        "4. **Security**: Any security issues (injection, auth bypass, data exposure)?"
    )
    lines.append("5. **Tests**: If tests were affected, do they make sense?")
    lines.append("6. **Dead Code**: Any commented-out or unused code added?")
    lines.append("")
    return lines


def _build_diff_section(diff: str) -> list[str]:
    """Build the diff code block section, truncating if necessary."""
    lines: list[str] = []
    lines.append("## Diff to Review")
    lines.append("")
    lines.append("```diff")
    if len(diff) > _MAX_DIFF_LENGTH:
        lines.append(diff[:_MAX_DIFF_LENGTH])
        lines.append("\n... (truncated, diff too long)")
    else:
        lines.append(diff)
    lines.append("```")
    lines.append("")
    return lines


def _build_response_section() -> list[str]:
    """Build the response format and verdict guidelines section."""
    lines: list[str] = []
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
    return lines


def build_review_prompt(
    diff: str,
    diff_stats: DiffStats,
    task: Task,
    rules: list[str],
) -> str:
    """Build the review prompt for Opus.

    Args:
        diff: Git diff output
        diff_stats: Dict with files_changed, insertions, deletions
        task: Task dict with title and description
        rules: List of relevant rule filenames

    Returns:
        Complete prompt string with review guidelines
    """
    lines: list[str] = []
    lines.extend(_build_header_section(task, diff_stats))
    lines.extend(_build_rules_section(rules))
    lines.extend(_build_checklist_section())
    lines.extend(_build_diff_section(diff))
    lines.extend(_build_response_section())
    return "\n".join(lines)
