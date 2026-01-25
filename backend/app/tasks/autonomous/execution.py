"""Subtask execution task using Agent Hub run_agent().

Executes subtasks with fresh context per subtask to prevent context rot.
"""

from __future__ import annotations

import asyncio
import hashlib
import re
from typing import Any

from celery import Task as CeleryTask
from celery import shared_task

from ...api.ws_execution import send_error, send_log, send_progress
from ...logging_config import get_logger
from ...services.agent_hub_client import get_sync_client
from ...services.worktree_manager import get_worktree_manager
from ...storage import tasks as task_store
from ...storage.projects import get_project_root_path
from ...storage.steps import update_step_passes
from ...storage.subtasks import (
    get_handoff_context,
    get_subtasks_for_task,
    insert_subtask_summary,
    update_subtask_passes,
)
from ...storage.task_spirit import get_task_spirit
from .escalation import check_escalation_needed, supervisor_guidance
from .review import ai_review
from .verification import verify_step

logger = get_logger(__name__)

MAX_ITERATIONS = 50
WORKER_STUCK_THRESHOLD = 3


def _get_worktree_path(project_id: str, task_id: str) -> str:
    """Get or create worktree for task execution, protecting main branch."""
    from pathlib import Path

    project_root = get_project_root_path(project_id)
    if not project_root:
        raise ValueError(f"Project {project_id} has no root_path configured")

    manager = get_worktree_manager(Path(project_root))
    worktree = manager.get_or_create_worktree(project_id, task_id)
    return str(worktree.path)


def _emit(coro: Any) -> None:
    """Run async WebSocket emit from sync Celery context (fire-and-forget)."""
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            asyncio.ensure_future(coro)  # noqa: RUF006 (fire-and-forget)
        else:
            loop.run_until_complete(coro)
    except Exception:
        pass


def _compute_issue_id(error: str) -> str:
    """Normalize error to stable ID for stuck detection."""
    normalized = re.sub(r":\d+:", ":N:", error)
    normalized = re.sub(r"/home/\w+/", "/HOME/", normalized)
    normalized = re.sub(r"\d{4}-\d{2}-\d{2}", "DATE", normalized)
    return hashlib.md5(normalized.encode()).hexdigest()[:8]


@shared_task(bind=True, name="autonomous.start_execution")  # type: ignore[untyped-decorator]
def start_execution(self: CeleryTask, task_id: str, project_id: str) -> dict[str, Any]:
    """Start autonomous execution of a task.

    Executes subtasks in order with fresh context per subtask.
    Uses run_agent() with the worker agent for implementation.

    Args:
        task_id: The task ID to execute
        project_id: The project ID

    Returns:
        Execution result with status
    """
    logger.info("Starting autonomous execution", task_id=task_id, project_id=project_id)
    _emit(send_log(task_id, "info", "Starting autonomous execution", source="execution"))

    task = task_store.get_task(task_id)
    if not task:
        _emit(send_error(task_id, "Task not found", recoverable=False))
        return {"task_id": task_id, "status": "error", "message": "Task not found"}

    task_store.update_task_status(task_id, "running")

    subtasks = get_subtasks_for_task(task_id, include_steps=True)
    incomplete = [s for s in subtasks if not s.get("passes")]
    total = len(subtasks)
    completed = total - len(incomplete)

    _emit(send_progress(task_id, total_subtasks=total, completed_subtasks=completed))

    if not incomplete:
        task_store.update_task_status(task_id, "completed")
        _emit(send_log(task_id, "info", "All subtasks already complete", source="execution"))
        return {"task_id": task_id, "status": "completed", "message": "All subtasks complete"}

    results: list[dict[str, Any]] = []
    issue_counts: dict[str, int] = {}
    supervisor_attempts: dict[str, int] = {}

    for iteration, subtask in enumerate(incomplete, 1):
        if iteration > MAX_ITERATIONS:
            _emit(
                send_log(
                    task_id,
                    "warn",
                    f"Max iterations ({MAX_ITERATIONS}) reached",
                    source="execution",
                )
            )
            _wind_down(task_id, results, incomplete, "max_iterations")
            break

        result = _execute_subtask(task_id, subtask, project_id, issue_counts)
        results.append(result)
        completed += 1
        status = "passed" if result.get("status") == "passed" else "failed"
        _emit(
            send_progress(
                task_id,
                subtask_id=result.get("subtask_id"),
                status=status,
                total_subtasks=total,
                completed_subtasks=completed,
            )
        )

        if result.get("status") == "failed":
            issue_id = result.get("issue_id")
            issue_count = result.get("issue_count", 1)

            if issue_id and issue_count >= WORKER_STUCK_THRESHOLD:
                sup_count = supervisor_attempts.get(issue_id, 0)
                escalation = check_escalation_needed(issue_count, sup_count)

                if escalation.get("escalate_to_human"):
                    _emit(
                        send_log(task_id, "error", "Escalating to human review", source="execution")
                    )
                    task_store.update_task_status(task_id, "human_review")
                    task_store.append_progress_log(
                        task_id,
                        f"ESCALATION_REQUIRED\nTask: {task_id}\nSubtask: {result.get('subtask_id')}\n"
                        f"Issue: {result.get('error', 'verification failed')}\n"
                        f"Attempts: {iteration}/{MAX_ITERATIONS}\nReason: Supervisor guidance exhausted",
                    )
                    return {"task_id": task_id, "status": "escalated", "subtask_results": results}

                if escalation.get("escalate_to_supervisor"):
                    _emit(
                        send_log(
                            task_id, "warn", "Requesting supervisor guidance", source="execution"
                        )
                    )
                    supervisor_guidance.delay(
                        task_id,
                        result.get("subtask_id", ""),
                        result.get("error", "verification failed"),
                        sup_count,
                    )
                    supervisor_attempts[issue_id] = sup_count + 1

            break

    all_passed = all(r.get("status") == "passed" for r in results)
    if all_passed and len(results) == len(incomplete):
        _emit(
            send_log(task_id, "info", "All subtasks passed, starting QA review", source="execution")
        )
        ai_review.delay(task_id, project_id)

    return {"task_id": task_id, "status": "executed", "subtask_results": results}


