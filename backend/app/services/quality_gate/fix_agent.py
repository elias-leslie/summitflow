"""Fix agent for lint/type errors.

Uses 3-2-1 escalation pattern: WORKER (3) → SUPERVISOR (2) → HUMAN.
Integrates with pattern memory for retrieval and storage of fixes.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import psycopg

from ...logging_config import get_logger
from ...storage import quality_check_results as qcr_store
from ...storage.projects import get_project_root_path
from .escalation import (
    FixAttemptResult,
    determine_fix_outcome,
    escalate_to_human,
    get_escalation_level,
)
from .fix_execution import apply_fix, execute_agent_fix, read_file_content, verify_fix
from .fix_prompts import build_fix_prompt
from .pattern_memory_utils import get_similar_patterns, store_successful_pattern

logger = get_logger(__name__)


def fix_lint_type_error(conn: psycopg.Connection[Any], result_id: int) -> FixAttemptResult:
    """Attempt to fix a lint/type error using 3-2-1 escalation."""
    res = qcr_store.get_check_result(conn, result_id)
    if not res:
        logger.error("check_result_not_found", result_id=result_id)
        return FixAttemptResult("failed")
    if res.get("fixed_at"):
        logger.info("already_fixed", result_id=result_id)
        return FixAttemptResult("fixed")
    
    check_type, check_name = res["check_type"], res.get("check_name", "")
    if check_type not in ("ruff", "mypy", "biome", "tsc"):
        logger.warning("unsupported_check_type", check_type=check_type)
        return FixAttemptResult("failed")

    attempts = res.get("fix_attempts", 0)
    level = get_escalation_level(attempts)
    if level == "HUMAN":
        logger.info("escalated_to_human", result_id=result_id, attempts=attempts)
        escalate_to_human(conn, result_id)
        return FixAttemptResult("escalated_human")

    root = get_project_root_path(res["project_id"])
    file_rel = res.get("file_path")
    if not root or not file_rel:
        logger.error("project_or_file_not_found", result_id=result_id)
        return FixAttemptResult("failed")

    project_path, file_path = Path(root), Path(root) / file_rel
    file_content = read_file_content(file_path)
    if not file_content:
        logger.warning("file_not_found", path=str(file_path))
        return FixAttemptResult("failed")

    qcr_store.record_fix_attempt(conn, result_id)
    err_msg = res.get("error_message", "")
    patterns = get_similar_patterns(check_type, check_name, err_msg)
    prompt = build_fix_prompt(res, file_content, project_path, patterns, level == "SUPERVISOR")
    agent_slug = "worker" if level == "WORKER" else "supervisor"

    logger.info("fix_attempt", result_id=result_id, level=level, attempt=attempts + 1, agent=agent_slug)
    try:
        new_content, cost = execute_agent_fix(agent_slug, prompt, 0.2 if level == "WORKER" else 0.3)
    except Exception as e:
        logger.error("llm_failed", error=str(e))
        return FixAttemptResult("failed")

    if new_content.startswith("CANNOT_FIX:"):
        logger.info("cannot_fix", result_id=result_id, reason=new_content[11:].strip())
        return FixAttemptResult("failed", cost)

    if apply_fix(file_path, new_content) and verify_fix(project_path, check_type, file_rel):
        qcr_store.mark_fixed(conn, result_id, fixed_by=agent_slug)
        logger.info("fix_successful", result_id=result_id, check_type=check_type, agent=agent_slug)
        store_successful_pattern(check_type, check_name, err_msg, file_rel, file_content, new_content)
        return FixAttemptResult("fixed", cost)

    logger.info("fix_did_not_pass", result_id=result_id)
    return determine_fix_outcome(conn, result_id, level, cost)
