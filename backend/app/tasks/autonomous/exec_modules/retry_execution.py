"""Agent execution and commit handling for retry loop."""

from __future__ import annotations

from ....constants import SELF_HEAL_MAX_ATTEMPTS
from ....logging_config import get_logger
from .agent_execution import execute_agent_fix
from .events import emit_log
from .git_ops import has_uncommitted_changes, smart_commit

logger = get_logger(__name__)


def _commit_fix_attempt(
    task_id: str,
    project_path: str,
    subtask_short_id: str,
    self_fix_attempts: int,
    supervisor_guided_attempts: int,
) -> None:
    """Auto-commit changes from a fix attempt if any uncommitted changes exist."""
    if has_uncommitted_changes(project_path):
        phase = "self-fix" if self_fix_attempts <= SELF_HEAL_MAX_ATTEMPTS else "guided"
        attempt_num = self_fix_attempts if phase == "self-fix" else supervisor_guided_attempts
        commit_msg = f"fix: {subtask_short_id} {phase} attempt {attempt_num}"
        smart_commit(
            project_path,
            commit_msg,
            task_id=task_id,
            push=True,
            skip_checks=True,
        )


def _handle_fix_error(
    task_id: str,
    subtask_short_id: str,
    project_id: str,
    heal_attempt: int,
    fix_error: Exception,
    agent_session_id: str | None,
) -> tuple[str, str | None]:
    """Log and emit error from a failed fix attempt, then return empty result."""
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
    return "", agent_session_id


def execute_fix_attempt(
    task_id: str,
    subtask_short_id: str,
    fix_prompt: str,
    agent_slug: str,
    project_path: str,
    project_id: str,
    agent_session_id: str | None,
    self_fix_attempts: int,
    supervisor_guided_attempts: int,
    heal_attempt: int,
    model_override: str | None = None,
) -> tuple[str, str | None]:
    """Execute agent fix attempt and auto-commit if changes detected.

    Returns:
        Tuple of (response_content, agent_session_id)
    """
    try:
        response, agent_session_id = execute_agent_fix(
            task_id,
            subtask_short_id,
            fix_prompt,
            agent_slug,
            project_path,
            project_id,
            agent_session_id,
            model_override=model_override,
        )
        response_content = response.content
        _commit_fix_attempt(
            task_id,
            project_path,
            subtask_short_id,
            self_fix_attempts,
            supervisor_guided_attempts,
        )
        return response_content, agent_session_id

    except Exception as fix_error:
        return _handle_fix_error(
            task_id,
            subtask_short_id,
            project_id,
            heal_attempt,
            fix_error,
            agent_session_id,
        )
