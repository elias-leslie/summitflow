"""Self-healing retry loop for subtask execution."""

from __future__ import annotations

from typing import Any

from ....constants import ESCALATION_MODEL, SELF_HEAL_MAX_ATTEMPTS, SUPERVISOR_GUIDED_MAX_ATTEMPTS
from ....logging_config import get_logger
from ....storage import agent_configs
from ....storage.steps import get_steps_for_subtask
from .agent_routing import EXTENSION_ATTEMPTS
from .interruption import assert_task_runnable
from .retry_execution import execute_fix_attempt
from .retry_extensions import check_and_request_extension
from .retry_infra import handle_infrastructure_failures
from .retry_phases import determine_fix_prompt
from .steps import run_execution_quality_check
from .worktree import check_worktree_health

logger = get_logger(__name__)


def _get_retry_limits(project_id: str) -> tuple[int, int]:
    """Return (max_self_fix, max_supervisor) falling back to module constants."""
    max_self_fix = agent_configs.get_max_self_fix_attempts(project_id)
    max_supervisor = agent_configs.get_max_supervisor_attempts(project_id)
    if max_self_fix == 0:
        max_self_fix = SELF_HEAL_MAX_ATTEMPTS
    if max_supervisor == 0:
        max_supervisor = SUPERVISOR_GUIDED_MAX_ATTEMPTS
    return max_self_fix, max_supervisor


def _try_extension(
    task_id: str, subtask_id: str, subtask_short_id: str,
    steps: list[dict[str, Any]], step_results: list[dict[str, Any]],
    project_path: str, project_id: str,
    extensions_granted: int, total_max_attempts: int, guidance: str | None,
) -> tuple[bool, int, int, str | None]:
    """Request an extension; return (approved, extensions_granted, total_max_attempts, guidance)."""
    approved, extensions_granted, ext_guidance = check_and_request_extension(
        task_id, subtask_id, subtask_short_id, steps, step_results,
        project_path, project_id, extensions_granted,
    )
    if not approved:
        return False, extensions_granted, total_max_attempts, guidance
    if ext_guidance:
        guidance = ext_guidance
    return True, extensions_granted, total_max_attempts + EXTENSION_ATTEMPTS, guidance


def _run_fix_attempt(
    task_id: str, subtask: dict[str, Any], subtask_short_id: str,
    failed_steps: list[dict[str, Any]], response_content: str,
    self_fix_attempts: int, supervisor_guided_attempts: int, max_self_fix: int,
    guidance: str | None, agent_slug: str, project_path: str, project_id: str,
    agent_session_id: str | None, heal_attempt: int,
) -> tuple[str, str | None, int, int, str | None]:
    """Determine fix prompt, update counters, and execute one fix attempt."""
    fix_prompt, guidance = determine_fix_prompt(
        task_id, subtask, subtask_short_id, failed_steps, response_content,
        self_fix_attempts, supervisor_guided_attempts, guidance, project_id,
    )
    if self_fix_attempts < max_self_fix:
        self_fix_attempts += 1
    else:
        supervisor_guided_attempts += 1
    model_override = ESCALATION_MODEL if self_fix_attempts >= max_self_fix else None
    response_content, agent_session_id = execute_fix_attempt(
        task_id, subtask_short_id, fix_prompt, agent_slug, project_path, project_id,
        agent_session_id, self_fix_attempts, supervisor_guided_attempts, heal_attempt,
        model_override=model_override,
    )
    return response_content, agent_session_id, self_fix_attempts, supervisor_guided_attempts, guidance


# Sentinel for worktree-destroyed abort
_WORKTREE_DESTROYED = [{"step_number": 0, "passed": False,
                         "output": "Worktree destroyed during execution",
                         "reason": "worktree_destroyed", "returncode": -1}]


