"""Subtask execution task using Agent Hub run_agent().

Executes subtasks with fresh context per subtask to prevent context rot.
"""

from __future__ import annotations

import hashlib
import re
from datetime import UTC, datetime
from typing import Any

from celery import Task, shared_task

from ...logging_config import get_logger
from ...services.agent_hub_client import get_sync_client
from ...services.pubsub import publish_ws_event
from ...services.worktree_manager import get_worktree_manager
from ...storage import log_task_event
from ...storage import tasks as task_store
from ...storage.events import EventVisibility
from ...storage.projects import get_project_root_path
from ...storage.steps import get_steps_for_subtask, update_step_passes
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


def _emit_log(
    task_id: str,
    level: str,
    message: str,
    source: str = "execution",
    *,
    project_id: str | None = None,
    visibility: EventVisibility = "user",
) -> None:
    """Emit a log event via Redis pub/sub."""
    from ...storage.events import EventLevel

    level_map: dict[str, EventLevel] = {
        "info": "info",
        "warn": "warning",
        "warning": "warning",
        "error": "error",
        "debug": "debug",
    }

    publish_ws_event(
        task_id,
        {
            "type": "log",
            "task_id": task_id,
            "data": {"level": level, "message": message, "source": source},
            "timestamp": datetime.now(UTC).isoformat(),
        },
        project_id=project_id,
        trace_id=task_id,
        source=source,
        level=level_map.get(level, "info"),
        visibility=visibility,
    )


def _emit_progress(
    task_id: str,
    subtask_id: str | None = None,
    step: int | None = None,
    status: str = "in_progress",
    total_subtasks: int | None = None,
    completed_subtasks: int | None = None,
    *,
    project_id: str | None = None,
) -> None:
    """Emit a progress event via Redis pub/sub."""
    if subtask_id:
        if step is not None:
            message = f"Subtask {subtask_id} step {step}: {status}"
        else:
            message = f"Subtask {subtask_id}: {status}"
    elif total_subtasks is not None:
        message = f"Progress: {completed_subtasks or 0}/{total_subtasks} subtasks"
    else:
        message = f"Status: {status}"

    publish_ws_event(
        task_id,
        {
            "type": "progress",
            "task_id": task_id,
            "data": {
                "message": message,
                "subtask_id": subtask_id,
                "step": step,
                "status": status,
                "total_subtasks": total_subtasks,
                "completed_subtasks": completed_subtasks,
            },
            "timestamp": datetime.now(UTC).isoformat(),
        },
        project_id=project_id,
        trace_id=task_id,
        source="orchestrator",
        visibility="user",
    )


def _emit_error(
    task_id: str,
    error: str,
    recoverable: bool = True,
    *,
    project_id: str | None = None,
) -> None:
    """Emit an error event via Redis pub/sub."""
    publish_ws_event(
        task_id,
        {
            "type": "error",
            "task_id": task_id,
            "data": {"message": error, "error": error, "recoverable": recoverable},
            "timestamp": datetime.now(UTC).isoformat(),
        },
        project_id=project_id,
        trace_id=task_id,
        source="orchestrator",
        level="error",
        visibility="user",
    )


def _reset_steps_for_rerun(subtasks: list[dict[str, Any]]) -> None:
    """Reset step passes values to allow re-running failed tasks.

    Called at the start of execution to clear previous verification results.
    This enables running the same task multiple times without stale state.
    """
    for subtask in subtasks:
        subtask_table_id = subtask.get("id", "")
        if not subtask_table_id:
            continue

        steps = get_steps_for_subtask(subtask_table_id)
        for step in steps:
            if step.get("passes"):
                update_step_passes(subtask_table_id, step["step_number"], passes=False)


def _compute_issue_id(error: str) -> str:
    """Normalize error to stable ID for stuck detection."""
    normalized = re.sub(r":\d+:", ":N:", error)
    normalized = re.sub(r"/home/\w+/", "/HOME/", normalized)
    normalized = re.sub(r"\d{4}-\d{2}-\d{2}", "DATE", normalized)
    return hashlib.md5(normalized.encode()).hexdigest()[:8]


