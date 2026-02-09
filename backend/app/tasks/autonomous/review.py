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
from typing import Any

from ...logging_config import get_logger
from ...services.agent_hub_client import get_sync_client
from ...services.worktree import get_execution_path
from ...storage import log_task_event
from ...storage import tasks as task_store

logger = get_logger(__name__)


def ai_review(
    task_id: str,
    project_id: str,
    dispatch: Callable[[str, str, str], None] | None = None,
) -> dict[str, Any]:
    """Run AI review on completed task using reviewer agent (Opus).

    Reviews the git diff and provides approval/rejection verdict.

    Args:
        task_id: The task ID to review
        project_id: The project ID

    Returns:
        Review result with verdict and routing
    """
    logger.info("Starting AI review", task_id=task_id, project_id=project_id)

    task = task_store.get_task(task_id)
    if not task:
        return {"task_id": task_id, "status": "error", "message": "Task not found"}

    task_store.update_task_status(task_id, "ai_reviewing")

    # Get diff from worktree if task has one, otherwise project root
    git_diff = _get_git_diff(task_id, project_id)

    # Zero-diff guard: reject tasks with no code changes
    if not git_diff or git_diff.strip() in ("(no changes)", ""):
        logger.warning("Zero-diff detected, rejecting review", task_id=task_id)
        log_task_event(task_id, "Review rejected: no code changes detected", source="review", level="warning")
        task_store.update_task_status(task_id, "failed")
        return {
            "task_id": task_id,
            "status": "rejected",
            "verdict": "REJECTED",
            "message": "No code changes detected — task produced zero diff",
        }

    complexity = task.get("complexity") or "STANDARD"

    prompt = f"""Task: {task.get("title", "")}
Complexity: {complexity}

Git Diff:
```
{git_diff[:5000]}
```"""

    try:
        client = get_sync_client()
        response = client.complete(
            messages=[{"role": "user", "content": prompt}],
            project_id=project_id,
            agent_slug="reviewer",
        )

        review_result = _parse_review_response(response.content)
        _route_based_on_verdict(task_id, complexity, review_result)

        return {
            "task_id": task_id,
            "status": "reviewed",
            "verdict": review_result.get("verdict"),
            "complexity": complexity,
        }

    except Exception as e:
        logger.warning("AI review failed", task_id=task_id, error=str(e))
        task_store.update_task_status(task_id, "blocked")
        return {"task_id": task_id, "status": "error", "message": str(e)}


def _get_git_diff(task_id: str, project_id: str) -> str:
    """Get git diff for the task, using worktree if available.

    Args:
        task_id: Task ID to check for worktree
        project_id: Project ID for fallback path

    Returns:
        Git diff output or error message
    """
    try:
        # Use worktree path if task has one, otherwise project root
        cwd = get_execution_path(task_id, project_id)
        result = subprocess.run(
            ["git", "diff", "HEAD~1"],
            capture_output=True,
            text=True,
            timeout=30,
            cwd=cwd,
        )
        return result.stdout or "(no changes)"
    except Exception as e:
        return f"(error getting diff: {e})"


def _parse_review_response(content: str) -> dict[str, Any]:
    """Parse the reviewer agent's response."""
    import json
    import re

    try:
        json_match = re.search(r"\{[\s\S]*\}", content)
        if json_match:
            parsed: dict[str, Any] = json.loads(json_match.group())
            return parsed
    except json.JSONDecodeError:
        pass

    content_upper = content.upper()
    if "APPROVED" in content_upper:
        return {"verdict": "APPROVED", "summary": content}
    if "PLAN_DEFECT" in content_upper:
        return {"verdict": "PLAN_DEFECT", "summary": content}
    if "ESCALATE" in content_upper:
        return {"verdict": "ESCALATE", "summary": content}
    return {"verdict": "NEEDS_FIX", "summary": content}


def _supervisor_resolve_escalation(
    task_id: str, review_summary: str, project_id: str,
) -> str:
    """Supervisor triages an ESCALATE verdict. Returns 'fix', 'approve', or 'block'."""
    prompt = (
        f"AI reviewer escalated task {task_id}.\n"
        f"Reviewer said: {review_summary[:500]}\n\n"
        f"Options:\n"
        f"- FIX: Create a fix subtask to address the concern\n"
        f"- APPROVE: Override and auto-merge anyway\n"
        f"- BLOCK: Park the task\n"
        f"Reply FIX, APPROVE, or BLOCK."
    )
    try:
        client = get_sync_client()
        response = client.complete(
            messages=[{"role": "user", "content": prompt}],
            agent_slug="supervisor",
            project_id=project_id,
        )
        upper = response.content.upper()
        if "APPROVE" in upper:
            return "approve"
        if "FIX" in upper:
            return "fix"
        return "block"
    except Exception:
        return "block"