def _execute_subtask(
    task_id: str,
    subtask: dict[str, Any],
    project_id: str,
    issue_counts: dict[str, int],
) -> dict[str, Any]:
    """Execute a single subtask with fresh context."""
    subtask_id = subtask.get("id", "")
    subtask_short_id = subtask.get("subtask_id", "")

    logger.info("Executing subtask", task_id=task_id, subtask_id=subtask_short_id)
    _emit(send_log(task_id, "info", f"Starting subtask {subtask_short_id}", source="execution"))
    _emit(send_progress(task_id, subtask_id=subtask_short_id, status="in_progress"))

    prompt = _build_subtask_prompt(task_id, subtask)

    try:
        worktree_path = _get_worktree_path(project_id, task_id)
        logger.info(
            "Executing in worktree",
            subtask_id=subtask_short_id,
            worktree_path=worktree_path,
            prompt_length=len(prompt),
        )
        _emit(send_log(task_id, "info", f"Using worktree: {worktree_path}", source="execution"))
        client = get_sync_client()
        logger.info("Calling Agent Hub run_agent", agent_slug="coder", max_turns=30)
        response = client.run_agent(
            task=prompt,
            agent_slug="coder",
            working_dir=worktree_path,
            max_turns=30,
        )
        logger.info(
            "Agent completed",
            subtask_id=subtask_short_id,
            response_length=len(response.content) if response.content else 0,
        )

        steps = subtask.get("steps_from_table", [])
        step_results = _verify_steps(task_id, subtask_id, steps, worktree_path)

        all_passed = all(r["passed"] for r in step_results)
        if all_passed:
            update_subtask_passes(task_id, subtask_short_id, passes=True)
            _extract_handoff_summary(subtask_id, response.content)
            _emit(
                send_log(task_id, "info", f"Subtask {subtask_short_id} passed", source="execution")
            )
        else:
            failed_steps = [r for r in step_results if not r["passed"]]
            for fail in failed_steps:
                error_msg = fail.get("error") or fail.get("reason") or "verification failed"
                issue_id = _compute_issue_id(error_msg)
                issue_counts[issue_id] = issue_counts.get(issue_id, 0) + 1
            _emit(
                send_log(
                    task_id,
                    "warn",
                    f"Subtask {subtask_short_id} failed: {len(failed_steps)} step(s)",
                    source="execution",
                )
            )

        return {
            "subtask_id": subtask_short_id,
            "status": "passed" if all_passed else "failed",
            "step_results": step_results,
            "issue_counts": {k: v for k, v in issue_counts.items() if v >= 2},
        }

    except Exception as e:
        logger.warning("Subtask execution failed", subtask_id=subtask_short_id, error=str(e))
        error_str = str(e)
        issue_id = _compute_issue_id(error_str)
        issue_counts[issue_id] = issue_counts.get(issue_id, 0) + 1
        _emit(send_error(task_id, f"Subtask {subtask_short_id} error: {error_str}"))
        return {
            "subtask_id": subtask_short_id,
            "status": "failed",
            "error": error_str,
            "issue_id": issue_id,
            "issue_count": issue_counts[issue_id],
        }


