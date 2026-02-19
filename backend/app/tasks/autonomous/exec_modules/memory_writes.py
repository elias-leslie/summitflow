"""Post-execution memory writes for pipeline learning.

Saves execution insights, fix patterns, and task outcomes to the
Agent Hub memory system for cross-session learning.
"""

from __future__ import annotations

import contextlib
from typing import Any

from ....logging_config import get_logger
from ....services.agent_hub_client import get_sync_client

logger = get_logger(__name__)

_TIER = "reference"
_SCOPE = "project"


def _issues(step_results: list[dict[str, Any]]) -> str:
    failed = [r for r in step_results if not r.get("passed")]
    return "; ".join(
        r.get("reason", r.get("error", "unknown"))[:80] for r in failed[:3]
    )


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
        return  # Clean pass, nothing interesting to learn
    try:
        client = get_sync_client()
        tag = f" [{subtask_type}]" if subtask_type else ""
        ctx = f"task:{task_id} subtask:{subtask_short_id}"
        if passed:
            content = (
                f"Subtask {subtask_short_id}{tag} required {total_attempts} attempts "
                f"({self_fix_attempts} self-fix, {supervisor_guided_attempts} guided). "
                f"Initial issues: {_issues(step_results)}"
            )
            client.save_learning(content, injection_tier=_TIER, confidence=70,
                                 context=ctx, scope=_SCOPE, scope_id=project_id)
        else:
            content = (
                f"Subtask {subtask_short_id}{tag} FAILED after {total_attempts} "
                f"attempts. Unresolved: {_issues(step_results)}"
            )
            client.save_learning(content, injection_tier=_TIER, confidence=60,
                                 context=ctx, scope=_SCOPE, scope_id=project_id)
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
        client.save_learning(content, injection_tier=_TIER, confidence=75,
                             context=f"task:{task_id} qa-fix",
                             scope=_SCOPE, scope_id=project_id)
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
            with contextlib.suppress(Exception):
                client.rate_episode(uuid, rating)
    except Exception as e:
        logger.debug("Memory rating failed (non-blocking)", error=str(e))
