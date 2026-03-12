"""Review actions: auto-merge, create fix subtasks, handle defects, QA loop."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import cast

from ....logging_config import get_logger
from ....services.agent_hub_client import get_sync_client
from ....services.smoke_test import PROD_HEALTH_URLS
from ....storage import log_task_event
from ....storage import tasks as task_store
from ....storage.projects import get_project_root_path
from ..cleanup.merge_types import MergeResult
from ..exec_modules.memory_writes import save_qa_fix_pattern
from ..verification_helpers import get_diff_range
from .parsing import parse_review_response

logger = get_logger(__name__)

MAX_QA_LOOP_ITERATIONS = 7
RECURRING_ISSUE_ESCALATION_THRESHOLD = 3


def auto_merge(task_id: str) -> MergeResult:
    """Auto-merge changes to main branch and return merge result."""
    from ..cleanup import merge_and_cleanup_task_worktree

    task = task_store.get_task(task_id)
    if not task:
        logger.warning("Cannot auto-merge: task not found", task_id=task_id)
        return cast(MergeResult, {"task_id": task_id, "status": "error", "error": "task_not_found"})
    project_id = task.get("project_id")
    if not project_id:
        logger.warning("Cannot auto-merge: no project_id", task_id=task_id)
        return cast(MergeResult, {"task_id": task_id, "status": "error", "error": "missing_project_id"})
    logger.info("Triggering auto-merge", task_id=task_id, project_id=project_id)
    merge_result = merge_and_cleanup_task_worktree(task_id, project_id)
    if merge_result.get("status") == "merged" and merge_result.get("post_merge_valid"):
        _deploy_and_verify(task_id, project_id)
    return merge_result


def _deploy_and_verify(task_id: str, project_id: str) -> None:
    """Run rebuild.sh and verify production health via CF Access."""
    project_root = get_project_root_path(project_id)
    if not project_root:
        return
    rebuild_script = str(Path(project_root) / "scripts" / "rebuild.sh")
    try:
        result = subprocess.run(
            [rebuild_script], cwd=project_root, capture_output=True, text=True, timeout=300
        )
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as e:
        log_task_event(task_id, f"Auto-deploy failed: {e}", level="error")
        return
    if result.returncode != 0:
        log_task_event(task_id, f"Auto-deploy failed: {result.stderr[-200:]}", level="error")
        return
    log_task_event(task_id, "Auto-deploy: rebuild.sh succeeded")
    prod_url = PROD_HEALTH_URLS.get(project_id)
    if not prod_url:
        return
    try:
        verify = subprocess.run(
            ["cf-curl", "-sf", prod_url], capture_output=True, text=True, timeout=30
        )
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as e:
        log_task_event(task_id, f"Production check error: {e}", level="warning")
        return
    ok = verify.returncode == 0
    log_task_event(task_id, f"Production {'verified' if ok else 'check failed'}: {prod_url}",
                   **({} if ok else {"level": "warning"}))


def create_fix_subtask(task_id: str, review_result: dict[str, object]) -> None:
    """Create fix subtask from reviewer feedback."""
    from ....storage.subtasks import create_subtask

    concerns: list[str] = list(review_result.get("concerns") or [])
    recommendation = review_result.get("recommendation", "Address reviewer concerns")
    description = f"Fix: {recommendation}\n\nReviewer concerns:\n" + "\n".join(
        f"- {c}" for c in concerns
    )
    create_subtask(
        task_id=task_id, subtask_id="99.1", description=description[:500],
        display_order=99, phase="backend",
        steps=[{"description": "Address reviewer feedback"}],
    )
    logger.info("Created fix subtask from review feedback", task_id=task_id)


def handle_plan_defect(task_id: str, review_result: dict[str, object]) -> None:
    """Handle plan defect by adding a fix step with correct verification."""
    from ....storage.subtasks import create_subtask

    recommendation = review_result.get("recommendation", "Implementation correct, verification fixed")
    fix_steps: list[object] = list(review_result.get("fix_steps") or [])
    steps_list = [
        {"description": fix if isinstance(fix, str) else str(fix)}
        for fix in fix_steps
    ] or [{"description": "Verify correct implementation with fixed command"}]
    create_subtask(
        task_id=task_id, subtask_id="98.1",
        description=f"Plan Defect Fix: {str(recommendation)[:400]}",
        display_order=98, phase="verification", steps=steps_list,
    )
    logger.info("Created plan defect fix subtask", task_id=task_id)


def _check_recurring_issues(task_id: str, concerns: list[str], tracker: dict[str, int]) -> bool:
    """Update tracker; return True if any concern hits escalation threshold."""
    for concern in concerns:
        key = concern[:100]
        tracker[key] = tracker.get(key, 0) + 1
        if tracker[key] >= RECURRING_ISSUE_ESCALATION_THRESHOLD:
            log_task_event(task_id, f"QA Loop: Recurring issue ({tracker[key]}x): {key}")
            logger.warning("QA loop recurring issue", task_id=task_id, issue=key[:80], count=tracker[key])
            return True
    return False


def _get_diff_text(project_path: str) -> str:
    """Return git diff or fallback string."""
    try:
        r = subprocess.run(
            ["git", "diff", get_diff_range(project_path)],
            cwd=project_path,
            capture_output=True,
            text=True,
            timeout=30,
        )
        return r.stdout[:5000] if r.stdout else "(no changes)"
    except Exception:
        return "(could not generate diff)"


def _run_fixer(task_id: str, project_id: str, project_path: str, fix_prompt: str, iteration: int) -> bool:
    """Invoke fixer agent; return False on failure."""
    try:
        get_sync_client().complete(
            messages=[{"role": "user", "content": fix_prompt}],
            agent_slug="fixer", project_id=project_id,
            working_dir=project_path, execute_tools=True, max_turns=25,
        )
        return True
    except Exception as e:
        logger.warning("QA loop fixer failed", task_id=task_id, iteration=iteration, error=str(e))
        return False


def _run_reviewer(
    task_id: str, project_id: str, iteration: int, diff_text: str, concerns: list[str]
) -> tuple[dict[str, object], str]:
    """Invoke reviewer agent; return (parsed_result, verdict)."""
    concerns_text = "\n".join(f"- {c}" for c in concerns)
    prompt = (
        f"Re-review after fix iteration {iteration}:\n\nChanges:\n{diff_text}\n\n"
        f"Previous concerns were:\n{concerns_text}\n\nAre these issues resolved? Reply with JSON: "
        '{"verdict": "APPROVED" | "NEEDS_FIX", "concerns": [...], "recommendation": "..."}'
    )
    re_review = get_sync_client().complete(
        messages=[{"role": "user", "content": prompt}], agent_slug="reviewer", project_id=project_id,
        execute_tools=False,
    )
    result = parse_review_response(re_review.content)
    verdict = str(result.get("verdict", "")).upper()
    log_task_event(task_id, f"QA Loop iteration {iteration}: {verdict}")
    return result, verdict


def run_qa_loop(
    task_id: str, project_id: str, review_result: dict[str, object], project_path: str
) -> str:
    """Run tight QA loop: fixer fixes issues, reviewer re-reviews until APPROVED or exhausted."""
    issue_tracker: dict[str, int] = {}
    for iteration in range(1, MAX_QA_LOOP_ITERATIONS + 1):
        concerns = list(review_result.get("concerns", []))
        recommendation = review_result.get("recommendation", "Address reviewer concerns")

        if _check_recurring_issues(task_id, concerns, issue_tracker):
            return "ESCALATE"
        concerns_text = "\n".join(f"- {c}" for c in concerns)
        fix_prompt = (
            f"The code reviewer found these issues (iteration {iteration}):\n\n"
            f"Recommendation: {recommendation}\n\nConcerns:\n{concerns_text}"
            "\n\nFix these issues. Run verify commands after each fix."
        )
        if not _run_fixer(task_id, project_id, project_path, fix_prompt, iteration):
            return "ESCALATE"
        try:
            review_result, verdict = _run_reviewer(
                task_id, project_id, iteration, _get_diff_text(project_path), concerns
            )
        except Exception as e:
            logger.warning("QA loop re-review failed", task_id=task_id, iteration=iteration, error=str(e))
            return "ESCALATE"
        if verdict == "APPROVED":
            for concern in concerns:
                save_qa_fix_pattern(task_id, project_id, concern, iteration)
            return "APPROVED"
        if verdict == "ESCALATE":
            return "ESCALATE"

    log_task_event(task_id, f"QA Loop exhausted after {MAX_QA_LOOP_ITERATIONS} iterations")
    logger.warning("QA loop exhausted", task_id=task_id, iterations=MAX_QA_LOOP_ITERATIONS)
    return "NEEDS_FIX"
