"""Escalation logic for fix agent.

Implements the 3-2-1 escalation pattern:
- WORKER (3 attempts): GEMINI_FLASH
- SUPERVISOR (2 attempts): CLAUDE_SONNET with different strategy
- HUMAN: Create blocking task for manual review
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

import psycopg

from ...constants import CLAUDE_SONNET, GEMINI_PRO
from ...logging_config import get_logger
from ...services.agent_hub_client import AgentType
from ...storage import quality_check_results as qcr_store
from ...storage.tasks.core import create_task

logger = get_logger(__name__)

FixResult = Literal["fixed", "failed", "escalated_supervisor", "escalated_human"]


@dataclass
class FixAttemptResult:
    """Result of a fix attempt including cost tracking.

    Used for budget enforcement in the self-healing orchestrator.
    """

    outcome: FixResult
    cost_usd: float = 0.0  # Cost incurred by this attempt


# 3-2-1 escalation thresholds
WORKER_ATTEMPTS = 3  # Attempts 1-3
SUPERVISOR_ATTEMPTS = 2  # Attempts 4-5
MAX_FIX_ATTEMPTS = WORKER_ATTEMPTS + SUPERVISOR_ATTEMPTS  # 5 total before HUMAN


def get_escalation_level(attempts: int) -> str:
    """Get current escalation level based on attempt count.

    Args:
        attempts: Number of fix attempts made

    Returns:
        'WORKER', 'SUPERVISOR', or 'HUMAN'
    """
    if attempts < WORKER_ATTEMPTS:
        return "WORKER"
    elif attempts < MAX_FIX_ATTEMPTS:
        return "SUPERVISOR"
    else:
        return "HUMAN"


def get_supervisor_model(attempts: int) -> tuple[str, AgentType]:
    """Get model for SUPERVISOR level based on attempt number.

    SUPERVISOR uses dual-model approach:
    - Attempt 4 (first SUPERVISOR): Claude Sonnet
    - Attempt 5 (second SUPERVISOR): Gemini Pro

    Args:
        attempts: Number of fix attempts made (0-indexed before this attempt)

    Returns:
        Tuple of (model_id, provider)
    """
    # Attempt 4 = first supervisor attempt (index 3)
    supervisor_attempt = attempts - WORKER_ATTEMPTS + 1
    if supervisor_attempt == 1:
        return CLAUDE_SONNET, "claude"
    else:
        return GEMINI_PRO, "gemini"


def escalate_to_human(
    conn: psycopg.Connection[Any],
    result_id: int,
    worktree_path: str | None = None,
) -> str | None:
    """Create a blocking bug task for manual review of an unfixable error.

    Called when fix attempts exceed MAX_FIX_ATTEMPTS (3 worker + 2 supervisor).
    Creates a P1 bug task linked to the check result.

    Per d5 decision: Worktree is preserved for human inspection. Do NOT delete
    the worktree on HUMAN escalation - include the path in the task description
    so the human can inspect git log, git diff, and attempt_history.json.

    Args:
        conn: Database connection
        result_id: ID of the quality_check_result to escalate
        worktree_path: Optional path to preserved worktree for inspection

    Returns:
        Created task ID, or None if escalation failed
    """
    check_result = qcr_store.get_check_result(conn, result_id)
    if not check_result:
        logger.error("check_result_not_found_for_escalation", result_id=result_id)
        return None

    # Skip if already escalated
    existing_task_id = check_result.get("escalation_task_id")
    if existing_task_id:
        logger.info(
            "already_escalated",
            result_id=result_id,
            task_id=existing_task_id,
        )
        return str(existing_task_id)

    check_type = check_result["check_type"]
    file_path = check_result.get("file_path", "unknown")
    line_number = check_result.get("line_number")
    error_message = check_result.get("error_message", "")[:200]  # Truncate for title
    check_name = check_result.get("check_name", "")

    # Build task title
    location = f"{file_path}:{line_number}" if line_number else file_path
    if check_name:
        title = f"Fix: {check_type} {check_name} in {location}"
    else:
        title = f"Fix: {check_type} error in {location}"

    # Build description with context
    description_parts = [
        f"**Auto-fix failed after {MAX_FIX_ATTEMPTS} attempts.**",
        "",
        f"**Check type:** {check_type}",
        f"**File:** {file_path}",
    ]
    if line_number:
        description_parts.append(f"**Line:** {line_number}")
    if check_name:
        description_parts.append(f"**Rule/Check:** {check_name}")
    description_parts.extend(
        [
            "",
            "**Error message:**",
            "```",
            error_message,
            "```",
            "",
            f"**Quality check result ID:** {result_id}",
            "",
            "This error could not be fixed automatically by the 3-2-1 escalation pipeline:",
            "- 3 attempts with GEMINI_FLASH (worker level)",
            "- 2 attempts with CLAUDE_SONNET + GEMINI_PRO (supervisor level)",
            "",
            "Manual investigation required.",
        ]
    )

    # Add worktree inspection info if available
    if worktree_path:
        description_parts.extend(
            [
                "",
                "## Worktree Preserved for Inspection",
                "",
                f"**Worktree path:** `{worktree_path}`",
                "",
                "The worktree has been preserved with all fix attempts. You can inspect:",
                "- `git log` - see all attempted commits",
                "- `git diff main...HEAD` - see current changes vs main",
                "- `.summitflow/attempt_history.json` - detailed history of all fix attempts",
                "",
                "**After inspection:** Delete the worktree with:",
                "```bash",
                f"rm -rf {worktree_path}",
                "```",
            ]
        )
    description = "\n".join(description_parts)

    try:
        task = create_task(
            project_id=check_result["project_id"],
            title=title,
            description=description,
            priority=1,  # P1 - high priority
            task_type="bug",
            complexity="STANDARD",
        )
        task_id: str = task["id"]

        # Link the check result to the task
        qcr_store.mark_escalated(conn, result_id, task_id)
        conn.commit()

        logger.info(
            "escalated_to_task",
            result_id=result_id,
            task_id=task_id,
            check_type=check_type,
            file_path=file_path,
        )

        return task_id

    except Exception as e:
        logger.error("escalation_failed", result_id=result_id, error=str(e))
        return None
