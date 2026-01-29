"""Fix agent for lint/type errors.

Uses 3-2-1 escalation pattern:
- WORKER (3 attempts): GEMINI_FLASH
- SUPERVISOR (2 attempts): CLAUDE_SONNET with different strategy
- HUMAN: Create blocking task for manual review

Integrates with pattern memory to:
- Retrieve similar successful fixes before attempting
- Store successful fix patterns for future retrieval
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import psycopg

from ...constants import GEMINI_FLASH
from ...logging_config import get_logger
from ...services.agent_hub_client import AgentType, get_agent
from ...storage import quality_check_results as qcr_store
from ...storage.projects import get_project_root_path
from .cost_estimator import estimate_cost_from_response
from .escalation import (
    MAX_FIX_ATTEMPTS,
    WORKER_ATTEMPTS,
    FixAttemptResult,
    escalate_to_human,
    get_escalation_level,
    get_supervisor_model,
)
from .fix_execution import apply_fix, read_file_content, verify_fix
from .fix_prompts import build_fix_prompt
from .pattern_memory_utils import get_similar_patterns, store_successful_pattern

logger = get_logger(__name__)

__all__ = ["fix_error", "escalate_to_human"]


def fix_lint_type_error(
    conn: psycopg.Connection[Any],
    result_id: int,
) -> FixAttemptResult:
    """Attempt to fix a lint/type error using 3-2-1 escalation.

    - WORKER (3 attempts): Uses GEMINI_FLASH
    - SUPERVISOR (2 attempts): Uses CLAUDE_SONNET with enhanced prompt
    - HUMAN: Returns escalated_human for task creation

    Args:
        conn: Database connection
        result_id: ID of the quality_check_result to fix

    Returns:
        FixAttemptResult with outcome and cost_usd for budget tracking
    """
    check_result = qcr_store.get_check_result(conn, result_id)
    if not check_result:
        logger.error("check_result_not_found", result_id=result_id)
        return FixAttemptResult(outcome="failed", cost_usd=0.0)

    # Only handle lint/type errors
    check_type = check_result["check_type"]
    if check_type not in ("ruff", "mypy", "biome", "tsc"):
        logger.warning("unsupported_check_type", check_type=check_type)
        return FixAttemptResult(outcome="failed", cost_usd=0.0)

    # Check if already fixed
    if check_result.get("fixed_at"):
        logger.info("already_fixed", result_id=result_id)
        return FixAttemptResult(outcome="fixed", cost_usd=0.0)

    # Check escalation level
    attempts = check_result.get("fix_attempts", 0)
    level = get_escalation_level(attempts)

    if level == "HUMAN":
        logger.info(
            "escalated_to_human",
            result_id=result_id,
            attempts=attempts,
        )
        # Create blocking task for manual review
        escalate_to_human(conn, result_id)
        return FixAttemptResult(outcome="escalated_human", cost_usd=0.0)

    # Get project path
    project_id = check_result["project_id"]
    root_path = get_project_root_path(project_id)
    if not root_path:
        logger.error("project_not_found", project_id=project_id)
        return FixAttemptResult(outcome="failed", cost_usd=0.0)
    project_path = Path(root_path)

    # Get file path
    file_rel_path = check_result.get("file_path")
    if not file_rel_path:
        logger.warning("no_file_path", result_id=result_id)
        return FixAttemptResult(outcome="failed", cost_usd=0.0)

    file_path = project_path / file_rel_path
    file_content = read_file_content(file_path)
    if not file_content:
        logger.warning("file_not_found", path=str(file_path))
        return FixAttemptResult(outcome="failed", cost_usd=0.0)

    # Record attempt
    qcr_store.record_fix_attempt(conn, result_id)

    # Retrieve similar patterns from memory
    error_message = check_result.get("error_message", "")
    check_name = check_result.get("check_name", "")
    similar_patterns = get_similar_patterns(check_type, check_name, error_message)

    # Build prompt - enhanced for SUPERVISOR level
    prompt = build_fix_prompt(check_result, file_content, project_path, similar_patterns)
    if level == "SUPERVISOR":
        prompt = f"""Previous fix attempts have failed. Try a different approach.

{prompt}

