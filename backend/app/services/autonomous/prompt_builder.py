"""Prompt builder service for autonomous task execution."""

from __future__ import annotations

from typing import Any

VERIFICATION_BLOCK = """---
# Verification

After making changes, the following will be run automatically:
- `pytest` on affected test files
- `pyright` for type checking
- `ruff check` for linting

All must pass for the task to be marked complete.
"""

OUTPUT_FORMAT_BLOCK = """---
# Output Format

Output your code changes in this format:

```file:path/to/file.py
# Complete file contents here
def example():
    return "example"
```

For each file you modify, output the complete file content.
Do not include explanations outside the code blocks.
"""


def build_execution_prompt(
    task: dict[str, Any],
    context: dict[str, Any],
    iteration_context: dict[str, Any] | None = None,
) -> str:
    """Build execution prompt for a task."""
    lines = ["# Task Execution", "", f"**Title:** {task.get('title', 'No title')}"]

    if desc := task.get("description"):
        lines.append(f"**Description:** {desc}")

    if objective := task.get("objective"):
        lines.extend(["", "## OBJECTIVE", "", objective])

    files = task.get("files_affected") or context.get("files") or []
    if files:
        lines.extend(["", "**Files to modify:**"] + [f"- {f}" for f in files])

    lines.append("")
    _add_steps(lines, task)
    _add_rules(lines, context.get("rule_contents", {}))
    _add_patterns(lines, context.get("patterns", []))

    if iteration_context:
        _add_iteration_context(lines, iteration_context)

    lines.extend([VERIFICATION_BLOCK, OUTPUT_FORMAT_BLOCK])
    return "\n".join(lines).replace("\n\n\n", "\n\n")


def _format_steps(lines: list[str], steps: list[dict[str, Any]]) -> None:
    """Append formatted step entries to lines."""
    lines.append("**Steps to complete:**")
    for s in steps:
        m = "✓" if s.get("passes") else "○"
        lines.append(f"{m} {s.get('step_number')}. {s.get('description', '')}")
    lines.append("")


def _add_steps(lines: list[str], task: dict[str, Any]) -> None:
    """Add steps to the prompt from subtasks (no-op: steps layer removed)."""
    pass


def _add_rules(lines: list[str], rules: dict[str, str]) -> None:
    if not rules:
        return
    lines.extend(["---", "# Relevant Rules", "", "Follow these rules when implementing:", ""])
    for name, content in rules.items():
        lines.extend([f"## {name}", "", content[:2000] + ("\n... (truncated)" if len(content) > 2000 else ""), ""])


def _add_patterns(lines: list[str], patterns: list[dict[str, Any]]) -> None:
    if not patterns:
        return
    lines.extend(["---", "# Learned Patterns", "", "Apply these patterns from previous successful sessions:", ""])
    for p in patterns:
        lines.append(f"- **{p.get('pattern', 'No pattern')}**")
        if rationale := p.get("rationale"):
            lines.append(f"  _{rationale}_")
    lines.append("")


def _add_iteration_context(lines: list[str], ctx: dict[str, Any]) -> None:
    if (iteration := ctx.get("iteration", 1)) > 1:
        lines.extend(["---", "# PREVIOUS ATTEMPT FAILED", "", f"This is attempt #{iteration}. The previous attempt had errors.", ""])
        for key, label, limit in [("test_failures", "## Test Failures", 3000), ("static_failures", "## Static Analysis Errors", 2000)]:
            if val := ctx.get(key):
                lines.extend([label, "", "```", val[:limit] + ("\n... (truncated)" if len(val) > limit else ""), "```", ""])
        if advice := ctx.get("advice"):
            lines.extend(["## SUGGESTION FROM ALTERNATE MODEL", "", advice, ""])
        lines.extend(["**Analyze the failures above and fix the issues.", "Do not repeat the same approach that failed.**", ""])

    if handoff := ctx.get("handoff_context"):
        lines.extend(["---", "# HANDOFF FROM PREVIOUS MODEL", "", "The previous model was unable to complete this task. You are taking over. Here is what they tried:", "", handoff, ""])
