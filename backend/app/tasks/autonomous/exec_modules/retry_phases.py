"""Phase management for retry loop (self-fix vs supervisor-guided)."""

from __future__ import annotations

from typing import Any

from ....constants import SELF_HEAL_MAX_ATTEMPTS, SUPERVISOR_GUIDED_MAX_ATTEMPTS
from ....logging_config import get_logger
from ..escalation import get_supervisor_guidance_sync
from .events import emit_log
from .prompts import build_fix_prompt

logger = get_logger(__name__)


def _build_error_description(failed_steps: list[dict[str, Any]]) -> str:
    """Build a human-readable error description from failed steps."""
    return "; ".join(
        f"Step {f.get('step_number')}: {f.get('reason', 'failed')}"
        for f in failed_steps
    )


def _fetch_supervisor_guidance(
    task_id: str,
    subtask_short_id: str,
    failed_steps: list[dict[str, Any]],
    project_id: str,
) -> str | None:
    """Request supervisor guidance and emit result logs."""
    emit_log(
        task_id,
        "warn",
        "Self-fix exhausted. Requesting supervisor guidance...",
        source="orchestrator",
        project_id=project_id,
    )
    error_desc = _build_error_description(failed_steps)
    guidance = get_supervisor_guidance_sync(
        task_id,
        subtask_short_id,
        error_desc,
        failed_steps,
        project_id=project_id,
    )
    if guidance:
        emit_log(
            task_id,
            "info",
            f"Supervisor guidance received ({len(guidance)} chars)",
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
    return guidance


def _handle_self_fix_phase(
    task_id: str,
    subtask: dict[str, Any],
    failed_steps: list[dict[str, Any]],
    response_content: str,
    self_fix_attempts: int,
    project_id: str,
) -> tuple[str, str | None]:
    """Handle Phase 1: self-fix attempt. Returns (fix_prompt, guidance)."""
    failed_count = len(failed_steps)
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
    return fix_prompt, None


def _handle_supervisor_phase(
    task_id: str,
    subtask: dict[str, Any],
    subtask_short_id: str,
    failed_steps: list[dict[str, Any]],
    response_content: str,
    supervisor_guided_attempts: int,
    supervisor_guidance_text: str | None,
    project_id: str,
) -> tuple[str, str | None]:
    """Handle Phase 2: supervisor-guided attempt. Returns (fix_prompt, updated_guidance)."""
    updated_guidance = supervisor_guidance_text
    if supervisor_guided_attempts == 0:
        updated_guidance = _fetch_supervisor_guidance(
            task_id, subtask_short_id, failed_steps, project_id
        )
    failed_count = len(failed_steps)
    emit_log(
        task_id,
        "warn",
        f"Verification failed ({failed_count} steps). "
        f"Supervisor-guided attempt {supervisor_guided_attempts + 1}/{SUPERVISOR_GUIDED_MAX_ATTEMPTS}",
        source="orchestrator",
        project_id=project_id,
    )
    fix_prompt = build_fix_prompt(subtask, failed_steps, response_content, updated_guidance)
    return fix_prompt, updated_guidance


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
    if self_fix_attempts < SELF_HEAL_MAX_ATTEMPTS:
        fix_prompt, _ = _handle_self_fix_phase(
            task_id, subtask, failed_steps, response_content, self_fix_attempts, project_id
        )
        return fix_prompt, supervisor_guidance_text

    fix_prompt, updated_guidance = _handle_supervisor_phase(
        task_id, subtask, subtask_short_id, failed_steps, response_content,
        supervisor_guided_attempts, supervisor_guidance_text, project_id,
    )
    return fix_prompt, updated_guidance
