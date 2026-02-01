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

from ...constants import (
    PRISTINE_SELF_HEAL_MAX_ATTEMPTS,
    SELF_HEAL_MAX_ATTEMPTS,
    SUPERVISOR_GUIDED_MAX_ATTEMPTS,
)
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
from .escalation import get_supervisor_guidance_sync
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


def _parse_error_count(output: str) -> int:
    """Parse error count from dt --check output.

    Looks for patterns like:
    - "Found N errors" / "N errors"
    - "N failed" / "N failures"
    - Fall back to counting "error:" lines
    """
    import re

    output_lower = output.lower()

    patterns = [
        r"found\s+(\d+)\s+error",
        r"(\d+)\s+error",
        r"(\d+)\s+fail",
        r"(\d+)\s+problem",
    ]

    for pattern in patterns:
        match = re.search(pattern, output_lower)
        if match:
            return int(match.group(1))

    error_lines = sum(1 for line in output.split("\n") if "error" in line.lower())
    return max(error_lines, 1 if "error" in output_lower else 0)


def pristine_self_heal(task_id: str, project_id: str) -> bool:
    """Auto-fix quality gate failures before task execution.

    Simple loop that:
    1. Runs dt --check
    2. If fails, passes error output to agent
    3. Reverts with git checkout . if error count increases
    4. Auto-commits successful fixes with [pristine] prefix

    Args:
        task_id: Task ID for logging
        project_id: Project to fix

    Returns:
        True if codebase is pristine (passed or fixed)
        False if exhausted attempts (escalate/block)
    """
    root_path = get_project_root_path(project_id)
    if not root_path:
        logger.error("pristine_self_heal_no_path", project_id=project_id)
        _emit_log(
            task_id,
            "error",
            "Pristine self-heal failed: no project path",
            source="pristine",
            project_id=project_id,
        )
        return False

    repo_path = Path(root_path)
    dt_cmd = _find_dev_tools()
    if not dt_cmd:
        logger.warning("pristine_self_heal_skipped", reason="dt not found")
        return True

    cmd = [dt_cmd, "--check"]
    previous_error_count: int | None = None

    _emit_log(
        task_id,
        "info",
        "Starting pristine self-heal: checking quality gates",
        source="pristine",
        project_id=project_id,
    )

    for attempt in range(PRISTINE_SELF_HEAL_MAX_ATTEMPTS):
        try:
            result = subprocess.run(
                cmd,
                cwd=str(repo_path),
                capture_output=True,
                text=True,
                timeout=600,
            )

            if result.returncode == 0:
                if attempt > 0:
                    if _has_uncommitted_changes(str(repo_path)):
                        _auto_commit(
                            str(repo_path),
                            f"[pristine] Auto-fix quality issues before {task_id}",
                        )
                    logger.info(
                        "pristine_self_heal_success",
                        project_id=project_id,
                        attempts=attempt + 1,
                    )
                    _emit_log(
                        task_id,
                        "info",
                        f"Pristine self-heal succeeded after {attempt + 1} attempt(s)",
                        source="pristine",
                        project_id=project_id,
                    )
                return True

            output = result.stdout + result.stderr
            error_count = _parse_error_count(output)

            if previous_error_count is not None and error_count > previous_error_count:
                logger.warning(
                    "pristine_self_heal_regression",
                    project_id=project_id,
                    previous=previous_error_count,
                    current=error_count,
                )
                _emit_log(
                    task_id,
                    "warning",
                    f"Pristine self-heal regression detected ({previous_error_count}→{error_count} errors), reverting",
                    source="pristine",
                    project_id=project_id,
                )
                subprocess.run(
                    ["git", "checkout", "."],
                    cwd=str(repo_path),
                    capture_output=True,
                )
                return False

            previous_error_count = error_count

            if attempt >= PRISTINE_SELF_HEAL_MAX_ATTEMPTS - 1:
                break

            logger.info(
                "pristine_self_heal_attempt",
                project_id=project_id,
                attempt=attempt + 1,
                error_count=error_count,
            )
            _emit_log(
                task_id,
                "info",
                f"Pristine self-heal attempt {attempt + 1}/{PRISTINE_SELF_HEAL_MAX_ATTEMPTS}: {error_count} errors, invoking coder agent",
                source="pristine",
                project_id=project_id,
            )

            client = get_sync_client()
            fix_prompt = f"""# Pristine Self-Heal: Fix Quality Gate Errors

The codebase has quality gate failures that must be fixed before task execution.

## Errors from `dt --check`:
```
{output[:8000]}
```

## Instructions
1. Fix all lint, type, and test errors shown above
2. Do NOT add new features or change behavior
3. Make minimal changes to pass quality gates
4. Focus on the specific errors listed

Fix these issues now.
"""

            response = client.run_agent(
                task=fix_prompt,
                agent_slug="coder",
                working_dir=str(repo_path),
                max_turns=20,
                project_id=project_id,
                use_memory=True,
            )

            logger.info(
                "pristine_self_heal_agent_completed",
                project_id=project_id,
                attempt=attempt + 1,
                response_length=len(response.content) if response.content else 0,
            )
            _emit_log(
                task_id,
                "info",
                f"Pristine self-heal: coder agent completed attempt {attempt + 1}",
                source="pristine",
                project_id=project_id,
            )

        except subprocess.TimeoutExpired:
            logger.error("pristine_self_heal_timeout", project_id=project_id)
            _emit_log(
                task_id,
                "error",
                "Pristine self-heal timed out",
                source="pristine",
                project_id=project_id,
            )
            return False
        except Exception as e:
            logger.error("pristine_self_heal_error", project_id=project_id, error=str(e))
            _emit_log(
                task_id,
                "error",
                f"Pristine self-heal error: {e}",
                source="pristine",
                project_id=project_id,
            )
            return False

    logger.warning(
        "pristine_self_heal_exhausted",
        project_id=project_id,
        max_attempts=PRISTINE_SELF_HEAL_MAX_ATTEMPTS,
    )
    _emit_log(
        task_id,
        "warning",
        f"Pristine self-heal exhausted {PRISTINE_SELF_HEAL_MAX_ATTEMPTS} attempts",
        source="pristine",
        project_id=project_id,
    )
    return False


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


