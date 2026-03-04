"""Fix verification and post-fix processing.

Handles verification, pattern storage, and escalation decisions.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import psycopg

from ...logging_config import get_logger
from ...storage import quality_check_results as qcr_store
from .escalation import MAX_FIX_ATTEMPTS, WORKER_ATTEMPTS, FixResult, escalate_to_supervisor
from .fix_execution import verify_fix
from .pattern_memory_utils import store_successful_pattern

logger = get_logger(__name__)


def process_successful_fix(
    conn: psycopg.Connection[Any],
    result_id: int,
    agent_slug: str,
    check_type: str,
    check_name: str,
    error_message: str,
    file_rel_path: str,
    original_content: str,
    fixed_content: str,
) -> None:
    """Process a successful fix.

    Marks result as fixed and stores pattern for future use.

    Args:
        conn: Database connection
        result_id: Result ID
        agent_slug: Agent that fixed it
        check_type: Check type
        check_name: Check name
        error_message: Original error message
        file_rel_path: Relative file path
        original_content: Original file content
        fixed_content: Fixed file content
    """
    qcr_store.mark_fixed(conn, result_id, fixed_by=agent_slug)
    logger.info("fix_successful", result_id=result_id, check_type=check_type, agent_slug=agent_slug)

    store_successful_pattern(
        check_type=check_type,
        check_name=check_name,
        error_message=error_message,
        file_path=file_rel_path,
        original_content=original_content,
        fixed_content=fixed_content,
    )


def get_escalation_outcome(
    conn: psycopg.Connection[Any],
    result_id: int,
    escalation_level: str,
) -> FixResult:
    """Determine escalation outcome after failed fix.

    Args:
        conn: Database connection
        result_id: Result ID
        escalation_level: Current escalation level

    Returns:
        Outcome string: 'escalated_pipeline', 'escalated_supervisor', or 'failed'
    """
    updated = qcr_store.get_check_result(conn, result_id)
    if not updated:
        return "failed"

    attempts = updated.get("fix_attempts", 0)
    if attempts >= MAX_FIX_ATTEMPTS:
        escalate_to_supervisor(conn, result_id)
        return "escalated_pipeline"
    elif escalation_level == "WORKER" and attempts >= WORKER_ATTEMPTS:
        return "escalated_supervisor"
    return "failed"


def verify_and_process_fix(
    conn: psycopg.Connection[Any],
    result_id: int,
    project_path: Path,
    check_type: str,
    file_rel_path: str,
    agent_slug: str,
    escalation_level: str,
    check_name: str,
    error_message: str,
    original_content: str,
    fixed_content: str,
) -> FixResult:
    """Verify fix and process result.

    Args:
        conn: Database connection
        result_id: Result ID
        project_path: Project path
        check_type: Check type
        file_rel_path: Relative file path
        agent_slug: Agent slug
        escalation_level: Escalation level
        check_name: Check name
        error_message: Error message
        original_content: Original content
        fixed_content: Fixed content

    Returns:
        Outcome string: 'fixed', 'escalated_pipeline', 'escalated_supervisor', or 'failed'
    """
    if verify_fix(project_path, check_type, file_rel_path):
        process_successful_fix(
            conn,
            result_id,
            agent_slug,
            check_type,
            check_name,
            error_message,
            file_rel_path,
            original_content,
            fixed_content,
        )
        return "fixed"

    logger.info("fix_did_not_pass", result_id=result_id)
    return get_escalation_outcome(conn, result_id, escalation_level)