@shared_task(bind=True, name="autonomous.start_execution")
def start_execution(self: Task[..., dict[str, Any]], task_id: str, project_id: str) -> dict[str, Any]:
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
    _emit_log(task_id, "info", "Starting autonomous execution", project_id=project_id)

    task = task_store.get_task(task_id)
    if not task:
        _emit_error(task_id, "Task not found", recoverable=False, project_id=project_id)
        return {"task_id": task_id, "status": "error", "message": "Task not found"}

    task_store.update_task_status(task_id, "running")

    subtasks = get_subtasks_for_task(task_id, include_steps=True)
    _reset_steps_for_rerun(subtasks)
    incomplete = [s for s in subtasks if not s.get("passes")]
    total = len(subtasks)
    completed = total - len(incomplete)

    _emit_progress(
        task_id, total_subtasks=total, completed_subtasks=completed, project_id=project_id
    )

    if not incomplete:
        task_store.update_task_status(task_id, "completed")
        _emit_log(task_id, "info", "All subtasks already complete", project_id=project_id)
        return {"task_id": task_id, "status": "completed", "message": "All subtasks complete"}

    results: list[dict[str, Any]] = []
    issue_counts: dict[str, int] = {}
    supervisor_attempts: dict[str, int] = {}

    for iteration, subtask in enumerate(incomplete, 1):
        if iteration > MAX_ITERATIONS:
            _emit_log(
                task_id, "warn", f"Max iterations ({MAX_ITERATIONS}) reached", project_id=project_id
            )
            _wind_down(task_id, results, incomplete, "max_iterations")
            break

        result = _execute_subtask(task_id, subtask, project_id, issue_counts)
        results.append(result)
        completed += 1
        status = "passed" if result.get("status") == "passed" else "failed"
        _emit_progress(
            task_id,
            subtask_id=result.get("subtask_id"),
            status=status,
            total_subtasks=total,
            completed_subtasks=completed,
            project_id=project_id,
        )

        if result.get("status") == "failed":
            issue_id = result.get("issue_id")
            issue_count = result.get("issue_count", 1)

            if issue_id and issue_count >= WORKER_STUCK_THRESHOLD:
                sup_count = supervisor_attempts.get(issue_id, 0)
                escalation = check_escalation_needed(issue_count, sup_count)

                if escalation.get("escalate_to_human"):
                    _emit_log(task_id, "error", "Escalating to human review", project_id=project_id)
                    task_store.update_task_status(task_id, "human_review")
                    log_task_event(
                        task_id,
                        f"ESCALATION_REQUIRED\nTask: {task_id}\nSubtask: {result.get('subtask_id')}\n"
                        f"Issue: {result.get('error', 'verification failed')}\n"
                        f"Attempts: {iteration}/{MAX_ITERATIONS}\nReason: Supervisor guidance exhausted",
                    )
                    return {"task_id": task_id, "status": "escalated", "subtask_results": results}

                if escalation.get("escalate_to_supervisor"):
                    _emit_log(
                        task_id, "warn", "Requesting supervisor guidance", project_id=project_id
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
        _emit_log(task_id, "info", "All subtasks passed, starting QA review", project_id=project_id)
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
    _emit_log(task_id, "info", f"Starting subtask {subtask_short_id}", project_id=project_id)
    _emit_progress(
        task_id, subtask_id=subtask_short_id, status="in_progress", project_id=project_id
    )

    try:
        worktree_path = _get_worktree_path(project_id, task_id)
        prompt = _build_subtask_prompt(task_id, subtask, project_id, worktree_path)
        logger.info(
            "Executing in worktree",
            subtask_id=subtask_short_id,
            worktree_path=worktree_path,
            prompt_length=len(prompt),
        )
        _emit_log(
            task_id,
            "info",
            f"Using worktree: {worktree_path}",
            project_id=project_id,
            visibility="internal",
        )
        client = get_sync_client()
        logger.info("Calling Agent Hub run_agent", agent_slug="coder", max_turns=30)
        response = client.run_agent(
            task=prompt,
            agent_slug="coder",
            working_dir=worktree_path,
            max_turns=30,
            project_id=project_id,
            use_memory=True,
        )
        logger.info(
            "Agent completed",
            subtask_id=subtask_short_id,
            response_length=len(response.content) if response.content else 0,
            session_id=response.session_id,
            cited_uuids=len(response.cited_uuids) if response.cited_uuids else 0,
        )

        # Log citations from Agent Hub response for ACE-aligned feedback
        if response.cited_uuids:
            from ...storage.subtasks import log_citations

            log_citations(task_id, subtask_short_id, response.cited_uuids, client=client)

        steps = subtask.get("steps_from_table", [])
        step_results = _verify_steps(task_id, subtask_id, steps, worktree_path, project_id)

        all_passed = all(r["passed"] for r in step_results)
        if all_passed:
            update_subtask_passes(task_id, subtask_short_id, passes=True)
            _extract_handoff_summary(subtask_id, response.content)
            _emit_log(task_id, "info", f"Subtask {subtask_short_id} passed", project_id=project_id)
        else:
            failed_steps = [r for r in step_results if not r["passed"]]
            for fail in failed_steps:
                error_msg = fail.get("error") or fail.get("reason") or "verification failed"
                issue_id = _compute_issue_id(error_msg)
                issue_counts[issue_id] = issue_counts.get(issue_id, 0) + 1
            _emit_log(
                task_id,
                "warn",
                f"Subtask {subtask_short_id} failed: {len(failed_steps)} step(s)",
                project_id=project_id,
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
        _emit_error(
            task_id, f"Subtask {subtask_short_id} error: {error_str}", project_id=project_id
        )
        return {
            "subtask_id": subtask_short_id,
            "status": "failed",
            "error": error_str,
            "issue_id": issue_id,
            "issue_count": issue_counts[issue_id],
        }


def _build_subtask_prompt(
    task_id: str,
    subtask: dict[str, Any],
    project_id: str,
    worktree_path: str,
) -> str:
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

    prompt_parts.append(f"""
# Execution Context
task_id: {task_id}
subtask_id: {subtask_short_id}
project_id: {project_id}
worktree_path: {worktree_path}
api_base: http://localhost:8001""")

    return "\n".join(prompt_parts)


def _verify_steps(
    task_id: str,
    subtask_id: str,
    steps: list[dict[str, Any]],
    worktree_path: str,
    project_id: str,
) -> list[dict[str, Any]]:
    """Run verify_command for each step and check expected_output."""
    results: list[dict[str, Any]] = []

    for step in steps:
        step_num = step.get("step_number", 0)

        result = verify_step(step, worktree_path, project_id=project_id)

        update_step_passes(subtask_id, step_num, result.passed, project_root=worktree_path)
        status = "passed" if result.passed else "failed"
        _emit_log(
            task_id,
            "info" if result.passed else "warn",
            f"Step {step_num}: {status}",
            source="verify",
        )
        _emit_progress(task_id, subtask_id=subtask_id, step=step_num, status=status)

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

    log_task_event(task_id, wind_down_log)
    task_store.update_task_status(task_id, "paused")
    _emit_log(task_id, "info", f"Session paused: {reason}")
