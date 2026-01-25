"""AI Review task using Agent Hub complete() with reviewer agent.

Reviews git diffs and routes tasks based on complexity:
- SIMPLE: Auto-merge if approved
- STANDARD/COMPLEX: Human review if approved
- Rejected: Create fix subtask and retry
"""

from __future__ import annotations

import subprocess
from typing import Any

from celery import Task as CeleryTask
from celery import shared_task

from ...logging_config import get_logger
from ...services.agent_hub_client import get_sync_client
from ...storage import tasks as task_store

logger = get_logger(__name__)


@shared_task(bind=True, name="autonomous.ai_review")  # type: ignore[untyped-decorator]
def ai_review(self: CeleryTask, task_id: str, project_id: str) -> dict[str, Any]:
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

Task: {task.get('title', '')}
Complexity: {complexity}

Git Diff:
```
{git_diff[:5000]}
```

Provide your review:
1. VERDICT: APPROVE or REJECT
2. Summary of changes
3. Any concerns or issues found
4. Recommendations

Output format:
{{
    "verdict": "APPROVE" or "REJECT",
    "summary": "...",
    "concerns": ["..."],
    "recommendation": "..."
}}"""

    try:
        client = get_sync_client()
        response = client.complete(
            messages=[{"role": "user", "content": prompt}],
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


def _get_git_diff(project_id: str) -> str:
    """Get git diff for the project."""
    try:
        result = subprocess.run(
            ["git", "diff", "HEAD~1"],
            capture_output=True,
            text=True,
            timeout=30,
            cwd=f"/home/kasadis/{project_id}",
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

    if "APPROVE" in content.upper():
        return {"verdict": "APPROVE", "summary": content}
    return {"verdict": "REJECT", "summary": content}


def _route_based_on_verdict(
    task_id: str,
    complexity: str,
    review_result: dict[str, Any],
) -> None:
    """Route task based on AI review verdict and complexity."""
    verdict = review_result.get("verdict", "").upper()

    if verdict == "APPROVE":
        if complexity == "SIMPLE":
            _auto_merge(task_id)
            task_store.update_task_status(task_id, "completed")
            task_store.append_progress_log(task_id, "AI Review: APPROVED - Auto-merged (SIMPLE)")
        else:
            task_store.update_task_status(task_id, "human_review")
            task_store.append_progress_log(
                task_id,
                f"AI Review: APPROVED - Routing to Human Review ({complexity})",
            )
    else:
        _create_fix_subtask(task_id, review_result)
        task_store.update_task_status(task_id, "queue")
        task_store.append_progress_log(
            task_id,
            f"AI Review: REJECTED - Created fix subtask. Issues: {review_result.get('concerns', [])}",
        )


def _auto_merge(task_id: str) -> None:
    """Auto-merge via worktree manager (placeholder)."""
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
