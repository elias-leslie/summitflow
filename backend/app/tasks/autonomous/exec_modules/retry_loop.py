"""Self-healing retry loop for subtask execution."""

from __future__ import annotations

from typing import Any

from ....constants import (
    SELF_HEAL_MAX_ATTEMPTS,
    SUPERVISOR_GUIDED_MAX_ATTEMPTS,
)
from ....logging_config import get_logger
from ....storage.steps import get_steps_for_subtask
from ..escalation import get_supervisor_guidance_sync
from .agent_execution import execute_agent_fix
from .agent_routing import EXTENSION_ATTEMPTS, detect_progress, request_extension
from .events import emit_log
from .git_ops import auto_commit, has_uncommitted_changes
from .prompts import build_fix_prompt
from .steps import (
    auto_defect_step,
    is_infrastructure_failure,
    verify_steps_with_smoke_tests,
)
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
    agent_session_id: str,
    initial_response_content: str,
) -> tuple[bool, list[dict[str, Any]], int, int, int, str]:
    """Run self-healing retry loop until success or exhaustion.

    Returns:
        Tuple of (all_passed, step_results, self_fix_attempts, supervisor_guided_attempts,
                  extensions_granted, final_agent_session_id)
    """
    supervisor_guidance_text: str | None = None
    self_fix_attempts = 0
    supervisor_guided_attempts = 0
    total_max_attempts = SELF_HEAL_MAX_ATTEMPTS + SUPERVISOR_GUIDED_MAX_ATTEMPTS
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

        # Success - break out of retry loop
        if all_passed:
            break

        # Exhausted all retry attempts — check for extension
        if heal_attempt >= total_max_attempts:
            progress = detect_progress(
                subtask_id,
                steps,
                step_results,
                project_path,
            )
            if not progress:
                break
            approved, ext_guidance = request_extension(
                task_id,
                subtask_short_id,
                step_results,
                progress,
                project_id=project_id,
                prior_extensions=extensions_granted,
            )
            if not approved:
                break
            extensions_granted += 1
            total_max_attempts += EXTENSION_ATTEMPTS
            if ext_guidance:
                supervisor_guidance_text = ext_guidance
            emit_log(
                task_id,
                "info",
                f"Supervisor granted extension #{extensions_granted} "
                f"({EXTENSION_ATTEMPTS} more attempts)",
                source="supervisor",
                project_id=project_id,
            )

        failed_steps = [r for r in step_results if not r["passed"]]
        failed_count = len(failed_steps)

        # Auto-defect infrastructure failures before retry
        infra_failures = [
            f
            for f in failed_steps
            if is_infrastructure_failure(
                f.get("output", ""), f.get("reason", ""), f.get("returncode", 1)
            )
        ]
        if infra_failures:
            for f in infra_failures:
                auto_defect_step(
                    subtask_id,
                    f["step_number"],
                    f.get("output", ""),
                    task_id,
                    project_id,
                )
            failed_steps = [f for f in failed_steps if f not in infra_failures]
            failed_count = len(failed_steps)
            if not failed_steps:
                steps = get_steps_for_subtask(subtask_id)
                heal_attempt += 1
                continue

        # Determine which phase we're in
        if self_fix_attempts < SELF_HEAL_MAX_ATTEMPTS:
            # Phase 1: Self-fix attempts
            self_fix_attempts += 1
            emit_log(
                task_id,
                "warn",
                f"Verification failed ({failed_count} steps). "
                f"Self-heal attempt {self_fix_attempts}/{SELF_HEAL_MAX_ATTEMPTS}",
                source="orchestrator",
                project_id=project_id,
            )

            fix_prompt = build_fix_prompt(
                subtask, failed_steps, response_content, supervisor_guidance=None
            )
        else:
            # Phase 2: Supervisor-guided attempts
            if supervisor_guided_attempts == 0:
                # First supervisor attempt - get guidance
                emit_log(
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
                    task_id,
                    subtask_short_id,
                    error_desc,
                    failed_steps,
                    project_id=project_id,
                )

                if supervisor_guidance_text:
                    emit_log(
                        task_id,
                        "info",
                        f"Supervisor guidance received ({len(supervisor_guidance_text)} chars)",
                        source="supervisor",
                        project_id=project_id,
                    )
                else:
                    emit_log(
                        task_id,
                        "warn",
                        "Supervisor guidance unavailable, continuing without",
                        source="orchestrator",
                        project_id=project_id,
                    )

            supervisor_guided_attempts += 1
            emit_log(
                task_id,
                "warn",
                f"Verification failed ({failed_count} steps). "
                f"Supervisor-guided attempt {supervisor_guided_attempts}/{SUPERVISOR_GUIDED_MAX_ATTEMPTS}",
                source="orchestrator",
                project_id=project_id,
            )

            fix_prompt = build_fix_prompt(
                subtask, failed_steps, response_content, supervisor_guidance_text
            )

        # Call agent with fix prompt, continuing existing session for context
        try:
            response, agent_session_id = execute_agent_fix(
                task_id,
                subtask_short_id,
                fix_prompt,
                agent_slug,
                project_path,
                project_id,
                agent_session_id,
            )
            response_content = response.content

            # Auto-commit fix attempt
            if has_uncommitted_changes(project_path):
                phase = (
                    "self-fix"
                    if self_fix_attempts <= SELF_HEAL_MAX_ATTEMPTS
                    else "guided"
                )
                attempt_num = (
                    self_fix_attempts if phase == "self-fix" else supervisor_guided_attempts
                )
                commit_msg = f"[{phase}] {subtask_short_id} attempt {attempt_num}"
                auto_commit(project_path, commit_msg)

        except Exception as fix_error:
            logger.warning(
                "Fix attempt failed",
                subtask_id=subtask_short_id,
                attempt=heal_attempt + 1,
                error=str(fix_error),
            )
            emit_log(
                task_id,
                "error",
                f"Fix attempt error: {str(fix_error)[:100]}",
                source="orchestrator",
                project_id=project_id,
            )
            # Continue to next attempt or exit loop

        heal_attempt += 1

    return (
        all_passed,
        step_results,
        self_fix_attempts,
        supervisor_guided_attempts,
        extensions_granted,
        agent_session_id,
    )
