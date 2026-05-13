"""Task work-product check before final closeout verification."""

from __future__ import annotations

import subprocess
from typing import Any

from ....logging_config import get_logger
from ....storage.task_spirit import get_task_spirit
from ....storage.tasks import get_task
from .events import emit_log

logger = get_logger(__name__)

_NO_CODE_MARKERS = (
    "no code edits",
    "no product code edits",
    "do not modify product code",
    "workflow validation only",
    "workflow-only",
    "temporary validation task only",
    "feedback id:",
    "marked obsolete with evidence",
)

_NO_CODE_STEP_PREFIXES = (
    "inspect",
    "confirm",
    "verify",
    "review",
    "analyze",
    "audit",
    "document",
    "summarize",
    "report",
    "identify",
    "determine",
    "check",
    "investigate",
    "diagnose",
    "reproduce",
    "classify",
    "validate",
    "run targeted validation",
    "run validation",
)

_CODE_CHANGE_PREFIXES = (
    "implement",
    "fix",
    "update",
    "change",
    "modify",
    "edit",
    "write",
    "add",
    "remove",
    "delete",
    "refactor",
    "create",
    "migrate",
)


def _detect_base_branch(project_path: str) -> str:
    """Detect the default branch (main, master, etc.) for a repository."""
    result = subprocess.run(
        ["git", "symbolic-ref", "refs/remotes/origin/HEAD"],
        cwd=project_path, capture_output=True, text=True, timeout=5,
    )
    if result.returncode == 0 and result.stdout.strip():
        return result.stdout.strip().rsplit("/", 1)[-1]
    return "main"


def _has_work_product(project_path: str) -> bool:
    """Check if the checkout contains branch-local work to verify."""
    try:
        base_branch = _detect_base_branch(project_path)
        commits = subprocess.run(
            ["git", "log", "--oneline", f"{base_branch}..HEAD"],
            cwd=project_path, capture_output=True, text=True, timeout=10,
        )
        if commits.returncode == 0 and commits.stdout and commits.stdout.strip():
            return True

        status = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=project_path, capture_output=True, text=True, timeout=10,
        )
        return bool(status.stdout and status.stdout.strip())
    except (subprocess.TimeoutExpired, OSError):
        return True


def _allows_no_code_verification(task_id: str) -> bool:
    """Return True when a task is explicitly scoped as workflow/no-code validation."""
    task = get_task(task_id) or {}
    spirit = get_task_spirit(task_id) or {}

    fields = [
        task.get("title", ""),
        task.get("description", ""),
        spirit.get("objective", ""),
        spirit.get("spirit_anti", ""),
        *(spirit.get("constraints") or []),
        *(spirit.get("done_when") or []),
    ]
    haystack = " ".join(str(field).lower() for field in fields if field)
    return any(marker in haystack for marker in _NO_CODE_MARKERS)


def _step_text(step: Any) -> str:
    """Extract comparable step text from dict-or-string step payloads."""
    if isinstance(step, dict):
        description = step.get("description")
        if isinstance(description, str):
            return description.lower()
        spec = step.get("spec")
        if isinstance(spec, str):
            return spec.lower()
        return ""
    if isinstance(step, str):
        return step.lower()
    return ""


def _allows_no_code_steps(steps: list[dict[str, Any]]) -> bool:
    """Return True for inspect/verify/document-only steps with no change verbs."""
    step_texts = [text for text in (_step_text(step) for step in steps) if text]
    if not step_texts:
        return False
    return all(
        any(text.startswith(prefix) for prefix in _NO_CODE_STEP_PREFIXES)
        and not any(text.startswith(prefix) for prefix in _CODE_CHANGE_PREFIXES)
        for text in step_texts
    )


def run_execution_quality_check(
    task_id: str,
    subtask_id: str,
    steps: list[dict[str, Any]],
    project_path: str,
    project_id: str,
) -> tuple[bool, list[dict[str, Any]]]:
    """Confirm the agent produced work before the final `st check` closeout."""
    step_results: list[dict[str, Any]] = []

    # Fail if no work product exists unless the task is explicitly no-code validation.
    if (
        not _has_work_product(project_path)
        and not _allows_no_code_verification(task_id)
        and not _allows_no_code_steps(steps)
    ):
        logger.warning("No commits on branch - marking as failed",
                       task_id=task_id, subtask_id=subtask_id)
        step_results.append({
            "step_number": 0,
            "passed": False,
            "reason": "no_work_product",
            "output": "No commits found on branch beyond main",
            "returncode": 1,
        })
        return False, step_results

    emit_log(
        task_id,
        "info",
        "Work product detected; final task-scoped check will verify it.",
        source="verify",
        project_id=project_id,
    )
    return True, step_results
