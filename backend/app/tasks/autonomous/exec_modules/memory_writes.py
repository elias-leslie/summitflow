"""Post-execution memory writes for pipeline learning.

Saves execution insights, fix patterns, and task outcomes to the
Agent Hub memory system for cross-session learning.
"""

from __future__ import annotations

from typing import Any

from ....logging_config import get_logger
from ....services.agent_hub_client import get_sync_client

logger = get_logger(__name__)


def save_subtask_learning(
    task_id: str,
    subtask_short_id: str,
    subtask_type: str | None,
    project_id: str,
    passed: bool,
    self_fix_attempts: int,
    supervisor_guided_attempts: int,
    step_results: list[dict[str, Any]],
) -> None:
    """Save execution insights after subtask completes.

    - Passed with fixes → reference tier (gotchas, patterns)
    - Failed → reference tier (failure patterns for avoidance)
    """
    total_attempts = 1 + self_fix_attempts + supervisor_guided_attempts
    if passed and total_attempts == 1:
        # Clean pass, nothing interesting to learn
        return

    try:
        client = get_sync_client()
        type_tag = f" [{subtask_type}]" if subtask_type else ""

        if passed and total_attempts > 1:
            failed_steps = [r for r in step_results if not r.get("passed")]
            issues = "; ".join(
                r.get("reason", r.get("error", "unknown"))[:80]
                for r in failed_steps[:3]
            )
            content = (
                f"Subtask {subtask_short_id}{type_tag} required {total_attempts} attempts "
                f"({self_fix_attempts} self-fix, {supervisor_guided_attempts} guided). "
                f"Initial issues: {issues}"
            )
            client.save_learning(
                content,
                injection_tier="reference",
                confidence=70,
                context=f"task:{task_id} subtask:{subtask_short_id}",
                scope="project",
                scope_id=project_id,
            )
        elif not passed:
            failed_steps = [r for r in step_results if not r.get("passed")]
            issues = "; ".join(
                r.get("reason", r.get("error", "unknown"))[:80]
                for r in failed_steps[:3]
            )
            content = (
                f"Subtask {subtask_short_id}{type_tag} FAILED after {total_attempts} "
                f"attempts. Unresolved: {issues}"
            )
            client.save_learning(
                content,
                injection_tier="reference",
                confidence=60,
                context=f"task:{task_id} subtask:{subtask_short_id}",
                scope="project",
                scope_id=project_id,
            )
    except Exception as e:
        logger.debug("Memory write failed (non-blocking)", error=str(e))


def save_qa_fix_pattern(
    task_id: str,
    project_id: str,
    concern: str,
    fix_iteration: int,
) -> None:
    """Save QA fix pattern after a fixer resolves a reviewer concern."""
    try:
        client = get_sync_client()
        content = (
            f"QA fix pattern: concern '{concern[:120]}' resolved in "
            f"{fix_iteration} iteration(s). Task {task_id}."
        )
        client.save_learning(
            content,
            injection_tier="reference",
            confidence=75,
            context=f"task:{task_id} qa-fix",
            scope="project",
            scope_id=project_id,
        )
    except Exception as e:
        logger.debug("QA fix memory write failed (non-blocking)", error=str(e))


def rate_cited_memories(
    cited_uuids: list[str],
    rating: str = "helpful",
) -> None:
    """Rate cited memory episodes after successful task completion."""
    if not cited_uuids:
        return
    try:
        client = get_sync_client()
        for uuid in cited_uuids[:10]:  # Cap to avoid excessive API calls
            try:
                client.rate_episode(uuid, rating)
            except Exception:
                pass  # Individual rating failures are non-critical
    except Exception as e:
        logger.debug("Memory rating failed (non-blocking)", error=str(e))
