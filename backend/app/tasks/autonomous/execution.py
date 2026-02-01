"""Subtask execution task using Agent Hub run_agent().

Executes subtasks with fresh context per subtask to prevent context rot.
"""

from __future__ import annotations

import hashlib
import re
import shutil
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from celery import Task, shared_task

from ...core.debug import (
    debug,
    debug_detailed,
    debug_error,
    debug_section,
    debug_success,
)
from ...logging_config import get_logger
from ...services.agent_hub_client import get_sync_client
from ...services.pubsub import publish_ws_event
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
from .verification import run_smoke_tests, verify_step

logger = get_logger(__name__)

MAX_ITERATIONS = 50

# Map task_type to agent_slug for specialized execution
TASK_TYPE_AGENT_MAP: dict[str, str] = {
    "refactor": "refactor",
    # Add more mappings as specialized agents are created:
    # "bug": "debugger",
    # "feature": "coder",
}
DEFAULT_AGENT = "coder"


def _get_agent_for_task(task_type: str | None) -> str:
    """Get the appropriate agent slug for a task type.

    Args:
        task_type: The task type (refactor, bug, feature, etc.)

    Returns:
        Agent slug to use for execution
    """
    if not task_type:
        return DEFAULT_AGENT
    return TASK_TYPE_AGENT_MAP.get(task_type, DEFAULT_AGENT)


class PristineCheckError(Exception):
    """Raised when codebase is not in pristine state."""

    pass


def _find_dev_tools() -> str | None:
    """Find dt command or dev-tools.sh script.

    Returns path to dt (if in PATH) or None if not found.
    """
    dt_path = shutil.which("dt")
    if dt_path:
        return dt_path
    return None


def check_pristine_codebase(project_id: str) -> None:
    """Verify codebase passes quality gates before automated execution.

    Runs lint, types, and tests to ensure no pre-existing failures that would
    cause false breaking change detection.

    Args:
        project_id: Project to check

    Raises:
        PristineCheckError: If quality gates fail
    """
    root_path = get_project_root_path(project_id)
    if not root_path:
        raise PristineCheckError(f"Project {project_id} not found or has no root_path")

    repo_path = Path(root_path)

    dt_cmd = _find_dev_tools()
    if dt_cmd:
        cmd = [dt_cmd, "--check"]
    else:
        dev_tools_script = repo_path / "scripts" / "dev-tools.sh"
        if not dev_tools_script.exists():
            logger.warning(
                "pristine_check_skipped",
                project_id=project_id,
                reason="dt command and scripts/dev-tools.sh not found",
            )
            return
        cmd = [str(dev_tools_script), "--check"]

    logger.info("pristine_check_started", project_id=project_id, cmd=cmd[0])

    try:
        result = subprocess.run(
            cmd,
            cwd=str(repo_path),
            capture_output=True,
            text=True,
            timeout=600,  # 10 minutes max
        )

        if result.returncode != 0:
            output = result.stdout + result.stderr
            logger.error(
                "pristine_check_failed",
                project_id=project_id,
                exit_code=result.returncode,
                output=output[:2000],
            )
            raise PristineCheckError(
                f"Codebase quality gates failed (exit code {result.returncode}). "
                f"Fix lint/type/test errors before running automated execution. "
                f"Run 'dt --check' to see details."
            )

        logger.info("pristine_check_passed", project_id=project_id)

    except subprocess.TimeoutExpired as e:
        raise PristineCheckError(
            "Pristine check timed out after 10 minutes. Run 'dt --check' manually to investigate."
        ) from e
    except FileNotFoundError as e:
        logger.warning(
            "pristine_check_skipped",
            project_id=project_id,
            reason=f"Command not found: {e}",
        )
        return


WORKER_STUCK_THRESHOLD = 3


def _get_project_path(project_id: str) -> str:
    """Get project root path for task execution."""
    project_root = get_project_root_path(project_id)
    if not project_root:
        raise ValueError(f"Project {project_id} has no root_path configured")
    return project_root


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


def _has_uncommitted_changes(project_path: str) -> bool:
    """Check if the working tree has uncommitted changes."""
    result = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=project_path,
        capture_output=True,
        text=True,
    )
    return bool(result.stdout.strip())


