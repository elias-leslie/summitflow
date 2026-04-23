"""AI Review task using Agent Hub complete() with reviewer agent.

Reviews git diffs and routes tasks based on verdict:
- APPROVED: Always auto-merge
- NEEDS_FIX with no concerns: Treat as APPROVED, auto-merge
- NEEDS_FIX with concerns: Create fix subtask and retry
- ESCALATE/unknown: Supervisor triage → approve, fix, or block
"""

from __future__ import annotations

import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Any

from ...logging_config import get_logger
from ...services.agent_hub_client import get_sync_client
from ...services.context_gatherer import (
    PRECISION_CODE_SEARCH_GUIDANCE,
    collect_precision_code_search_context,
)
from ...services.task_checkout import create_task_checkout, get_execution_path
from ...services.task_harness import summarize_execution_contract
from ...storage import log_task_event
from ...storage import tasks as task_store
from ...storage.notifications import create_task_failure_notification
from ...storage.task_spirit import get_task_spirit
from .review_modules.actions import (
    auto_merge,
    create_fix_subtask,
    handle_plan_defect,
)
from .review_modules.diff import get_git_diff
from .review_modules.parsing import parse_review_response
from .review_modules.routing import (
    route_based_on_verdict,
    supervisor_resolve_escalation,
)
from .verification_helpers import get_diff_range

logger = get_logger(__name__)
_MAX_REVIEW_FILES = 5
_MAX_SNAPSHOT_CHARS = 3000


def _get_spirit_context(task_id: str) -> dict[str, Any]:
    spirit = get_task_spirit(task_id)
    context = spirit.get("context") if spirit else {}
    return context if isinstance(context, dict) else {}


def _build_precision_context(task: dict[str, Any], task_id: str, project_id: str) -> str:
    """Build shared Precision Code Search context for reviewer prompts."""
    spirit = get_task_spirit(task_id)
    done_when = spirit.get("done_when", []) if spirit else []
    queries = [
        str(task.get("title", "")),
        str(task.get("description", "")),
        *(str(item) for item in done_when),
    ]
    result = collect_precision_code_search_context(
        project_id,
        queries,
        budget_tokens=1200,
    )
    if not result.prompt_context:
        return ""
    return f"Precision Code Search:\n{result.prompt_context}\n\n"


