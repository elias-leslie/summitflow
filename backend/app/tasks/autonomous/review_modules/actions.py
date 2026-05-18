"""Review actions: create fix subtasks, handle defects, QA loop."""

from __future__ import annotations

import subprocess
from collections.abc import Mapping, Sequence
from typing import Any, cast

from ....logging_config import get_logger
from ....services.agent_hub_client import get_sync_client
from ....storage import log_task_event
from ..exec_modules.memory_writes import save_qa_fix_pattern
from ..verification_helpers import get_diff_range
from .parsing import parse_review_response

logger = get_logger(__name__)

MAX_QA_LOOP_ITERATIONS = 7
RECURRING_ISSUE_ESCALATION_THRESHOLD = 3


def _string_list(value: object) -> list[str]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        return []
    return [str(item) for item in value]


def create_fix_subtask(task_id: str, review_result: Mapping[str, Any]) -> None:
    """Create fix subtask from reviewer feedback."""
    from ....storage.subtasks import create_subtask

    concerns = _string_list(review_result.get("concerns"))
    recommendation = str(review_result.get("recommendation", "Address reviewer concerns"))
    description = f"Fix: {recommendation}\n\nReviewer concerns:\n" + "\n".join(
        f"- {c}" for c in concerns
    )
    create_subtask(
        task_id=task_id, subtask_id="99.1", description=description[:500],
        display_order=99, phase="backend",
        steps=[cast(dict[str, Any], {"description": "Address reviewer feedback"})],
    )
    logger.info("Created fix subtask from review feedback", task_id=task_id)


def handle_plan_defect(task_id: str, review_result: Mapping[str, Any]) -> None:
    """Handle plan defect by adding a fix step with correct verification."""
    from ....storage.subtasks import create_subtask

    recommendation = str(
        review_result.get("recommendation", "Implementation correct, verification fixed")
    )
    fix_steps = _string_list(review_result.get("fix_steps"))
    steps_list: list[str | dict[str, Any]] = []
    for fix in fix_steps:
        steps_list.append(cast(dict[str, Any], {"description": fix}))
    if not steps_list:
        steps_list.append(
            cast(dict[str, Any], {"description": "Verify correct implementation with fixed command"})
        )
    create_subtask(
        task_id=task_id, subtask_id="98.1",
        description=f"Plan Defect Fix: {recommendation[:400]}",
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
        logger.debug("Failed to generate diff for review", exc_info=True)
        return "(could not generate diff)"


def _run_debugger(
    task_id: str, project_id: str, project_path: str, fix_prompt: str, iteration: int
) -> bool:
    """Invoke debugger agent; return False on failure."""
    try:
        get_sync_client().complete(
            messages=[{"role": "user", "content": fix_prompt}],
            agent_slug="debugger", project_id=project_id,
            working_dir=project_path, execute_tools=True,
        )
        return True
    except Exception as e:
        logger.warning("QA loop debugger failed", task_id=task_id, iteration=iteration, error=str(e))
        return False


def _run_reviewer(
    task_id: str, project_id: str, iteration: int, diff_text: str, concerns: list[str]
) -> tuple[dict[str, Any], str]:
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
    task_id: str, project_id: str, review_result: Mapping[str, Any], project_path: str
) -> str:
    """Run tight QA loop: debugger fixes issues, reviewer re-reviews until APPROVED or exhausted."""
    issue_tracker: dict[str, int] = {}
    current_review: dict[str, Any] = dict(review_result)
    for iteration in range(1, MAX_QA_LOOP_ITERATIONS + 1):
        concerns = _string_list(current_review.get("concerns"))
        recommendation = str(current_review.get("recommendation", "Address reviewer concerns"))

        if _check_recurring_issues(task_id, concerns, issue_tracker):
            return "ESCALATE"
        concerns_text = "\n".join(f"- {c}" for c in concerns)
        fix_prompt = (
            f"The code reviewer found these issues (iteration {iteration}):\n\n"
            f"Recommendation: {recommendation}\n\nConcerns:\n{concerns_text}"
            "\n\nFix these issues. Run verify commands after each fix."
        )
        if not _run_debugger(task_id, project_id, project_path, fix_prompt, iteration):
            return "ESCALATE"
        try:
            current_review, verdict = _run_reviewer(
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