def _auto_commit(project_path: str, message: str) -> bool:
    """Auto-commit all changes with the given message.

    Returns True if commit was made, False if nothing to commit or error.
    """
    try:
        add_result = subprocess.run(
            ["git", "add", "-A"],
            cwd=project_path,
            capture_output=True,
            text=True,
        )
        if add_result.returncode != 0:
            logger.warning("git_add_failed", error=add_result.stderr)
            return False

        commit_result = subprocess.run(
            ["git", "commit", "-m", message],
            cwd=project_path,
            capture_output=True,
            text=True,
        )
        if commit_result.returncode != 0:
            if "nothing to commit" in commit_result.stdout.lower():
                return False
            logger.warning("git_commit_failed", error=commit_result.stderr)
            return False

        logger.info("auto_commit_success", message=message[:80])
        return True
    except Exception as e:
        logger.warning("auto_commit_exception", error=str(e))
        return False


@shared_task(bind=True, name="autonomous.start_execution")
def start_execution(
    self: Task[..., dict[str, Any]], task_id: str, project_id: str
) -> dict[str, Any]:
    """Start autonomous execution of a task.

    Executes subtasks in order with fresh context per subtask.
    Uses run_agent() with the worker agent for implementation.

    Args:
        task_id: The task ID to execute
        project_id: The project ID

    Returns:
        Execution result with status
    """
    debug_section("Autonomous Execution", task_id=task_id, project_id=project_id)
    logger.info("Starting autonomous execution", task_id=task_id, project_id=project_id)
    _emit_log(task_id, "info", "Starting autonomous execution", project_id=project_id)

    task = task_store.get_task(task_id)
    if not task:
        _emit_error(task_id, "Task not found", recoverable=False, project_id=project_id)
        return {"task_id": task_id, "status": "error", "message": "Task not found"}

    # Extract agent routing info
    task_type = task.get("task_type")
    agent_override = task.get("agent_override")

    # Verify codebase is pristine before automated execution
    try:
        _emit_log(task_id, "info", "Running pristine check (dt --check)...", project_id=project_id)
        check_pristine_codebase(project_id)
        _emit_log(task_id, "info", "Pristine check passed", project_id=project_id)
    except PristineCheckError as e:
        logger.error("pristine_check_failed", task_id=task_id, error=str(e))
        task_store.update_task_status(task_id, "blocked", error_message=str(e))
        _emit_error(
            task_id, f"Pristine check failed: {e}", recoverable=False, project_id=project_id
        )
        return {
            "task_id": task_id,
            "status": "blocked",
            "error": str(e),
            "reason": "pristine_check_failed",
        }

    # Auto-commit any orphaned changes from previous session
    project_path = _get_project_path(project_id)
    if _has_uncommitted_changes(project_path):
        _emit_log(
            task_id,
            "warn",
            "Found uncommitted changes from previous session, auto-committing",
            project_id=project_id,
        )
        if _auto_commit(project_path, "WIP: uncommitted changes from previous session"):
            _emit_log(task_id, "info", "Orphaned changes committed", project_id=project_id)

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

        result = _execute_subtask(
            task_id, subtask, project_id, issue_counts, task_type, agent_override
        )
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

        # Auto-commit after each subtask (supervisor ensures commits happen)
        subtask_short_id = subtask.get("subtask_id", "")
        subtask_desc = subtask.get("description", "")[:50]
        if _has_uncommitted_changes(project_path):
            commit_msg = f"Subtask {subtask_short_id}: {subtask_desc}"
            if status == "failed":
                commit_msg = f"[FAILED] {commit_msg}"
            if _auto_commit(project_path, commit_msg):
                _emit_log(
                    task_id,
                    "info",
                    f"Committed changes for subtask {subtask_short_id}",
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
        task_store.update_task_status(task_id, "ai_reviewing")
        _emit_log(task_id, "info", "All subtasks passed, starting QA review", project_id=project_id)
        ai_review.delay(task_id, project_id)
    else:
        # Some subtasks failed - mark as blocked (not stuck in "running")
        task_store.update_task_status(task_id, "blocked")
        _emit_log(
            task_id, "info", "Execution paused - subtask verification failed", project_id=project_id
        )

    return {"task_id": task_id, "status": "executed", "subtask_results": results}


def _execute_subtask(
    task_id: str,
    subtask: dict[str, Any],
    project_id: str,
    issue_counts: dict[str, int],
    task_type: str | None = None,
    agent_override: str | None = None,
) -> dict[str, Any]:
    """Execute a single subtask with fresh context."""
    import time

    start_time = time.time()
    subtask_id = subtask.get("id", "")
    subtask_short_id = subtask.get("subtask_id", "")
    subtask_desc = subtask.get("description", "")[:60]

    debug_section(f"Subtask {subtask_short_id}", task_id=task_id, project_id=project_id)
    debug(
        "Starting subtask execution",
        task_id=task_id,
        project_id=project_id,
        subtask_id=subtask_short_id,
        description=subtask_desc,
    )
    logger.info("Executing subtask", task_id=task_id, subtask_id=subtask_short_id)
    _emit_log(
        task_id,
        "info",
        f"Starting subtask {subtask_short_id}: {subtask_desc}",
        project_id=project_id,
    )
    _emit_progress(
        task_id, subtask_id=subtask_short_id, status="in_progress", project_id=project_id
    )

    try:
        project_path = _get_project_path(project_id)
        prompt = _build_subtask_prompt(task_id, subtask, project_id, project_path)

        # Resolve which agent to use: override > task_type mapping > default
        agent_slug = agent_override or _get_agent_for_task(task_type)

        logger.info(
            "Executing in project",
            subtask_id=subtask_short_id,
            project_path=project_path,
            prompt_length=len(prompt),
            agent_slug=agent_slug,
        )
        client = get_sync_client()
        _emit_log(
            task_id,
            "info",
            f"Calling agent ({agent_slug}) for subtask {subtask_short_id}...",
            source="orchestrator",
            project_id=project_id,
        )
        debug_detailed(
            "Agent input prepared",
            task_id=task_id,
            project_id=project_id,
            prompt_length=len(prompt),
            prompt_preview=prompt[:200] + "..." if len(prompt) > 200 else prompt,
        )
        logger.info("Calling Agent Hub run_agent", agent_slug=agent_slug, max_turns=30)
        response = client.run_agent(
            task=prompt,
            agent_slug=agent_slug,
            working_dir=project_path,
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
        debug_detailed(
            "Agent output received",
            task_id=task_id,
            project_id=project_id,
            response_length=len(response.content) if response.content else 0,
            session_id=response.session_id,
            citations=len(response.cited_uuids) if response.cited_uuids else 0,
        )

        # Emit agent completion with summary
        response_preview = response.content[:300] if response.content else "(no response)"
        _emit_log(
            task_id,
            "info",
            f"Agent completed subtask {subtask_short_id}",
            source="agent",
            project_id=project_id,
        )
        _emit_log(
            task_id,
            "debug",
            f"Agent response: {response_preview}",
            source="agent",
            project_id=project_id,
            visibility="internal",
        )

        # Log memory citations used
        if response.cited_uuids:
            citations_str = ", ".join(response.cited_uuids[:5])
            if len(response.cited_uuids) > 5:
                citations_str += f" (+{len(response.cited_uuids) - 5} more)"
            _emit_log(
                task_id,
                "info",
                f"Memory cited: {citations_str}",
                source="memory",
                project_id=project_id,
            )

        # Log citations from Agent Hub response for ACE-aligned feedback
        # Must acknowledge citations (or lack thereof) before subtask can pass
        if response.cited_uuids:
            from ...storage.subtasks import log_citations

            log_citations(task_id, subtask_short_id, response.cited_uuids, client=client)
        else:
            # No citations used - acknowledge this for the citation gate
            from ...storage.subtasks import acknowledge_no_citations

            acknowledge_no_citations(task_id, subtask_short_id)

        steps = subtask.get("steps_from_table", [])
        step_results = _verify_steps(task_id, subtask_id, steps, project_path, project_id)

        all_passed = all(r["passed"] for r in step_results)

        # Run smoke tests on changed files after explicit verification passes
        if all_passed:
            _emit_log(
                task_id,
                "info",
                "Running smoke tests on changed files...",
                source="verify",
                project_id=project_id,
            )
            smoke_result = run_smoke_tests(project_path)
            if not smoke_result.passed:
                all_passed = False
                # Add smoke failures to step results for visibility
                for failure in smoke_result.failures:
                    step_results.append(
                        {
                            "step_number": 999,
                            "passed": False,
                            "output": f"Import failed: {failure['error']}",
                            "reason": f"smoke_test_failed:{failure['module']}",
                            "returncode": 1,
                        }
                    )
                    _emit_log(
                        task_id,
                        "error",
                        f"Smoke test failed: {failure['module']} - {failure['error'][:100]}",
                        source="verify",
                        project_id=project_id,
                    )
            else:
                tested_count = len(smoke_result.files_tested)
                if tested_count > 0:
                    _emit_log(
                        task_id,
                        "info",
                        f"Smoke tests passed ({tested_count} modules)",
                        source="verify",
                        project_id=project_id,
                    )

        duration = time.time() - start_time
        duration_str = f"{duration:.1f}s"

        if all_passed:
            update_subtask_passes(task_id, subtask_short_id, passes=True)
            _extract_handoff_summary(subtask_id, response.content)
            _emit_log(
                task_id,
                "info",
                f"Subtask {subtask_short_id} PASSED ({duration_str})",
                project_id=project_id,
            )
            debug_success(
                f"Subtask {subtask_short_id} verified",
                task_id=task_id,
                project_id=project_id,
                duration_ms=duration * 1000,
            )
        else:
            failed_steps = [r for r in step_results if not r["passed"]]
            for fail in failed_steps:
                error_msg = fail.get("error") or fail.get("reason") or "verification failed"
                issue_id = _compute_issue_id(error_msg)
                issue_counts[issue_id] = issue_counts.get(issue_id, 0) + 1
            _emit_log(
                task_id,
                "warn",
                f"Subtask {subtask_short_id} FAILED: {len(failed_steps)} step(s) ({duration_str})",
                project_id=project_id,
            )
            debug_error(
                f"Subtask {subtask_short_id} verification failed",
                task_id=task_id,
                project_id=project_id,
                failed_steps=len(failed_steps),
                duration_ms=duration * 1000,
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
        debug_error(
            f"Subtask {subtask_short_id} exception",
            task_id=task_id,
            project_id=project_id,
            error=error_str,
            issue_id=issue_id,
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
    project_path: str,
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
project_path: {project_path}
api_base: http://localhost:8001""")

    return "\n".join(prompt_parts)


def _verify_steps(
    task_id: str,
    subtask_id: str,
    steps: list[dict[str, Any]],
    project_path: str,
    project_id: str,
) -> list[dict[str, Any]]:
    """Run verify_command for each step and check expected_output."""
    results: list[dict[str, Any]] = []

    for step in steps:
        step_num = step.get("step_number", 0)

        result = verify_step(step, project_path, project_id=project_id)

        update_step_passes(subtask_id, step_num, result.passed, project_root=project_path)
        status = "passed" if result.passed else "failed"

        # Emit detailed verification result
        step_desc = step.get("description", "")[:50]
        verify_cmd = step.get("verify_command", "")[:60]
        output_preview = result.output[:200] if result.output else "(no output)"

        _emit_log(
            task_id,
            "info" if result.passed else "warn",
            f"Step {step_num} ({step_desc}): {status}",
            source="verify",
            project_id=project_id,
        )

        # Log verification details (command, output, reason)
        _emit_log(
            task_id,
            "debug",
            f"  cmd: {verify_cmd}",
            source="verify",
            project_id=project_id,
            visibility="internal",
        )
        _emit_log(
            task_id,
            "debug" if result.passed else "warn",
            f"  output: {output_preview}",
            source="verify",
            project_id=project_id,
        )
        if not result.passed and result.reason:
            _emit_log(
                task_id,
                "warn",
                f"  reason: {result.reason}",
                source="verify",
                project_id=project_id,
            )

        _emit_progress(
            task_id, subtask_id=subtask_id, step=step_num, status=status, project_id=project_id
        )

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
