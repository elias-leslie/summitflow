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

from ...logging_config import get_logger
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
    """Get current escalation level based on attempt count."""
    if attempts < WORKER_ATTEMPTS:
        return "WORKER"
    elif attempts < MAX_FIX_ATTEMPTS:
        return "SUPERVISOR"
    else:
        return "HUMAN"


def escalate_to_human(
    conn: psycopg.Connection[Any],
    result_id: int,
) -> str | None:
    """Create a blocking bug task for manual review of an unfixable error."""
    check_result = qcr_store.get_check_result(conn, result_id)
    if not check_result:
        logger.error("check_result_not_found_for_escalation", result_id=result_id)
        return None

    # Skip if already escalated
    existing_task_id = check_result.get("escalation_task_id")
    if existing_task_id:
        logger.info("already_escalated", result_id=result_id, task_id=existing_task_id)
        return str(existing_task_id)

    check_type = check_result["check_type"]
    file_path = check_result.get("file_path", "unknown")
    line_number = check_result.get("line_number")
    error_message = check_result.get("error_message", "")[:200]
    check_name = check_result.get("check_name", "")

    location = f"{file_path}:{line_number}" if line_number else file_path
    title = f"Fix: {check_type} {check_name or 'error'} in {location}"

    description = f"""**Auto-fix failed after {MAX_FIX_ATTEMPTS} attempts.**

**Check type:** {check_type}
**File:** {file_path}
{f'**Line:** {line_number}' if line_number else ''}
{f'**Rule/Check:** {check_name}' if check_name else ''}

**Error message:**
```
{error_message}
```

**Quality check result ID:** {result_id}

This error could not be fixed automatically by the 3-2-1 escalation pipeline:
- 3 attempts with GEMINI_FLASH (worker level)
- 2 attempts with CLAUDE_SONNET + GEMINI_PRO (supervisor level)

Manual investigation required.
"""
    try:
        task = create_task(
            project_id=check_result["project_id"],
            title=title,
            description=description,
            priority=1,
            task_type="bug",
            complexity="STANDARD",
        )
        task_id: str = task["id"]
        qcr_store.mark_escalated(conn, result_id, task_id)
        conn.commit()
        logger.info("escalated_to_task", result_id=result_id, task_id=task_id)
        return task_id
    except Exception as e:
        logger.error("escalation_failed", result_id=result_id, error=str(e))
        return None


def determine_fix_outcome(
    conn: psycopg.Connection[Any],
    result_id: int,
    level: str,
    cost_usd: float,
) -> FixAttemptResult:
    """Determine outcome after a failed fix verification."""
    updated = qcr_store.get_check_result(conn, result_id)
    attempts = updated.get("fix_attempts", 0) if updated else 0

    if attempts >= MAX_FIX_ATTEMPTS:
        escalate_to_human(conn, result_id)
        return FixAttemptResult(outcome="escalated_human", cost_usd=cost_usd)
    if level == "WORKER" and attempts >= WORKER_ATTEMPTS:
        return FixAttemptResult(outcome="escalated_supervisor", cost_usd=cost_usd)

    return FixAttemptResult(outcome="failed", cost_usd=cost_usd)
