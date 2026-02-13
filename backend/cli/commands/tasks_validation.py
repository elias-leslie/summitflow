"""Validation helpers for task commands."""

from __future__ import annotations

import re
from typing import Any


def validate_task_item(item: dict[str, Any], index: int) -> list[str]:
    """Validate a single task item and return list of errors."""
    errors: list[str] = []
    prefix = f"tasks[{index}]"

    # Required fields
    if "title" not in item or not item["title"]:
        errors.append(f"{prefix}: Missing required field 'title'")
    if "task_type" not in item or not item["task_type"]:
        errors.append(f"{prefix}: Missing required field 'task_type'")

    # Validate task_type
    valid_types = ("feature", "bug", "task", "chore")
    if item.get("task_type") and item["task_type"] not in valid_types:
        errors.append(f"{prefix}: task_type must be one of: {', '.join(valid_types)}")

    # Validate priority
    if "priority" in item:
        p = item["priority"]
        if not isinstance(p, int) or p < 0 or p > 4:
            errors.append(f"{prefix}: priority must be integer 0-4")

    # Validate subtasks if present
    if item.get("subtasks"):
        for si, subtask in enumerate(item["subtasks"]):
            sub_prefix = f"{prefix}.subtasks[{si}]"
            if "subtask_id" not in subtask:
                errors.append(f"{sub_prefix}: Missing required field 'subtask_id'")
            if "description" not in subtask:
                errors.append(f"{sub_prefix}: Missing required field 'description'")

    return errors


def validate_plan_schema(plan: dict[str, Any]) -> list[str]:
    """Validate plan structure and return list of issues.

    Returns:
        List of validation issues (empty if valid)
    """
    issues: list[str] = []

    # Check conditional requirements
    complexity = plan.get("complexity", "SIMPLE")

    if complexity in ("STANDARD", "COMPLEX"):
        if not plan.get("spirit_anti"):
            issues.append(f"Conditional: {complexity} tasks require 'spirit_anti'")
        done_when = plan.get("done_when", [])
        if not done_when or len(done_when) < 1:
            issues.append(
                f"Conditional: {complexity} tasks require 'done_when' with at least 1 item"
            )

    if complexity == "COMPLEX":
        decisions = plan.get("decisions", [])
        if not decisions or len(decisions) < 1:
            issues.append("Conditional: COMPLEX tasks require 'decisions' with at least 1 item")

    # Collect valid subtask IDs for dependency validation
    subtasks = plan.get("subtasks", [])
    valid_subtask_ids = {s.get("id") for s in subtasks if s.get("id")}

    # Validate depends_on references point to valid subtask IDs
    for subtask in subtasks:
        subtask_id = subtask.get("id", "?")
        depends_on = subtask.get("depends_on", [])
        if depends_on:
            for dep in depends_on:
                if dep not in valid_subtask_ids:
                    issues.append(f"subtask {subtask_id} depends_on '{dep}' which doesn't exist")
                if dep == subtask_id:
                    issues.append(f"subtask {subtask_id} cannot depend on itself")

    # Validate step structure
    for subtask in subtasks:
        subtask_id = subtask.get("id", "?")
        steps = subtask.get("steps", [])

        if not steps:
            issues.append(f"subtask {subtask_id}: missing required 'steps' array")
            continue

        for step_idx, step in enumerate(steps):
            step_num = step_idx + 1
            if isinstance(step, str):
                issues.append(
                    f"subtask {subtask_id} step {step_num}: must be object with verify_command, "
                    f"not string"
                )
                continue

            if not step.get("verify_command"):
                issues.append(
                    f"subtask {subtask_id} step {step_num}: missing required 'verify_command'"
                )
            elif re.search(r"\bcd\s+/[^\s;|&]+", step["verify_command"]) or re.search(
                r"(?:^|\s)/(?:home|root|tmp|var|opt|usr)/\S+", step["verify_command"]
            ):
                issues.append(
                    f"subtask {subtask_id} step {step_num}: verify_command contains absolute path "
                    f"(use relative paths — commands run with cwd=worktree): "
                    f"{step['verify_command'][:80]}"
                )

    # Validate deploy and browser steps for backend/frontend subtasks
    for subtask in subtasks:
        subtask_id = subtask.get("id", "?")
        phase = subtask.get("phase", "").lower()
        steps = subtask.get("steps", [])

        if phase in ("backend", "frontend") and steps:
            has_deploy = False
            has_browser_check = False

            for step in steps:
                if isinstance(step, dict):
                    step_desc = step.get("description", "").lower()
                    verify_cmd = step.get("verify_command", "").lower()

                    if "deploy" in step_desc or "rebuild.sh" in verify_cmd:
                        has_deploy = True
                    if "agent-browser" in verify_cmd or "console error" in step_desc:
                        has_browser_check = True

            if not has_deploy:
                issues.append(
                    f"subtask {subtask_id} (phase={phase}): must have deploy step "
                    f"(rebuild.sh in verify_command or 'deploy' in description)"
                )

            if phase == "frontend" and not has_browser_check:
                issues.append(
                    f"subtask {subtask_id} (phase=frontend): must have browser verification step "
                    f"(agent-browser in verify_command or 'console error' in description)"
                )

    # Validate final verification subtask
    if subtasks:
        last_subtask = subtasks[-1]
        last_id = last_subtask.get("id", "?")
        last_phase = last_subtask.get("phase", "").lower()
        last_desc = last_subtask.get("description", "").lower()

        is_verification = (
            last_phase == "verification" or "verification" in last_desc or "verify" in last_desc
        )
        if not is_verification:
            issues.append(
                f"Final subtask {last_id} must be a verification subtask "
                f"(phase='verification' or description contains 'verification')"
            )

    return issues
