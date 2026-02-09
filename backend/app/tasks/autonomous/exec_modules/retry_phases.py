"""Phase management for retry loop (self-fix vs supervisor-guided)."""

from __future__ import annotations

from typing import Any

from ....constants import SELF_HEAL_MAX_ATTEMPTS, SUPERVISOR_GUIDED_MAX_ATTEMPTS
from ....logging_config import get_logger
from ..escalation import get_supervisor_guidance_sync
from .events import emit_log
from .prompts import build_fix_prompt

logger = get_logger(__name__)


def determine_fix_prompt(
    task_id: str,
    subtask: dict[str, Any],
    subtask_short_id: str,
    failed_steps: list[dict[str, Any]],
    response_content: str,
    self_fix_attempts: int,
    supervisor_guided_attempts: int,
    supervisor_guidance_text: str | None,
    project_id: str,
) -> tuple[str, str | None]:
    """Determine which fix prompt to use based on current phase.

    Returns:
        Tuple of (fix_prompt, updated_supervisor_guidance_text)
    """
    updated_guidance = supervisor_guidance_text
    failed_count = len(failed_steps)

    if self_fix_attempts < SELF_HEAL_MAX_ATTEMPTS:
        # Phase 1: Self-fix attempts
        emit_log(
            task_id,
            "warn",
            f"Verification failed ({failed_count} steps). "
            f"Self-heal attempt {self_fix_attempts + 1}/{SELF_HEAL_MAX_ATTEMPTS}",
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

            error_desc = "; ".join(
                f"Step {f.get('step_number')}: {f.get('reason', 'failed')}"
                for f in failed_steps
            )
            updated_guidance = get_supervisor_guidance_sync(
                task_id,
                subtask_short_id,
                error_desc,
                failed_steps,
                project_id=project_id,
            )

            if updated_guidance:
                emit_log(
                    task_id,
                    "info",
                    f"Supervisor guidance received ({len(updated_guidance)} chars)",
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

        emit_log(
            task_id,
            "warn",
            f"Verification failed ({failed_count} steps). "
            f"Supervisor-guided attempt {supervisor_guided_attempts + 1}/{SUPERVISOR_GUIDED_MAX_ATTEMPTS}",
            source="orchestrator",
            project_id=project_id,
        )

        fix_prompt = build_fix_prompt(
            subtask, failed_steps, response_content, updated_guidance
        )

    return fix_prompt, updated_guidance
