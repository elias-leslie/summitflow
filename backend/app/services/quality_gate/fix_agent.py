"""Fix agent for lint/type errors.

Uses 3-2-1 escalation pattern:
- WORKER (3 attempts): worker agent
- SUPERVISOR (2 attempts): supervisor agent with different strategy
- ESCALATE: Create blocking task for autonomous investigation
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import psycopg

from ...logging_config import get_logger
from ...storage import quality_check_results as qcr_store
from .escalation import FixAttemptResult, FixResult, escalate_to_supervisor, get_escalation_level
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


def _get_check_result_project_id(check_result: dict[str, object]) -> str:
    """Return the required project scope for a quality-check result."""
    return str(check_result["project_id"])


def _get_file_data(
    check_result: dict[str, object], result_id: int
) -> tuple[Path, Path, str, str] | None:
    """Return (project_path, file_path, file_rel_path, file_content) or None."""
    paths = get_project_file_path(check_result, result_id)
    if not paths:
        return None
    project_path, file_path = paths
    file_content = read_file_content(file_path)
    if not file_content:
        logger.warning("file_not_found", path=str(file_path))
        return None
    return project_path, file_path, str(check_result["file_path"]), file_content


def _build_prompt(
    check_result: dict[str, object], file_content: str, project_path: Path, level: str
) -> str:
    """Build the LLM prompt, enhancing it for supervisor level."""
    check_type = str(check_result["check_type"])
    check_name = str(check_result.get("check_name") or "")
    error_message = str(check_result.get("error_message") or "")
    project_id = _get_check_result_project_id(check_result)
    similar = get_similar_patterns(check_type, check_name, error_message, project_id)
    prompt = build_fix_prompt(check_result, file_content, project_path, similar)
    return enhance_prompt_for_supervisor(prompt) if level == "SUPERVISOR" else prompt


def _apply_and_verify(
    conn: psycopg.Connection[Any],
    result_id: int,
    check_result: dict[str, object],
    project_path: Path,
    file_path: Path,
    file_rel_path: str,
    file_content: str,
    new_content: str,
    agent_slug: str,
    level: str,
) -> FixResult:
    """Apply the fix to disk and run verification; return the outcome."""
    if not apply_fix(file_path, new_content):
        return "failed"
    project_id = _get_check_result_project_id(check_result)
    return verify_and_process_fix(
        conn, result_id, project_id, project_path,
        str(check_result["check_type"]), file_rel_path, agent_slug, level,
        str(check_result.get("check_name") or ""),
        str(check_result.get("error_message") or ""),
        file_content, new_content,
    )


def fix_lint_type_error(
    conn: psycopg.Connection[Any], result_id: int
) -> FixAttemptResult:
    """Attempt to fix a lint/type error using 3-2-1 escalation."""
    check_result = qcr_store.get_check_result(conn, result_id)
    validation_error = validate_check_result(check_result, result_id)
    if validation_error:
        outcome: FixResult = "fixed" if validation_error == "already_fixed" else "failed"
        return FixAttemptResult(outcome=outcome, cost_usd=0.0)
    assert check_result is not None

    attempts = int(check_result.get("fix_attempts") or 0)
    level = get_escalation_level(attempts)
    if level == "ESCALATE":
        logger.info("escalated_to_supervisor", result_id=result_id, attempts=attempts)
        escalate_to_supervisor(conn, result_id)
        return FixAttemptResult(outcome="escalated_pipeline", cost_usd=0.0)

    file_data = _get_file_data(check_result, result_id)
    if not file_data:
        return FixAttemptResult(outcome="failed", cost_usd=0.0)
    project_path, file_path, file_rel_path, file_content = file_data

    qcr_store.record_fix_attempt(conn, result_id)
    prompt = _build_prompt(check_result, file_content, project_path, level)
    agent_slug = select_agent(level)
    logger.info("fix_attempt", result_id=result_id, escalation_level=level,
                attempt=attempts + 1, agent_slug=agent_slug)
    try:
        new_content, cost_usd = execute_llm_fix(
            prompt, agent_slug, get_temperature(level), result_id
        )
    except Exception as e:
        logger.error("llm_failed", error=str(e))
        return FixAttemptResult(outcome="failed", cost_usd=0.0)

    if not new_content:
        logger.warning("empty_llm_response", result_id=result_id)
        return FixAttemptResult(outcome="failed", cost_usd=cost_usd)

    is_cannot_fix, reason = is_cannot_fix_response(new_content)
    if is_cannot_fix:
        logger.info("cannot_fix", result_id=result_id, reason=reason)
        return FixAttemptResult(outcome="failed", cost_usd=cost_usd)

    outcome = _apply_and_verify(
        conn, result_id, check_result, project_path, file_path,
        file_rel_path, file_content, new_content, agent_slug, level,
    )
    return FixAttemptResult(outcome=outcome, cost_usd=cost_usd)