def _collect_touched_files(task_id: str, project_id: str) -> list[str]:
    context = _get_spirit_context(task_id)
    declared_paths = [
        str(path).strip()
        for key in ("files_to_modify", "files_to_create")
        for path in context.get(key, [])
        if str(path).strip()
    ]
    discovered_paths: list[str] = []
    try:
        project_path = get_execution_path(task_id, project_id)
        result = subprocess.run(
            ["git", "diff", "--name-only", get_diff_range(project_path)],
            cwd=project_path,
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0:
            discovered_paths = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    except Exception:
        logger.debug("review_changed_files_lookup_failed", task_id=task_id, exc_info=True)

    seen: set[str] = set()
    merged: list[str] = []
    for path in [*declared_paths, *discovered_paths]:
        if path and path not in seen:
            seen.add(path)
            merged.append(path)
    return merged[:_MAX_REVIEW_FILES]


def _build_scope_block(task_id: str, project_id: str) -> str:
    touched_files = _collect_touched_files(task_id, project_id)
    if not touched_files:
        return ""
    lines = ["Touched Files:"]
    lines.extend(f"- {path}" for path in touched_files)
    return "\n".join(lines) + "\n\n"


def _build_snapshot_block(task_id: str, project_id: str) -> str:
    touched_files = _collect_touched_files(task_id, project_id)
    if not touched_files:
        return ""

    try:
        project_root = Path(get_execution_path(task_id, project_id)).resolve()
    except Exception:
        logger.debug("review_snapshot_path_resolve_failed", task_id=task_id, exc_info=True)
        return ""

    blocks: list[str] = []
    for relative_path in touched_files:
        try:
            file_path = (project_root / relative_path).resolve()
            if not file_path.is_relative_to(project_root) or not file_path.is_file():
                continue
            content = file_path.read_text(encoding="utf-8", errors="replace")
        except Exception:
            logger.debug("review_snapshot_read_failed", path=relative_path, exc_info=True)
            continue

        blocks.append(
            f"File: {relative_path}\n```\n{content[:_MAX_SNAPSHOT_CHARS]}\n```"
        )
    if not blocks:
        return ""
    return "Touched File Snapshots:\n" + "\n\n".join(blocks) + "\n\n"


def _build_execution_contract_block(task_id: str) -> str:
    context = _get_spirit_context(task_id)
    contract = context.get("execution_contract")
    summary = summarize_execution_contract(contract)
    if summary["target_url_count"] == 0 and summary["user_flow_count"] == 0 and summary["api_check_count"] == 0 and summary["negative_case_count"] == 0 and not summary["has_design_criteria"]:
        return ""
    return (
        "Execution Contract:\n"
        f"- mode: {summary['mode']}\n"
        f"- target_urls: {summary['target_url_count']}\n"
        f"- user_flows: {summary['user_flow_count']}\n"
        f"- api_checks: {summary['api_check_count']}\n"
        f"- negative_cases: {summary['negative_case_count']}\n"
        f"- design_critic: {'yes' if summary['has_design_criteria'] else 'no'}\n\n"
    )


def _notify_failure(project_id: str, task_id: str, task: dict, error_message: str) -> None:
    """Send failure notification, suppressing secondary errors."""
    try:
        session_ids = task_store.get_agent_hub_sessions(task_id)
        create_task_failure_notification(
            project_id=project_id,
            task_id=task_id,
            task_title=task.get("title", "Unknown"),
            error_message=error_message,
            agent_hub_session_ids=session_ids or None,
        )
    except Exception:
        logger.exception("Failed to create notification", task_id=task_id)


def _ensure_review_checkout(task_id: str, project_id: str, task: dict[str, Any]) -> bool:
    """Review must run against the task branch, not whatever branch was already checked out."""
    base_branch = str(task.get("base_branch") or "main")
    checkout = create_task_checkout(task_id, project_id, base_branch=base_branch)
    if checkout:
        return True
    logger.warning("review_checkout_unavailable", task_id=task_id, project_id=project_id)
    task_store.update_task_status(task_id, "failed")
    _notify_failure(project_id, task_id, task, f"Review could not switch to {task_id}/main")
    return False


def _check_diff_issues(task_id: str, project_id: str, task: dict, git_diff: str) -> dict | None:
    """Return an early-exit result dict if the diff is empty or erroneous, else None."""
    if not git_diff or git_diff.strip() in ("(no changes)", ""):
        logger.warning("Zero-diff detected, rejecting review", task_id=task_id)
        log_task_event(task_id, "Review rejected: no code changes detected", source="review", level="warning")
        task_store.update_task_status(task_id, "failed")
        _notify_failure(project_id, task_id, task, "No code changes detected — task produced zero diff.")
        return {"task_id": task_id, "status": "rejected", "verdict": "REJECTED",
                "message": "No code changes detected — task produced zero diff"}

    if git_diff.strip().startswith("(error"):
        logger.warning("Diff error detected, blocking review", task_id=task_id, diff=git_diff[:200])
        log_task_event(task_id, f"Review blocked: diff extraction failed — {git_diff.strip()[:200]}",
                       source="review", level="error")
        task_store.update_task_status(task_id, "failed")
        _notify_failure(project_id, task_id, task, f"Diff extraction failed: {git_diff.strip()[:200]}")
        return {"task_id": task_id, "status": "failed", "verdict": "BLOCKED",
                "message": f"Cannot review: {git_diff.strip()}"}

    return None


def _build_prompt(task: dict, complexity: str, git_diff: str, task_id: str) -> str:
    """Build the reviewer prompt from task metadata and diff."""
    spirit = get_task_spirit(task_id)
    done_when = spirit.get("done_when", []) if spirit else []
    done_when_text = "\n".join(f"- {c}" for c in done_when) if done_when else "(none defined)"
    precision_context = _build_precision_context(task, task_id, task.get("project_id", ""))
    scope_block = _build_scope_block(task_id, task.get("project_id", ""))
    snapshot_block = _build_snapshot_block(task_id, task.get("project_id", ""))
    contract_block = _build_execution_contract_block(task_id)

    return (
        f"Task: {task.get('title', '')}\nComplexity: {complexity}\n\n"
        f"{precision_context}"
        f"Success Criteria (done_when):\n{done_when_text}\n\n"
        f"{contract_block}"
        f"{scope_block}"
        f"{snapshot_block}"
        f"Git Diff:\n```\n{git_diff[:50000]}\n```\n\n"
        f"{PRECISION_CODE_SEARCH_GUIDANCE}\n"
        "If done_when criteria are defined, verify the diff addresses each one.\n"
        "Review the touched area, not just the patch. Reject code that leaves touched files structurally worse without justification.\n"
        "Flag new duplication, dead code, stale compatibility wrappers, broadened scope beyond the touched files, or maintainability regressions in touched files.\n\n"
        'Respond ONLY with a JSON object. No prose, no tool calls, no markdown. '
        'Required format: {"verdict": "APPROVED" | "NEEDS_FIX" | "PLAN_DEFECT" | "ESCALATE", '
        '"concerns": [...], "recommendation": "..."}'
    )


def ai_review(
    task_id: str,
    project_id: str,
    dispatch: Callable[[str, str, str], None] | None = None,
) -> dict[str, Any]:
    """Run AI review on completed task using reviewer agent (Opus).

    Reviews the git diff and provides approval/rejection verdict.
    """
    logger.info("Starting AI review", task_id=task_id, project_id=project_id)

    task = task_store.get_task(task_id)
    if not task:
        return {"task_id": task_id, "status": "error", "message": "Task not found"}

    if task.get("status") != "completed":
        task_store.update_task_status(task_id, "running")
    if not _ensure_review_checkout(task_id, project_id, task):
        return {"task_id": task_id, "status": "error", "message": f"Review could not switch to {task_id}/main"}
    git_diff = get_git_diff(task_id, project_id)

    early = _check_diff_issues(task_id, project_id, task, git_diff)
    if early:
        return early

    complexity = task.get("complexity") or "STANDARD"
    prompt = _build_prompt(task, complexity, git_diff, task_id)

    try:
        client = get_sync_client()
        response = client.complete(
            messages=[{"role": "user", "content": prompt}],
            project_id=project_id,
            agent_slug="reviewer",
            execute_tools=False,
        )
        review_result = parse_review_response(response.content)
        route_based_on_verdict(task_id, complexity, review_result)
        return {"task_id": task_id, "status": "reviewed",
                "verdict": review_result.get("verdict"), "complexity": complexity}
    except Exception as e:
        logger.warning("AI review failed", task_id=task_id, error=str(e))
        current_status = str((task_store.get_task(task_id) or {}).get("status") or "")
        if current_status == "completed":
            log_task_event(
                task_id,
                f"AI review failed while task stayed completed: {e}",
                source="review",
                level="warning",
            )
        else:
            task_store.update_task_status(task_id, "failed")
            _notify_failure(project_id, task_id, task, f"AI review failed: {e}")
        return {"task_id": task_id, "status": "error", "message": str(e)}


# Backward compatibility: expose private functions for tests
_auto_merge = auto_merge
_create_fix_subtask = create_fix_subtask
_get_git_diff = get_git_diff
_handle_plan_defect = handle_plan_defect
_parse_review_response = parse_review_response
_route_based_on_verdict = route_based_on_verdict
_supervisor_resolve_escalation = supervisor_resolve_escalation

__all__ = [
    "_auto_merge",
    "_create_fix_subtask",
    "_get_git_diff",
    "_handle_plan_defect",
    "_parse_review_response",
    "_route_based_on_verdict",
    "_supervisor_resolve_escalation",
    "ai_review",
]