def _build_subtask_prompt(task_id: str, subtask: dict[str, Any]) -> str:
    """Build subtask prompt with fresh context: objective + spirit/anti + subtask + handoff."""
    spirit = get_task_spirit(task_id)
    objective = spirit.get("objective", "") if spirit else ""
    spirit_anti = spirit.get("spirit_anti", "") if spirit else ""

    subtask_short_id = subtask.get("subtask_id", "")
    handoff = get_handoff_context(task_id, subtask_short_id)

    prompt_parts = [f"# Task Objective\n{objective}"]

    if spirit_anti:
        prompt_parts.append(f"\n# Guiding Principles\n{spirit_anti}")

    if handoff.get("previous_summaries"):
        prompt_parts.append("\n# Previous Work Summary")
        for summary in handoff["previous_summaries"]:
            prompt_parts.append(f"- Subtask {summary['short_id']}: {summary['summary']}")

    prompt_parts.append(f"\n# Current Subtask: {subtask_short_id}")
    prompt_parts.append(f"Description: {subtask.get('description', '')}")

    steps = subtask.get("steps_from_table", [])
    if steps:
        prompt_parts.append("\nSteps to complete:")
        for step in steps:
            step_num = step.get("step_number", 0)
            desc = step.get("description", "")
            verify = step.get("verify_command", "")
            expect = step.get("expected_output", "")
            prompt_parts.append(f"{step_num}. {desc}")
            if verify:
                prompt_parts.append(f"   Verify: {verify}")
            if expect:
                prompt_parts.append(f"   Expected: {expect}")

    return "\n".join(prompt_parts)


def _verify_steps(
    task_id: str, subtask_id: str, steps: list[dict[str, Any]], worktree_path: str
) -> list[dict[str, Any]]:
    """Run verify_command for each step and check expected_output."""
    results: list[dict[str, Any]] = []

    for step in steps:
        step_num = step.get("step_number", 0)

        result = verify_step(step, worktree_path)

        update_step_passes(subtask_id, step_num, result.passed)
        status = "passed" if result.passed else "failed"
        _emit(
            send_log(
                task_id,
                "info" if result.passed else "warn",
                f"Step {step_num}: {status}",
                source="verify",
            )
        )
        _emit(send_progress(task_id, subtask_id=subtask_id, step=step_num, status=status))

        results.append(
            {
                "step_number": step_num,
                "passed": result.passed,
                "output": result.output[:500],
                "reason": result.reason,
                "returncode": result.returncode,
            }
        )

    return results


def _extract_handoff_summary(subtask_id: str, agent_response: str) -> None:
    """Extract and save handoff summary from agent response."""
    summary = agent_response[:1000] if len(agent_response) > 1000 else agent_response
    insert_subtask_summary(subtask_id, summary=summary, files_modified=[], decisions_made=[])


def _wind_down(
    task_id: str,
    results: list[dict[str, Any]],
    incomplete: list[dict[str, Any]],
    reason: str,
) -> None:
    """Preserve session state when execution pauses."""
    from datetime import UTC, datetime

    completed_ids = [r["subtask_id"] for r in results if r.get("status") == "passed"]
    failed_ids = [r["subtask_id"] for r in results if r.get("status") == "failed"]
    remaining_ids = [
        s.get("subtask_id", "")
        for s in incomplete
        if s.get("subtask_id") not in completed_ids + failed_ids
    ]

    last_failed = failed_ids[-1] if failed_ids else None

    wind_down_log = f"""SESSION END {datetime.now(UTC).strftime("%Y-%m-%d %H:%M")}:
COMPLETED: {", ".join(completed_ids) if completed_ids else "none"}
IN PROGRESS: {last_failed or "none"}
REMAINING: {", ".join(remaining_ids) if remaining_ids else "none"}

NEXT SESSION:
1. Resume at: {last_failed or remaining_ids[0] if remaining_ids else "complete"}
2. Reason for pause: {reason}
"""

    task_store.append_progress_log(task_id, wind_down_log)
    task_store.update_task_status(task_id, "paused")
    _emit(send_log(task_id, "info", f"Session paused: {reason}", source="execution"))
