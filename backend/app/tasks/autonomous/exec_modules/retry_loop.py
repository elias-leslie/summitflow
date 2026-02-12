"""Self-healing retry loop for subtask execution."""

from __future__ import annotations

from typing import Any

from ....constants import ESCALATION_MODEL, SELF_HEAL_MAX_ATTEMPTS, SUPERVISOR_GUIDED_MAX_ATTEMPTS
from ....logging_config import get_logger
from ....storage import agent_configs
from ....storage.steps import get_steps_for_subtask
from .agent_routing import EXTENSION_ATTEMPTS
from .retry_execution import execute_fix_attempt
from .retry_extensions import check_and_request_extension
from .retry_infra import handle_infrastructure_failures
from .retry_phases import determine_fix_prompt
from .steps import verify_steps_with_smoke_tests
from .worktree import check_worktree_health

logger = get_logger(__name__)


def run_self_healing_loop(
    task_id: str,
    subtask_id: str,
    subtask_short_id: str,
    subtask: dict[str, Any],
    steps: list[dict[str, Any]],
    project_path: str,
    project_id: str,
    agent_slug: str,
    agent_session_id: str | None,
    initial_response_content: str,
) -> tuple[bool, list[dict[str, Any]], int, int, int, str | None]:
    """Run self-healing retry loop until success or exhaustion.

    Returns:
        Tuple of (all_passed, step_results, self_fix_attempts, supervisor_guided_attempts,
                  extensions_granted, final_agent_session_id)
    """
    # Get configurable retry limits from project settings
    max_self_fix = agent_configs.get_max_self_fix_attempts(project_id)
    max_supervisor = agent_configs.get_max_supervisor_attempts(project_id)

    # Fall back to constants if not configured
    if max_self_fix == 0:
        max_self_fix = SELF_HEAL_MAX_ATTEMPTS
    if max_supervisor == 0:
        max_supervisor = SUPERVISOR_GUIDED_MAX_ATTEMPTS

    supervisor_guidance_text: str | None = None
    self_fix_attempts = 0
    supervisor_guided_attempts = 0
    total_max_attempts = max_self_fix + max_supervisor
    extensions_granted = 0
    all_passed = False
    step_results: list[dict[str, Any]] = []
    response_content = initial_response_content
    heal_attempt = 0

    while heal_attempt <= total_max_attempts:
        if heal_attempt > 0:
            steps = get_steps_for_subtask(subtask_id)

        if not check_worktree_health(project_path, task_id, project_id):
            step_results = [
                {
                    "step_number": 0,
                    "passed": False,
                    "output": "Worktree destroyed during execution",
                    "reason": "worktree_destroyed",
                    "returncode": -1,
                }
            ]
            all_passed = False
            break

        all_passed, step_results = verify_steps_with_smoke_tests(
            task_id, subtask_id, steps, project_path, project_id
        )

        if all_passed:
            break

        # Check for extension if attempts exhausted
        if heal_attempt >= total_max_attempts:
            approved, extensions_granted, ext_guidance = check_and_request_extension(
                task_id,
                subtask_id,
                subtask_short_id,
                steps,
                step_results,
                project_path,
                project_id,
                extensions_granted,
            )
            if not approved:
                break

            total_max_attempts += EXTENSION_ATTEMPTS
            if ext_guidance:
                supervisor_guidance_text = ext_guidance

        failed_steps = [r for r in step_results if not r["passed"]]

        # Auto-defect infrastructure failures
        failed_steps = handle_infrastructure_failures(
            failed_steps, subtask_id, task_id, project_id
        )
        if not failed_steps:
            steps = get_steps_for_subtask(subtask_id)
            heal_attempt += 1
            continue

        # Determine fix prompt based on current phase
        fix_prompt, supervisor_guidance_text = determine_fix_prompt(
            task_id,
            subtask,
            subtask_short_id,
            failed_steps,
            response_content,
            self_fix_attempts,
            supervisor_guided_attempts,
            supervisor_guidance_text,
            project_id,
        )

        # Update attempt counters
        if self_fix_attempts < max_self_fix:
            self_fix_attempts += 1
        else:
            supervisor_guided_attempts += 1

        # Escalate model during supervisor-guided phase
        model_override = ESCALATION_MODEL if self_fix_attempts >= max_self_fix else None

        # Execute agent fix and auto-commit
        response_content, agent_session_id = execute_fix_attempt(
            task_id,
            subtask_short_id,
            fix_prompt,
            agent_slug,
            project_path,
            project_id,
            agent_session_id,
            self_fix_attempts,
            supervisor_guided_attempts,
            heal_attempt,
            model_override=model_override,
        )

        heal_attempt += 1

    return (
        all_passed,
        step_results,
        self_fix_attempts,
        supervisor_guided_attempts,
        extensions_granted,
        agent_session_id,
    )
