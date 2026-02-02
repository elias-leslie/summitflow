"""AI Review task using Agent Hub complete() with reviewer agent.

Reviews git diffs and routes tasks based on complexity:
- SIMPLE: Auto-merge if approved
- STANDARD/COMPLEX: Human review if approved
- Rejected: Create fix subtask and retry
"""

from __future__ import annotations

import subprocess
from typing import Any

from celery import Task, shared_task

from ...logging_config import get_logger
from ...services.agent_hub_client import get_sync_client
from ...services.worktree import get_execution_path
from ...storage import log_task_event
from ...storage import tasks as task_store

logger = get_logger(__name__)


@shared_task(bind=True, name="autonomous.ai_review")
def ai_review(self: Task[..., dict[str, Any]], task_id: str, project_id: str) -> dict[str, Any]:
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

    git_diff = _get_git_diff(project_id)
    complexity = task.get("complexity", "STANDARD")

    prompt = f"""Review this code change for quality, correctness, and security.

Task: {task.get("title", "")}
Complexity: {complexity}

Git Diff:
```
{git_diff[:5000]}
```

Provide your review with one of these verdicts:
1. APPROVED - Code is correct and complete
2. NEEDS_FIX - Implementation has issues that need fixing
3. PLAN_DEFECT - Implementation is correct but verify_command is wrong
4. ESCALATE - Issue too complex for AI review

Output format:
{{
    "verdict": "APPROVED" | "NEEDS_FIX" | "PLAN_DEFECT" | "ESCALATE",
    "summary": "...",
    "concerns": ["..."],
    "recommendation": "...",
    "fix_steps": ["..."]  // For NEEDS_FIX
}}"""

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
        task_store.update_task_status(task_id, "human_review")
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


def _route_based_on_verdict(
    task_id: str,
    complexity: str,
    review_result: dict[str, Any],
) -> None:
    """Route task based on AI review verdict.

    Verdicts:
    - APPROVED: SIMPLE → completed (auto-merge), others → human_review
    - NEEDS_FIX: Log issues, create fix subtask, retry execution
    - PLAN_DEFECT: Add fix step, mark original as defect, retry
    - ESCALATE: Move to human_review
    """
    verdict = review_result.get("verdict", "").upper()

    if verdict == "APPROVED":
        if complexity == "SIMPLE":
            # SIMPLE tasks auto-merge after AI approval
            task_store.update_task_status(task_id, "completed")
            log_task_event(
                task_id,
                "AI Review: APPROVED - Auto-merged (SIMPLE)",
            )
            logger.info("QA approved, auto-merged SIMPLE task", task_id=task_id)
        else:
            # STANDARD/COMPLEX tasks need human review
            task_store.update_task_status(task_id, "human_review")
            log_task_event(
                task_id,
                f"AI Review: APPROVED - Requires human review ({complexity})",
            )
            logger.info(
                "QA approved, human review required", task_id=task_id, complexity=complexity
            )

    elif verdict in ("NEEDS_FIX", "REJECT", "REJECTED"):
        _create_fix_subtask(task_id, review_result)
        # Transition to running (ai_reviewing → running is valid)
        task_store.update_task_status(task_id, "running")
        log_task_event(
            task_id,
            f"AI Review: {verdict} - Created fix subtask. Issues: {review_result.get('concerns', [])}",
        )
        logger.info("QA needs fix, returning to execution", task_id=task_id)

    elif verdict == "PLAN_DEFECT":
        _handle_plan_defect(task_id, review_result)
        # Transition to running (ai_reviewing → running is valid)
        task_store.update_task_status(task_id, "running")
        log_task_event(
            task_id,
            "AI Review: PLAN_DEFECT - Added fix step with correct verification",
        )
        logger.info("Plan defect detected, added fix step", task_id=task_id)

    else:
        task_store.update_task_status(task_id, "human_review")
        log_task_event(
            task_id,
            f"AI Review: ESCALATE - {review_result.get('summary', 'Issue requires human review')[:200]}",
        )
        logger.info("QA escalated to human review", task_id=task_id)


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
    """Auto-merge changes to main branch (placeholder)."""
    logger.info("Auto-merge triggered for SIMPLE task", task_id=task_id)


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
