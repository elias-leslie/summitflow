"""Review actions: auto-merge, create fix subtasks, handle defects, QA loop."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

from ....logging_config import get_logger
from ....services.agent_hub_client import get_sync_client
from ....services.smoke_test import PROD_HEALTH_URLS
from ....storage import log_task_event
from ....storage import tasks as task_store
from ....storage.projects import get_project_root_path
from ..exec_modules.memory_writes import save_qa_fix_pattern

logger = get_logger(__name__)

# QA loop constants
MAX_QA_LOOP_ITERATIONS = 7
RECURRING_ISSUE_ESCALATION_THRESHOLD = 3


def auto_merge(task_id: str) -> None:
    """Auto-merge changes to main branch.

    Triggers the merge_and_cleanup_task_worktree workflow to:
    1. Merge task branch to main
    2. Remove the worktree
    3. Delete the task branch

    Args:
        task_id: Task ID to merge
    """
    from ..cleanup import merge_and_cleanup_task_worktree

    task = task_store.get_task(task_id)
    if not task:
        logger.warning("Cannot auto-merge: task not found", task_id=task_id)
        return

    project_id = task.get("project_id")
    if not project_id:
        logger.warning("Cannot auto-merge: no project_id", task_id=task_id)
        return

    logger.info("Triggering auto-merge", task_id=task_id, project_id=project_id)
    merge_result = merge_and_cleanup_task_worktree(task_id, project_id)

    if merge_result.get("status") == "merged" and merge_result.get("post_merge_valid"):
        _deploy_and_verify(task_id, project_id)


def _deploy_and_verify(task_id: str, project_id: str) -> None:
    """Run rebuild.sh and verify production health via CF Access."""
    project_root = get_project_root_path(project_id)
    if not project_root:
        return

    rebuild_script = str(Path(project_root) / "scripts" / "rebuild.sh")
    try:
        result = subprocess.run(
            [rebuild_script],
            cwd=project_root,
            capture_output=True,
            text=True,
            timeout=300,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as e:
        log_task_event(task_id, f"Auto-deploy failed: {e}", level="error")
        return

    if result.returncode != 0:
        log_task_event(
            task_id,
            f"Auto-deploy failed: {result.stderr[-200:]}",
            level="error",
        )
        return

    log_task_event(task_id, "Auto-deploy: rebuild.sh succeeded")

    prod_url = PROD_HEALTH_URLS.get(project_id)
    if not prod_url:
        return

    try:
        verify = subprocess.run(
            ["cf-curl", "-sf", prod_url],
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as e:
        log_task_event(task_id, f"Production check error: {e}", level="warning")
        return

    if verify.returncode == 0:
        log_task_event(task_id, f"Production verified: {prod_url}")
    else:
        log_task_event(task_id, f"Production check failed: {prod_url}", level="warning")


def create_fix_subtask(task_id: str, review_result: dict[str, Any]) -> None:
    """Create fix subtask from reviewer feedback.

    Args:
        task_id: Task ID to add fix subtask to
        review_result: Review result with concerns and recommendations
    """
    from ....storage.subtasks import create_subtask

    concerns = review_result.get("concerns", [])
    recommendation = review_result.get(
        "recommendation", "Address reviewer concerns"
    )

    description = (
        f"Fix: {recommendation}\n\nReviewer concerns:\n"
        + "\n".join(f"- {c}" for c in concerns)
    )

    create_subtask(
        task_id=task_id,
        subtask_id="99.1",
        description=description[:500],
        display_order=99,
        phase="backend",
        steps=[
            {"description": "Address reviewer feedback", "verify_command": None}
        ],
    )

    logger.info("Created fix subtask from review feedback", task_id=task_id)


def handle_plan_defect(task_id: str, review_result: dict[str, Any]) -> None:
    """Handle plan defect by adding fix step with correct verification.

    When the implementation is correct but the verify_command is wrong,
    we add a fix step that proves correctness and mark the original as defect.

    Args:
        task_id: Task ID to add plan defect fix to
        review_result: Review result with fix steps and recommendations
    """
    from ....storage.subtasks import create_subtask

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


def run_qa_loop(
    task_id: str,
    project_id: str,
    review_result: dict[str, Any],
    project_path: str,
) -> str:
    """Run tight QA loop: fixer agent fixes issues, reviewer re-reviews.

    Instead of creating a new subtask that re-enters the full pipeline,
    this invokes the fixer agent directly in the same worktree context,
    then re-reviews. Loops until APPROVED or max iterations.

    Args:
        task_id: Task ID
        project_id: Project ID
        review_result: Initial review result with concerns
        project_path: Worktree path for the task

    Returns:
        Final verdict: "APPROVED", "NEEDS_FIX", or "ESCALATE"
    """
    issue_tracker: dict[str, int] = {}  # concern text → occurrence count
    current_result = review_result

    for iteration in range(1, MAX_QA_LOOP_ITERATIONS + 1):
        concerns = current_result.get("concerns", [])
        recommendation = current_result.get("recommendation", "Address reviewer concerns")

        # Track recurring issues
        for concern in concerns:
            key = concern[:100]  # Normalize by truncating
            issue_tracker[key] = issue_tracker.get(key, 0) + 1
            if issue_tracker[key] >= RECURRING_ISSUE_ESCALATION_THRESHOLD:
                log_task_event(
                    task_id,
                    f"QA Loop: Recurring issue detected ({issue_tracker[key]}x): {key}",
                )
                logger.warning(
                    "QA loop recurring issue, escalating",
                    task_id=task_id, issue=key[:80], count=issue_tracker[key],
                )
                return "ESCALATE"

        # Invoke fixer agent directly in same worktree
        fix_prompt = (
            f"The code reviewer found these issues (iteration {iteration}):\n\n"
            f"Recommendation: {recommendation}\n\n"
            f"Concerns:\n"
            + "\n".join(f"- {c}" for c in concerns)
            + "\n\nFix these issues. Run verify commands after each fix."
        )

        try:
            client = get_sync_client()
            client.complete(
                messages=[{"role": "user", "content": fix_prompt}],
                agent_slug="fixer",
                project_id=project_id,
                working_dir=project_path,
                execute_tools=True,
                max_turns=25,
            )
        except Exception as e:
            logger.warning(
                "QA loop fixer failed", task_id=task_id, iteration=iteration, error=str(e)
            )
            return "ESCALATE"

        # Re-review after fix
        import subprocess

        try:
            diff_result = subprocess.run(
                ["git", "diff", "HEAD~1"],
                cwd=project_path,
                capture_output=True,
                text=True,
                timeout=30,
            )
            diff_text = diff_result.stdout[:5000] if diff_result.stdout else "(no changes)"
        except Exception:
            diff_text = "(could not generate diff)"

        review_prompt = (
            f"Re-review after fix iteration {iteration}:\n\n"
            f"Changes:\n{diff_text}\n\n"
            f"Previous concerns were:\n"
            + "\n".join(f"- {c}" for c in concerns)
            + "\n\nAre these issues resolved? Reply with JSON: "
            '{"verdict": "APPROVED" | "NEEDS_FIX", "concerns": [...], "recommendation": "..."}'
        )

        try:
            client = get_sync_client()
            re_review = client.complete(
                messages=[{"role": "user", "content": review_prompt}],
                agent_slug="reviewer",
                project_id=project_id,
            )
            from .parsing import parse_review_response

            current_result = parse_review_response(re_review.content)
            verdict = current_result.get("verdict", "").upper()

            log_task_event(
                task_id,
                f"QA Loop iteration {iteration}: {verdict}",
            )

            if verdict == "APPROVED":
                # Save fix pattern for learning
                for concern in concerns:
                    save_qa_fix_pattern(task_id, project_id, concern, iteration)
                return "APPROVED"
            if verdict == "ESCALATE":
                return "ESCALATE"
            # NEEDS_FIX continues the loop

        except Exception as e:
            logger.warning(
                "QA loop re-review failed", task_id=task_id, iteration=iteration, error=str(e)
            )
            return "ESCALATE"

    # Max iterations exhausted
    log_task_event(
        task_id,
        f"QA Loop exhausted after {MAX_QA_LOOP_ITERATIONS} iterations",
    )
    logger.warning("QA loop exhausted", task_id=task_id, iterations=MAX_QA_LOOP_ITERATIONS)
    return "NEEDS_FIX"  # Falls back to creating fix subtask
