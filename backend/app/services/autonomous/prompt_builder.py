"""Prompt builder service for autonomous task execution.

Builds execution prompts with:
- Task context (title, description, files)
- Effective criteria (from capability or task junction tables)
- Filtered rules based on affected files
- Learned patterns
- Iteration context (previous failures, advice)
- Output format instructions
"""

from __future__ import annotations

from typing import Any

from ...storage.connection import get_connection
from ...storage.criteria import get_effective_criteria, get_tests_for_criterion
from ...storage.steps import get_steps_for_subtask
from ...storage.subtasks import get_subtasks_for_task


def build_execution_prompt(
    task: dict[str, Any],
    context: dict[str, Any],
    iteration_context: dict[str, Any] | None = None,
) -> str:
    """Build execution prompt for a task.

    Args:
        task: Task dict with title, description, files_affected
        context: Context dict from /context/for-task endpoint
        iteration_context: Optional dict for retries:
            - iteration: Current iteration number
            - test_failures: Output from pytest
            - static_failures: Output from pyright/ruff
            - advice: Advice from alternate model (if consulted)
            - handoff_context: Full context if handed off from another model

    Returns:
        Complete prompt string for the AI model
    """
    lines: list[str] = []

    # Task header
    lines.append("# Task Execution")
    lines.append("")
    lines.append(f"**Title:** {task.get('title', 'No title')}")

    if task.get("description"):
        lines.append(f"**Description:** {task['description']}")

    lines.append("")

    # Objective - single measurable goal
    if task.get("objective"):
        lines.append("## OBJECTIVE")
        lines.append("")
        lines.append(task["objective"])
        lines.append("")

    # Acceptance Criteria - from capability or task junction tables
    project_id = task.get("project_id") or context.get("project_id")
    if not project_id:
        raise ValueError("project_id is required for building execution prompt")
    with get_connection() as conn:
        criteria = get_effective_criteria(conn, project_id, task)

        if criteria:
            lines.append("## ACCEPTANCE CRITERIA")
            lines.append("")

            # Indicate source of criteria
            if task.get("capability_id"):
                lines.append(f"_Criteria from capability: {task['capability_id']}_")
            else:
                lines.append("_Task-specific criteria_")
            lines.append("")

            lines.append("Each criterion must be verified before task completion.")
            lines.append("Write tests to verify each criterion. Link test to criterion when done.")
            lines.append("")

            # Get test linkage for each criterion
            for c in criteria:
                verified = "x" if c.get("verified") else " "
                crit_id = c.get("criterion_id", "?")
                crit_text = c.get("criterion", "")
                threshold = c.get("threshold")
                threshold_str = f" (threshold: {threshold})" if threshold else ""

                # Get linked tests for this criterion
                tests: list[dict[str, Any]] = []
                if c.get("id"):  # Has DB id, can lookup tests
                    tests = get_tests_for_criterion(conn, c["id"])

                if tests:
                    test_names = [t.get("name", t.get("test_id", "?")) for t in tests]
                    lines.append(
                        f"- [{verified}] {crit_id}: {crit_text}{threshold_str} "
                        f"[Tests: {', '.join(test_names)}]"
                    )
                else:
                    lines.append(f"- [{verified}] {crit_id}: {crit_text}{threshold_str}")

                # Show verification status for task-linked criteria
                if c.get("verified_by"):
                    lines.append(f"  _Verified by: {c['verified_by']}_")

            lines.append("")

    # Files affected
    files = task.get("files_affected") or context.get("files") or []
    if files:
        lines.append("**Files to modify:**")
        for f in files:
            lines.append(f"- {f}")
        lines.append("")

    # Steps from subtasks table (preferred) or plan_content (fallback)
    task_id = task.get("id", "")
    steps_found = False

    # Try subtasks table first (normalized storage)
    if task_id:
        subtasks = get_subtasks_for_task(task_id, include_steps=False)
        if subtasks:
            # Find first incomplete subtask
            for subtask in subtasks:
                if not subtask.get("passes"):
                    subtask_full_id = subtask.get("id", "")
                    steps = get_steps_for_subtask(subtask_full_id)
                    if steps:
                        lines.append("**Steps to complete:**")
                        for step in steps:
                            # Show completion status for each step
                            marker = "✓" if step.get("passes") else "○"
                            lines.append(
                                f"{marker} {step.get('step_number')}. {step.get('description', '')}"
                            )
                        lines.append("")
                        steps_found = True
                    break

    # Fallback to plan_content if no subtasks found
    if not steps_found:
        plan = task.get("plan_content") or {}
        if isinstance(plan, dict):
            tasks_list = plan.get("tasks", [])
            current_id = plan.get("current_task_id")

            # Find current task in plan
            current_task = None
            for t in tasks_list:
                if t.get("id") == current_id:
                    current_task = t
                    break

            if current_task:
                lines.append("**Steps to complete:**")
                for step in current_task.get("steps", []):
                    lines.append(f"1. {step}")
                lines.append("")

    # Rules section
    rules = context.get("rule_contents", {})
    if rules:
        lines.append("---")
        lines.append("# Relevant Rules")
        lines.append("")
        lines.append("Follow these rules when implementing:")
        lines.append("")

        for rule_name, rule_content in rules.items():
            lines.append(f"## {rule_name}")
            lines.append("")
            # Truncate very long rules
            if len(rule_content) > 2000:
                lines.append(rule_content[:2000])
                lines.append("\n... (truncated)")
            else:
                lines.append(rule_content)
            lines.append("")

    # Patterns section
    patterns = context.get("patterns", [])
    if patterns:
        lines.append("---")
        lines.append("# Learned Patterns")
        lines.append("")
        lines.append("Apply these patterns from previous successful sessions:")
        lines.append("")

        for p in patterns:
            lines.append(f"- **{p.get('pattern', 'No pattern')}**")
            if p.get("rationale"):
                lines.append(f"  _{p['rationale']}_")
        lines.append("")

    # Iteration context (for retries)
    if iteration_context:
        iteration = iteration_context.get("iteration", 1)

        if iteration > 1:
            lines.append("---")
            lines.append("# PREVIOUS ATTEMPT FAILED")
            lines.append("")
            lines.append(f"This is attempt #{iteration}. The previous attempt had errors.")
            lines.append("")

            # Test failures
            test_failures = iteration_context.get("test_failures")
            if test_failures:
                lines.append("## Test Failures")
                lines.append("")
                lines.append("```")
                lines.append(test_failures[:3000])  # Truncate long output
                if len(test_failures) > 3000:
                    lines.append("... (truncated)")
                lines.append("```")
                lines.append("")

            # Static analysis failures
            static_failures = iteration_context.get("static_failures")
            if static_failures:
                lines.append("## Static Analysis Errors")
                lines.append("")
                lines.append("```")
                lines.append(static_failures[:2000])
                if len(static_failures) > 2000:
                    lines.append("... (truncated)")
                lines.append("```")
                lines.append("")

            # Advice from alternate model
            advice = iteration_context.get("advice")
            if advice:
                lines.append("## SUGGESTION FROM ALTERNATE MODEL")
                lines.append("")
                lines.append(advice)
                lines.append("")

            lines.append("**Analyze the failures above and fix the issues.")
            lines.append("Do not repeat the same approach that failed.**")
            lines.append("")

        # Handoff context (full handoff from another model)
        handoff = iteration_context.get("handoff_context")
        if handoff:
            lines.append("---")
            lines.append("# HANDOFF FROM PREVIOUS MODEL")
            lines.append("")
            lines.append(
                "The previous model was unable to complete this task. "
                "You are taking over. Here is what they tried:"
            )
            lines.append("")
            lines.append(handoff)
            lines.append("")

    # Verification commands
    lines.append("---")
    lines.append("# Verification")
    lines.append("")
    lines.append("After making changes, the following will be run automatically:")
    lines.append("- `pytest` on affected test files")
    lines.append("- `pyright` for type checking")
    lines.append("- `ruff check` for linting")
    lines.append("")
    lines.append("All must pass for the task to be marked complete.")
    lines.append("")

    # Output format instructions
    lines.append("---")
    lines.append("# Output Format")
    lines.append("")
    lines.append("Output your code changes in this format:")
    lines.append("")
    lines.append("```file:path/to/file.py")
    lines.append("# Complete file contents here")
    lines.append("def example():")
    lines.append('    return "example"')
    lines.append("```")
    lines.append("")
    lines.append("For each file you modify, output the complete file content.")
    lines.append("Do not include explanations outside the code blocks.")
    lines.append("")

    return "\n".join(lines)