IMPORTANT: Previous attempts failed. Consider:
- Reading surrounding context more carefully
- The error might require structural changes, not just line fixes
- Check if imports or dependencies are missing
- Verify the fix actually addresses the root cause
"""

    # Select model based on escalation level
    provider: AgentType
    model: str
    if level == "WORKER":
        model = GEMINI_FLASH
        provider = "gemini"
    else:  # SUPERVISOR - dual model approach
        model, provider = get_supervisor_model(attempts)

    logger.info(
        "fix_attempt",
        result_id=result_id,
        escalation_level=level,
        attempt=attempts + 1,
        model=model,
    )

    # Track cost for budget enforcement
    cost_usd = 0.0

    try:
        agent = get_agent(provider, model=model)
        response = agent.generate(
            prompt=prompt,
            system="You are a code fix agent. Output only the fixed code, no explanations.",
            temperature=0.2 if level == "WORKER" else 0.3,
            purpose="quality_gate_fix",
        )
        new_content = response.content.strip()

        # Calculate cost from response
        cost_usd = estimate_cost_from_response(response)
        logger.debug("fix_attempt_cost", cost_usd=cost_usd, model=model)
    except Exception as e:
        logger.error("llm_failed", error=str(e))
        return FixAttemptResult(outcome="failed", cost_usd=cost_usd)

    # Check for cannot fix response
    if new_content.startswith("CANNOT_FIX:"):
        reason = new_content[11:].strip()
        logger.info("cannot_fix", result_id=result_id, reason=reason)
        return FixAttemptResult(outcome="failed", cost_usd=cost_usd)

    # Apply the fix
    if not apply_fix(file_path, new_content):
        return FixAttemptResult(outcome="failed", cost_usd=cost_usd)

    # Verify the fix worked
    if verify_fix(project_path, check_type, file_rel_path):
        qcr_store.mark_fixed(conn, result_id, fixed_by=model)
        logger.info("fix_successful", result_id=result_id, check_type=check_type, model=model)

        # Store successful fix pattern for future retrieval
        store_successful_pattern(
            check_type=check_type,
            check_name=check_name,
            error_message=error_message,
            file_path=file_rel_path,
            original_content=file_content,
            fixed_content=new_content,
        )

        return FixAttemptResult(outcome="fixed", cost_usd=cost_usd)
    else:
        logger.info("fix_did_not_pass", result_id=result_id)
        # Check if we should escalate
        updated = qcr_store.get_check_result(conn, result_id)
        if updated and updated.get("fix_attempts", 0) >= MAX_FIX_ATTEMPTS:
            # Create blocking task for manual review
            escalate_to_human(conn, result_id)
            return FixAttemptResult(outcome="escalated_human", cost_usd=cost_usd)
        elif level == "WORKER" and updated and updated.get("fix_attempts", 0) >= WORKER_ATTEMPTS:
            return FixAttemptResult(outcome="escalated_supervisor", cost_usd=cost_usd)
        return FixAttemptResult(outcome="failed", cost_usd=cost_usd)


def fix_unfixed_errors(
    conn: psycopg.Connection[Any],
    project_id: str,
    check_type: qcr_store.CheckType | None = None,
    limit: int = 10,
    budget_cap_usd: float | None = None,
    cumulative_cost: float = 0.0,
) -> dict[str, Any]:
    """Fix all unfixed lint/type errors for a project.

    Args:
        conn: Database connection
        project_id: Project ID
        check_type: Optional filter by check type
        limit: Maximum number of errors to attempt
        budget_cap_usd: Optional budget cap. If provided, stops when exceeded.
        cumulative_cost: Starting cumulative cost (for multi-project orchestration)

    Returns:
        Dict with counts: fixed, failed, escalated, cumulative_cost_usd

    Raises:
        BudgetExceededError: If cumulative_cost exceeds budget_cap_usd
    """
    from ...services.self_healing.orchestrator import BUDGET_CAP_USD, BudgetExceededError

    # Use default budget cap if not specified
    effective_budget = budget_cap_usd if budget_cap_usd is not None else BUDGET_CAP_USD

    results: dict[str, Any] = {
        "fixed": 0,
        "failed": 0,
        "escalated": 0,
        "cumulative_cost_usd": cumulative_cost,
    }

    # Get unfixed results
    unfixed = qcr_store.list_check_results(
        conn,
        project_id,
        check_type=check_type,
        unfixed_only=True,
        limit=limit,
    )

    # Filter to lint/type errors only
    lint_type_errors = [r for r in unfixed if r["check_type"] in ("ruff", "mypy", "biome", "tsc")]

    for result in lint_type_errors:
        # Check budget before each attempt
        if results["cumulative_cost_usd"] >= effective_budget:
            logger.warning(
                "budget_cap_reached",
                cumulative_cost=results["cumulative_cost_usd"],
                budget=effective_budget,
            )
            raise BudgetExceededError(results["cumulative_cost_usd"], effective_budget)

        fix_result = fix_lint_type_error(conn, result["id"])

        # Track cost
        results["cumulative_cost_usd"] += fix_result.cost_usd

        # Map outcomes
        if fix_result.outcome in ("escalated_supervisor", "escalated_human"):
            results["escalated"] += 1
        else:
            results[fix_result.outcome] += 1

    logger.info(
        "batch_fix_complete",
        project_id=project_id,
        fixed=results["fixed"],
        failed=results["failed"],
        escalated=results["escalated"],
        cumulative_cost_usd=results["cumulative_cost_usd"],
    )

    return results