def _emit_progress_log(
    task_id: str,
    subtask_id: str,
    progress_log: list[Any],
    *,
    project_id: str | None = None,
) -> None:
    """Emit progress_log entries from Agent Hub response as timeline events.

    Args:
        task_id: Task ID for event correlation
        subtask_id: Subtask being executed
        progress_log: List of AgentProgress entries from run_agent response
        project_id: Project ID for event scoping
    """
    if not progress_log:
        return

    for entry in progress_log:
        turn = getattr(entry, "turn", 0)
        status = getattr(entry, "status", "unknown")
        message = getattr(entry, "message", "")
        tool_calls = getattr(entry, "tool_calls", [])
        tool_results = getattr(entry, "tool_results", [])
        thinking = getattr(entry, "thinking", None)

        # Map status to log level
        level = "info"
        if status == "error":
            level = "error"
        elif status in ("thinking", "tool_use"):
            level = "debug"

        # Determine visibility based on content
        visibility: EventVisibility = "user"
        if thinking or status == "thinking":
            visibility = "internal"

        # Build event message
        if tool_calls:
            tool_names = [tc.get("name", "?") for tc in tool_calls]
            event_message = f"Turn {turn}: {status} - tools: {', '.join(tool_names)}"
        else:
            event_message = f"Turn {turn}: {status}"
            if message and message != f"Turn {turn}: sending to Gemini":
                event_message = f"Turn {turn}: {message}"

        _emit_log(
            task_id,
            level,
            event_message,
            source="agent",
            project_id=project_id,
            visibility=visibility,
        )

        # Emit tool results as separate events for detail
        for result in tool_results:
            tool_id = result.get("id", "?")
            content_preview = str(result.get("content", ""))[:200]
            _emit_log(
                task_id,
                "debug",
                f"  Tool result [{tool_id}]: {content_preview}",
                source="agent",
                project_id=project_id,
                visibility="internal",
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
    # First try self-healing, then fall back to blocking
    try:
        _emit_log(task_id, "info", "Running pristine check (dt --check)...", project_id=project_id)
        check_pristine_codebase(project_id)
        _emit_log(task_id, "info", "Pristine check passed", project_id=project_id)
    except PristineCheckError as e:
        _emit_log(
            task_id,
            "warn",
            f"Pristine check failed, attempting self-heal: {str(e)[:100]}",
            project_id=project_id,
        )

        if pristine_self_heal(task_id, project_id):
            _emit_log(task_id, "info", "Pristine self-heal succeeded", project_id=project_id)
        else:
            logger.error("pristine_self_heal_failed", task_id=task_id, error=str(e))
            task_store.update_task_status(task_id, "blocked", error_message=str(e))
            _emit_error(
                task_id,
                f"Pristine self-heal failed after {PRISTINE_SELF_HEAL_MAX_ATTEMPTS} attempts: {e}",
                recoverable=False,
                project_id=project_id,
            )
            return {
                "task_id": task_id,
                "status": "blocked",
                "error": str(e),
                "reason": "pristine_self_heal_failed",
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

        # Auto-commit after each subtask
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
            # Self-healing loop was already exhausted within _execute_subtask
            # Check if we should escalate to human review
            self_fix_attempts = result.get("self_fix_attempts", 0)
            supervisor_guided_attempts = result.get("supervisor_guided_attempts", 0)
            total_attempts = 1 + self_fix_attempts + supervisor_guided_attempts

            if supervisor_guided_attempts > 0:
                # Supervisor guidance was already tried - escalate to human
                _emit_log(
                    task_id,
                    "error",
                    f"Escalating to human review after {total_attempts} attempts "
                    f"(including {supervisor_guided_attempts} supervisor-guided)",
                    project_id=project_id,
                )
                task_store.update_task_status(task_id, "human_review")
                log_task_event(
                    task_id,
                    f"ESCALATION_REQUIRED\nTask: {task_id}\nSubtask: {result.get('subtask_id')}\n"
                    f"Issue: verification failed after self-healing\n"
                    f"Total Attempts: {total_attempts}\n"
                    f"Self-fix: {self_fix_attempts}, Supervisor-guided: {supervisor_guided_attempts}\n"
                    f"Reason: All retry attempts exhausted",
                )
                return {"task_id": task_id, "status": "escalated", "subtask_results": results}

            # Self-healing wasn't fully attempted (edge case: exception before loop)
            # Mark as blocked for retry
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


def _build_fix_prompt(
    subtask: dict[str, Any],
    failed_steps: list[dict[str, Any]],
    previous_response: str,
    supervisor_guidance: str | None = None,
) -> str:
    """Build a fix prompt with error context for self-healing.

    Args:
        subtask: The subtask being executed
        failed_steps: List of failed step verification results
        previous_response: Agent's previous response (for context)
        supervisor_guidance: Optional supervisor guidance text

    Returns:
        Fix prompt to send to agent
    """
    subtask_short_id = subtask.get("subtask_id", "")
    subtask_desc = subtask.get("description", "")

    prompt_parts = [
        f"# Fix Required for Subtask {subtask_short_id}",
        f"\nDescription: {subtask_desc}",
        "\n## Verification Failures",
        "The following verification steps failed:",
    ]

    for fail in failed_steps:
        step_num = fail.get("step_number", "?")
        reason = fail.get("reason", "unknown")
        output = fail.get("output", "")[:500]
        prompt_parts.append(f"\n### Step {step_num}: FAILED")
        prompt_parts.append(f"Reason: {reason}")
        if output:
            prompt_parts.append(f"Output:\n```\n{output}\n```")

    if supervisor_guidance:
        prompt_parts.append("\n## Supervisor Guidance")
        prompt_parts.append(supervisor_guidance)

    prompt_parts.append("\n## Your Task")
    prompt_parts.append("Fix the issues identified above. Focus on making the verification pass.")
    prompt_parts.append("After making changes, the same verification commands will run again.")

    # Include steps from subtask for reference
    steps = subtask.get("steps_from_table", [])
    if steps:
        prompt_parts.append("\n## Steps (for reference)")
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


def _execute_subtask(
    task_id: str,
    subtask: dict[str, Any],
    project_id: str,
    issue_counts: dict[str, int],
    task_type: str | None = None,
    agent_override: str | None = None,
) -> dict[str, Any]:
    """Execute a single subtask with fresh context and self-healing retry loop."""
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
        # Store session ID for continuation in retry attempts
        agent_session_id = response.session_id

        # Surface progress_log to execution timeline
        if response.progress_log:
            _emit_progress_log(
                task_id, subtask_short_id, response.progress_log, project_id=project_id
            )

        logger.info(
            "Agent completed",
            subtask_id=subtask_short_id,
            response_length=len(response.content) if response.content else 0,
            session_id=response.session_id,
            cited_uuids=len(response.cited_uuids) if response.cited_uuids else 0,
            progress_entries=len(response.progress_log) if response.progress_log else 0,
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

        # ================================================================
        # Self-Healing Retry Loop
        # ================================================================
        # After initial execution, if verification fails:
        # 1. Self-fix attempts (SELF_HEAL_MAX_ATTEMPTS)
        # 2. Supervisor-guided attempts (SUPERVISOR_GUIDED_MAX_ATTEMPTS)
        # 3. Escalate to outer loop for human review

        steps = subtask.get("steps_from_table", [])
        supervisor_guidance_text: str | None = None
        self_fix_attempts = 0
        supervisor_guided_attempts = 0
        total_max_attempts = SELF_HEAL_MAX_ATTEMPTS + SUPERVISOR_GUIDED_MAX_ATTEMPTS

        for heal_attempt in range(total_max_attempts + 1):
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

            # Success - break out of retry loop
            if all_passed:
                break

            # Exhausted all retry attempts
            if heal_attempt >= total_max_attempts:
                break

            failed_steps = [r for r in step_results if not r["passed"]]
            failed_count = len(failed_steps)

            # Determine which phase we're in
            if self_fix_attempts < SELF_HEAL_MAX_ATTEMPTS:
                # Phase 1: Self-fix attempts
                self_fix_attempts += 1
                _emit_log(
                    task_id,
                    "warn",
                    f"Verification failed ({failed_count} steps). "
                    f"Self-heal attempt {self_fix_attempts}/{SELF_HEAL_MAX_ATTEMPTS}",
                    source="orchestrator",
                    project_id=project_id,
                )

                fix_prompt = _build_fix_prompt(
                    subtask, failed_steps, response.content, supervisor_guidance=None
                )
            else:
                # Phase 2: Supervisor-guided attempts
                if supervisor_guided_attempts == 0:
                    # First supervisor attempt - get guidance
                    _emit_log(
                        task_id,
                        "warn",
                        "Self-fix exhausted. Requesting supervisor guidance...",
                        source="orchestrator",
                        project_id=project_id,
                    )

                    # Get supervisor guidance synchronously
                    error_desc = "; ".join(
                        f"Step {f.get('step_number')}: {f.get('reason', 'failed')}"
                        for f in failed_steps
                    )
                    supervisor_guidance_text = get_supervisor_guidance_sync(
                        task_id, subtask_short_id, error_desc, failed_steps
                    )

                    if supervisor_guidance_text:
                        _emit_log(
                            task_id,
                            "info",
                            f"Supervisor guidance received ({len(supervisor_guidance_text)} chars)",
                            source="supervisor",
                            project_id=project_id,
                        )
                    else:
                        _emit_log(
                            task_id,
                            "warn",
                            "Supervisor guidance unavailable, continuing without",
                            source="orchestrator",
                            project_id=project_id,
                        )

                supervisor_guided_attempts += 1
                _emit_log(
                    task_id,
                    "warn",
                    f"Verification failed ({failed_count} steps). "
                    f"Supervisor-guided attempt {supervisor_guided_attempts}/{SUPERVISOR_GUIDED_MAX_ATTEMPTS}",
                    source="orchestrator",
                    project_id=project_id,
                )

                fix_prompt = _build_fix_prompt(
                    subtask, failed_steps, response.content, supervisor_guidance_text
                )

            # Call agent with fix prompt
            _emit_log(
                task_id,
                "info",
                "Calling agent for fix attempt...",
                source="orchestrator",
                project_id=project_id,
            )

            try:
                response = client.run_agent(
                    task=fix_prompt,
                    agent_slug=agent_slug,
                    working_dir=project_path,
                    max_turns=15,  # Shorter for fix attempts
                    project_id=project_id,
                    use_memory=True,
                    resume_session_id=agent_session_id,  # Continue from previous session
                )
                # Update session ID for next iteration
                agent_session_id = response.session_id or agent_session_id

                # Surface progress_log to execution timeline
                if response.progress_log:
                    _emit_progress_log(
                        task_id, subtask_short_id, response.progress_log, project_id=project_id
                    )

                _emit_log(
                    task_id,
                    "info",
                    "Agent fix attempt completed",
                    source="agent",
                    project_id=project_id,
                )

                # Auto-commit fix attempt
                if _has_uncommitted_changes(project_path):
                    phase = "self-fix" if self_fix_attempts <= SELF_HEAL_MAX_ATTEMPTS else "guided"
                    attempt_num = (
                        self_fix_attempts if phase == "self-fix" else supervisor_guided_attempts
                    )
                    commit_msg = f"[{phase}] {subtask_short_id} attempt {attempt_num}"
                    _auto_commit(project_path, commit_msg)

            except Exception as fix_error:
                logger.warning(
                    "Fix attempt failed",
                    subtask_id=subtask_short_id,
                    attempt=heal_attempt + 1,
                    error=str(fix_error),
                )
                _emit_log(
                    task_id,
                    "error",
                    f"Fix attempt error: {str(fix_error)[:100]}",
                    source="orchestrator",
                    project_id=project_id,
                )
                # Continue to next attempt or exit loop

        # ================================================================
        # End of Self-Healing Loop - Process Final Result
        # ================================================================

        duration = time.time() - start_time
        duration_str = f"{duration:.1f}s"
        total_attempts = 1 + self_fix_attempts + supervisor_guided_attempts

        if all_passed:
            update_subtask_passes(task_id, subtask_short_id, passes=True)
            _extract_handoff_summary(subtask_id, response.content)
            attempt_info = f" (after {total_attempts} attempts)" if total_attempts > 1 else ""
            _emit_log(
                task_id,
                "info",
                f"Subtask {subtask_short_id} PASSED{attempt_info} ({duration_str})",
                project_id=project_id,
            )
            debug_success(
                f"Subtask {subtask_short_id} verified",
                task_id=task_id,
                project_id=project_id,
                duration_ms=duration * 1000,
                self_fix_attempts=self_fix_attempts,
                supervisor_guided_attempts=supervisor_guided_attempts,
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
                f"Subtask {subtask_short_id} FAILED after {total_attempts} attempts: "
                f"{len(failed_steps)} step(s) ({duration_str})",
                project_id=project_id,
            )
            debug_error(
                f"Subtask {subtask_short_id} verification failed after self-healing",
                task_id=task_id,
                project_id=project_id,
                failed_steps=len(failed_steps),
                duration_ms=duration * 1000,
                self_fix_attempts=self_fix_attempts,
                supervisor_guided_attempts=supervisor_guided_attempts,
            )

        return {
            "subtask_id": subtask_short_id,
            "status": "passed" if all_passed else "failed",
            "step_results": step_results,
            "issue_counts": {k: v for k, v in issue_counts.items() if v >= 2},
            "self_fix_attempts": self_fix_attempts,
            "supervisor_guided_attempts": supervisor_guided_attempts,
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
