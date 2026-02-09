"""Agent execution and commit handling for retry loop."""

from __future__ import annotations

from ....constants import SELF_HEAL_MAX_ATTEMPTS
from ....logging_config import get_logger
from .agent_execution import execute_agent_fix
from .events import emit_log
from .git_ops import auto_commit, has_uncommitted_changes

logger = get_logger(__name__)


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
        )
        response_content = response.content

        # Auto-commit fix attempt
        if has_uncommitted_changes(project_path):
            phase = "self-fix" if self_fix_attempts <= SELF_HEAL_MAX_ATTEMPTS else "guided"
            attempt_num = self_fix_attempts if phase == "self-fix" else supervisor_guided_attempts
            commit_msg = f"[{phase}] {subtask_short_id} attempt {attempt_num}"
            auto_commit(project_path, commit_msg)

        return response_content, agent_session_id

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
        return "", agent_session_id