def _route_based_on_verdict(
    task_id: str,
    complexity: str,
    review_result: dict[str, Any],
) -> None:
    """Route task based on AI review verdict.

    Verdicts:
    - APPROVED: Always auto-merge
    - NEEDS_FIX with no concerns: Treat as APPROVED, auto-merge
    - NEEDS_FIX with concerns: Create fix subtask, retry execution
    - PLAN_DEFECT: Add fix step, mark original as defect, retry
    - ESCALATE/unknown: Supervisor triage → approve, fix, or block
    """
    verdict = review_result.get("verdict", "").upper()

    if verdict == "APPROVED":
        _auto_merge(task_id)
        task_store.update_task_status(task_id, "completed")
        log_task_event(
            task_id,
            f"AI Review: APPROVED - Auto-merged ({complexity})",
        )
        logger.info(
            "QA approved, auto-merged",
            task_id=task_id,
            complexity=complexity,
        )

    elif verdict in ("NEEDS_FIX", "REJECT", "REJECTED"):
        concerns = review_result.get("concerns", [])
        if not concerns:
            log_task_event(
                task_id,
                f"AI Review: {verdict} with no concerns - treating as APPROVED",
            )
            _auto_merge(task_id)
            task_store.update_task_status(task_id, "completed")
            logger.info("QA no concerns, auto-merged", task_id=task_id)
        else:
            _create_fix_subtask(task_id, review_result)
            task_store.update_task_status(task_id, "running")
            log_task_event(
                task_id,
                f"AI Review: {verdict} - Created fix subtask. Issues: {concerns}",
            )
            logger.info("QA needs fix, returning to execution", task_id=task_id)

    elif verdict == "PLAN_DEFECT":
        _handle_plan_defect(task_id, review_result)
        task_store.update_task_status(task_id, "running")
        log_task_event(
            task_id,
            "AI Review: PLAN_DEFECT - Added fix step with correct verification",
        )
        logger.info("Plan defect detected, added fix step", task_id=task_id)

    else:
        task = task_store.get_task(task_id)
        project_id = task.get("project_id", "summitflow") if task else "summitflow"
        summary = review_result.get("summary", "Unknown issue")
        decision = _supervisor_resolve_escalation(task_id, summary, project_id)

        if decision == "approve":
            _auto_merge(task_id)
            task_store.update_task_status(task_id, "completed")
            log_task_event(
                task_id,
                "AI Review: ESCALATE - Supervisor approved, auto-merged",
            )
            logger.info("Escalation overridden by supervisor, auto-merged", task_id=task_id)
        elif decision == "fix":
            _create_fix_subtask(task_id, {"concerns": [summary[:500]], "recommendation": summary[:500]})
            task_store.update_task_status(task_id, "running")
            log_task_event(
                task_id,
                "AI Review: ESCALATE - Supervisor created fix subtask",
            )
            logger.info("Escalation resolved with fix subtask", task_id=task_id)
        else:
            task_store.update_task_status(task_id, "blocked")
            log_task_event(
                task_id,
                f"AI Review: ESCALATE - Blocked. {summary[:200]}",
            )
            logger.info("QA escalated, blocked by supervisor", task_id=task_id)


def _handle_plan_defect(task_id: str, review_result: dict[str, Any]) -> None:
    """Handle plan defect by adding fix step with correct verification.

    When the implementation is correct but the verify_command is wrong,
    we add a fix step that proves correctness and mark the original as defect.
    """
    from ...storage.subtasks import create_subtask

    recommendation = review_result.get(
        "recommendation", "Implementation correct, verification fixed"
    )
    fix_steps = review_result.get("fix_steps", [])

    steps_list: list[str | dict[str, Any]] = []
    for fix in fix_steps:
        steps_list.append(
            {
                "description": fix if isinstance(fix, str) else str(fix),
                "verify_command": None,
            }
        )

    if not steps_list:
        steps_list = [
            {
                "description": "Verify correct implementation with fixed command",
                "verify_command": None,
            }
        ]

    create_subtask(
        task_id=task_id,
        subtask_id="98.1",
        description=f"Plan Defect Fix: {recommendation[:400]}",
        display_order=98,
        phase="verification",
        steps=steps_list,
    )

    logger.info("Created plan defect fix subtask", task_id=task_id)


def _auto_merge(task_id: str) -> None:
    """Auto-merge changes to main branch.

    Triggers the merge_and_cleanup_task_worktree Celery task to:
    1. Merge task branch to main
    2. Remove the worktree
    3. Delete the task branch
    """
    from .cleanup import merge_and_cleanup_task_worktree

    task = task_store.get_task(task_id)
    if not task:
        logger.warning("Cannot auto-merge: task not found", task_id=task_id)
        return

    project_id = task.get("project_id")
    if not project_id:
        logger.warning("Cannot auto-merge: no project_id", task_id=task_id)
        return

    logger.info("Triggering auto-merge", task_id=task_id, project_id=project_id)
    merge_and_cleanup_task_worktree(task_id, project_id)


def _create_fix_subtask(task_id: str, review_result: dict[str, Any]) -> None:
    """Create fix subtask from reviewer feedback."""
    from ...storage.subtasks import create_subtask

    concerns = review_result.get("concerns", [])
    recommendation = review_result.get("recommendation", "Address reviewer concerns")

    description = f"Fix: {recommendation}\n\nReviewer concerns:\n" + "\n".join(
        f"- {c}" for c in concerns
    )

    create_subtask(
        task_id=task_id,
        subtask_id="99.1",
        description=description[:500],
        display_order=99,
        phase="backend",
        steps=[{"description": "Address reviewer feedback", "verify_command": None}],
    )

    logger.info("Created fix subtask from review feedback", task_id=task_id)
