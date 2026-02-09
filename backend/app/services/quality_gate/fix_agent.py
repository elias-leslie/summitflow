"""Fix agent for lint/type errors.

Uses 3-2-1 escalation pattern:
- WORKER (3 attempts): GEMINI_FLASH
- SUPERVISOR (2 attempts): CLAUDE_SONNET with different strategy
- HUMAN: Create blocking task for manual review
"""

from __future__ import annotations

from typing import Any

import psycopg

from ...logging_config import get_logger
from ...storage import quality_check_results as qcr_store
from .escalation import FixAttemptResult, FixResult, escalate_to_human, get_escalation_level
from .fix_batch import fix_unfixed_errors  # Re-export for backward compatibility
from .fix_execution import apply_fix, read_file_content
from .fix_llm import execute_llm_fix, is_cannot_fix_response
from .fix_prompts import build_fix_prompt
from .fix_strategies import enhance_prompt_for_supervisor, get_temperature, select_agent
from .fix_validation import get_project_file_path, validate_check_result
from .fix_verification import verify_and_process_fix
from .pattern_memory_utils import get_similar_patterns

logger = get_logger(__name__)

__all__ = ["fix_lint_type_error", "fix_unfixed_errors"]


def fix_lint_type_error(
    conn: psycopg.Connection[Any],
    result_id: int,
) -> FixAttemptResult:
    """Attempt to fix a lint/type error using 3-2-1 escalation.

    Args:
        conn: Database connection
        result_id: ID of the quality_check_result to fix

    Returns:
        FixAttemptResult with outcome and cost_usd for budget tracking
    """
    check_result = qcr_store.get_check_result(conn, result_id)

    # Validate preconditions
    validation_error = validate_check_result(check_result, result_id)
    if validation_error:
        outcome: FixResult = "fixed" if validation_error == "already_fixed" else "failed"
        return FixAttemptResult(outcome=outcome, cost_usd=0.0)

    assert check_result is not None

    # Check escalation level
    attempts = check_result.get("fix_attempts", 0)
    level = get_escalation_level(attempts)

    if level == "HUMAN":
        logger.info("escalated_to_human", result_id=result_id, attempts=attempts)
        escalate_to_human(conn, result_id)
        return FixAttemptResult(outcome="escalated_human", cost_usd=0.0)

    # Get paths and content
    paths = get_project_file_path(check_result, result_id)
    if not paths:
        return FixAttemptResult(outcome="failed", cost_usd=0.0)
    project_path, file_path = paths

    file_rel_path = check_result["file_path"]
    file_content = read_file_content(file_path)
    if not file_content:
        logger.warning("file_not_found", path=str(file_path))
        return FixAttemptResult(outcome="failed", cost_usd=0.0)

    qcr_store.record_fix_attempt(conn, result_id)

    # Build prompt
    check_type = check_result["check_type"]
    check_name = check_result.get("check_name", "")
    error_message = check_result.get("error_message", "")
    similar_patterns = get_similar_patterns(check_type, check_name, error_message)

    prompt = build_fix_prompt(check_result, file_content, project_path, similar_patterns)
    if level == "SUPERVISOR":
        prompt = enhance_prompt_for_supervisor(prompt)

    # Execute fix
    agent_slug = select_agent(level)
    logger.info(
        "fix_attempt",
        result_id=result_id,
        escalation_level=level,
        attempt=attempts + 1,
        agent_slug=agent_slug,
    )

    try:
        new_content, cost_usd = execute_llm_fix(
            prompt, agent_slug, get_temperature(level), result_id
        )
    except Exception as e:
        logger.error("llm_failed", error=str(e))
        return FixAttemptResult(outcome="failed", cost_usd=0.0)

    # Handle CANNOT_FIX
    is_cannot_fix, reason = is_cannot_fix_response(new_content)
    if is_cannot_fix:
        logger.info("cannot_fix", result_id=result_id, reason=reason)
        return FixAttemptResult(outcome="failed", cost_usd=cost_usd)

    # Apply and verify
    if not apply_fix(file_path, new_content):
        return FixAttemptResult(outcome="failed", cost_usd=cost_usd)

    outcome = verify_and_process_fix(
        conn,
        result_id,
        project_path,
        check_type,
        file_rel_path,
        agent_slug,
        level,
        check_name,
        error_message,
        file_content,
        new_content,
    )
    return FixAttemptResult(outcome=outcome, cost_usd=cost_usd)