def _healing_loop_body(
    heal_attempt: int, task_id: str, subtask_id: str, subtask_short_id: str,
    subtask: dict[str, Any], steps: list[dict[str, Any]], project_path: str,
    project_id: str, agent_slug: str, agent_session_id: str | None,
    response_content: str, self_fix_attempts: int, supervisor_guided_attempts: int,
    max_self_fix: int, total_max_attempts: int, extensions_granted: int,
    guidance: str | None,
) -> tuple[bool, list[dict[str, Any]], int, int, str | None, int, int, str | None, bool]:
    """One iteration of the healing loop; returns updated state plus should_break flag."""
    assert_task_runnable(task_id, project_id, f"self_heal_attempt_{heal_attempt}")
    if heal_attempt > 0:
        steps = get_steps_for_subtask(subtask_id)
    if not check_worktree_health(project_path, task_id, project_id):
        return False, _WORKTREE_DESTROYED, self_fix_attempts, supervisor_guided_attempts, agent_session_id, total_max_attempts, extensions_granted, guidance, True
    all_passed, step_results = run_execution_quality_check(task_id, subtask_id, steps, project_path, project_id)
    if all_passed:
        return True, step_results, self_fix_attempts, supervisor_guided_attempts, agent_session_id, total_max_attempts, extensions_granted, guidance, True
    if heal_attempt >= total_max_attempts:
        approved, extensions_granted, total_max_attempts, guidance = _try_extension(
            task_id, subtask_id, subtask_short_id, steps, step_results,
            project_path, project_id, extensions_granted, total_max_attempts, guidance,
        )
        if not approved:
            return False, step_results, self_fix_attempts, supervisor_guided_attempts, agent_session_id, total_max_attempts, extensions_granted, guidance, True
    failed_steps = handle_infrastructure_failures([r for r in step_results if not r["passed"]], subtask_id, task_id, project_id)
    if not failed_steps:
        return False, step_results, self_fix_attempts, supervisor_guided_attempts, agent_session_id, total_max_attempts, extensions_granted, guidance, False
    response_content, agent_session_id, self_fix_attempts, supervisor_guided_attempts, guidance = _run_fix_attempt(
        task_id, subtask, subtask_short_id, failed_steps, response_content,
        self_fix_attempts, supervisor_guided_attempts, max_self_fix, guidance,
        agent_slug, project_path, project_id, agent_session_id, heal_attempt,
    )
    return False, step_results, self_fix_attempts, supervisor_guided_attempts, agent_session_id, total_max_attempts, extensions_granted, guidance, False


def run_self_healing_loop(
    task_id: str, subtask_id: str, subtask_short_id: str, subtask: dict[str, Any],
    steps: list[dict[str, Any]], project_path: str, project_id: str, agent_slug: str,
    agent_session_id: str | None, initial_response_content: str,
) -> tuple[bool, list[dict[str, Any]], int, int, int, str | None]:
    """Run self-healing retry loop until success or exhaustion.

    Returns:
        Tuple of (all_passed, step_results, self_fix_attempts, supervisor_guided_attempts,
                  extensions_granted, final_agent_session_id)
    """
    max_self_fix, max_supervisor = _get_retry_limits(project_id)
    guidance: str | None = None
    self_fix_attempts = 0
    supervisor_guided_attempts = 0
    total_max_attempts = max_self_fix + max_supervisor
    extensions_granted = 0
    all_passed = False
    step_results: list[dict[str, Any]] = []
    response_content = initial_response_content
    heal_attempt = 0
    while heal_attempt <= total_max_attempts:
        all_passed, step_results, self_fix_attempts, supervisor_guided_attempts, agent_session_id, total_max_attempts, extensions_granted, guidance, should_break = _healing_loop_body(
            heal_attempt, task_id, subtask_id, subtask_short_id, subtask, steps,
            project_path, project_id, agent_slug, agent_session_id, response_content,
            self_fix_attempts, supervisor_guided_attempts, max_self_fix,
            total_max_attempts, extensions_granted, guidance,
        )
        if should_break:
            break
        heal_attempt += 1
    return all_passed, step_results, self_fix_attempts, supervisor_guided_attempts, extensions_granted, agent_session_id
