"""Validation helpers for task commands."""

from __future__ import annotations

import re
from typing import Any

_ABS_PATH_RE = re.compile(r"\bcd\s+/[^\s;|&]+")
_ABS_COMPONENT_RE = re.compile(r"(?:^|\s)/(?:home|root|tmp|var|opt|usr)/\S+")


def validate_task_item(item: dict[str, Any], index: int) -> list[str]:
    """Validate a single task item and return list of errors."""
    errors: list[str] = []
    prefix = f"tasks[{index}]"
    if "title" not in item or not item["title"]:
        errors.append(f"{prefix}: Missing required field 'title'")
    if "task_type" not in item or not item["task_type"]:
        errors.append(f"{prefix}: Missing required field 'task_type'")
    valid_types = ("feature", "bug", "task", "chore")
    if item.get("task_type") and item["task_type"] not in valid_types:
        errors.append(f"{prefix}: task_type must be one of: {', '.join(valid_types)}")
    if "priority" in item:
        p = item["priority"]
        if not isinstance(p, int) or p < 0 or p > 4:
            errors.append(f"{prefix}: priority must be integer 0-4")
    for si, subtask in enumerate(item.get("subtasks") or []):
        sub_prefix = f"{prefix}.subtasks[{si}]"
        if "subtask_id" not in subtask:
            errors.append(f"{sub_prefix}: Missing required field 'subtask_id'")
        if "description" not in subtask:
            errors.append(f"{sub_prefix}: Missing required field 'description'")
    return errors


def _validate_complexity(plan: dict[str, Any]) -> list[str]:
    """Validate conditional requirements based on complexity."""
    issues: list[str] = []
    complexity = plan.get("complexity", "SIMPLE")
    if complexity in ("STANDARD", "COMPLEX"):
        if not plan.get("spirit_anti"):
            issues.append(f"Conditional: {complexity} tasks require 'spirit_anti'")
        if not plan.get("done_when"):
            issues.append(f"Conditional: {complexity} tasks require 'done_when' with at least 1 item")
    if complexity == "COMPLEX" and not plan.get("decisions"):
        issues.append("Conditional: COMPLEX tasks require 'decisions' with at least 1 item")
    return issues


def _validate_subtask_deps(subtasks: list[dict], valid_ids: set) -> list[str]:
    """Validate depends_on references are valid and non-self-referential."""
    issues: list[str] = []
    for subtask in subtasks:
        subtask_id = subtask.get("id", "?")
        for dep in subtask.get("depends_on", []):
            if dep not in valid_ids:
                issues.append(f"subtask {subtask_id} depends_on '{dep}' which doesn't exist")
            if dep == subtask_id:
                issues.append(f"subtask {subtask_id} cannot depend on itself")
    return issues


def _validate_step(subtask_id: str, step_num: int, step: Any) -> list[str]:
    """Validate a single step object."""
    if isinstance(step, str):
        return [f"subtask {subtask_id} step {step_num}: must be object with verify_command, not string"]
    verify_cmd = step.get("verify_command", "")
    if not verify_cmd:
        return [f"subtask {subtask_id} step {step_num}: missing required 'verify_command'"]
    if _ABS_PATH_RE.search(verify_cmd) or _ABS_COMPONENT_RE.search(verify_cmd):
        return [
            f"subtask {subtask_id} step {step_num}: verify_command contains absolute path "
            f"(use relative paths — commands run with cwd=worktree): {verify_cmd[:80]}"
        ]
    return []


def _validate_subtask_steps(subtasks: list[dict]) -> list[str]:
    """Validate step structure for all subtasks."""
    issues: list[str] = []
    for subtask in subtasks:
        subtask_id = subtask.get("id", "?")
        steps = subtask.get("steps", [])
        if not steps:
            issues.append(f"subtask {subtask_id}: missing required 'steps' array")
            continue
        for step_idx, step in enumerate(steps):
            issues.extend(_validate_step(subtask_id, step_idx + 1, step))
    return issues


def _validate_deploy_browser(subtasks: list[dict]) -> list[str]:
    """Validate deploy and browser steps for backend/frontend subtasks."""
    issues: list[str] = []
    for subtask in subtasks:
        phase = subtask.get("phase", "").lower()
        if phase not in ("backend", "frontend"):
            continue
        subtask_id = subtask.get("id", "?")
        steps = [s for s in subtask.get("steps", []) if isinstance(s, dict)]
        has_deploy = any(
            "deploy" in s.get("description", "").lower() or "rebuild.sh" in s.get("verify_command", "").lower()
            for s in steps
        )
        has_browser = any(
            "agent-browser" in s.get("verify_command", "").lower() or "console error" in s.get("description", "").lower()
            for s in steps
        )
        if not has_deploy:
            issues.append(
                f"subtask {subtask_id} (phase={phase}): must have deploy step "
                f"(rebuild.sh in verify_command or 'deploy' in description)"
            )
        if phase == "frontend" and not has_browser:
            issues.append(
                f"subtask {subtask_id} (phase=frontend): must have browser verification step "
                f"(agent-browser in verify_command or 'console error' in description)"
            )
    return issues


def validate_plan_schema(plan: dict[str, Any]) -> list[str]:
    """Validate plan structure and return list of issues."""
    subtasks = plan.get("subtasks", [])
    valid_ids = {s.get("id") for s in subtasks if s.get("id")}
    issues = _validate_complexity(plan)
    issues += _validate_subtask_deps(subtasks, valid_ids)
    issues += _validate_subtask_steps(subtasks)
    issues += _validate_deploy_browser(subtasks)
    if not subtasks:
        return issues
    last = subtasks[-1]
    last_id = last.get("id", "?")
    last_phase = last.get("phase", "").lower()
    last_desc = last.get("description", "").lower()
    if not (last_phase == "verification" or "verification" in last_desc or "verify" in last_desc):
        issues.append(
            f"Final subtask {last_id} must be a verification subtask "
            f"(phase='verification' or description contains 'verification')"
        )
    return issues
