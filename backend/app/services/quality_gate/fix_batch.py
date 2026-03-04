"""Batch fix processing for multiple errors.

Handles batch fixing with budget tracking and error aggregation.
"""

from __future__ import annotations

from typing import Any

import psycopg

from ...logging_config import get_logger
from ...storage import quality_check_results as qcr_store
from .fix_validation import filter_lint_type_errors

logger = get_logger(__name__)


def check_budget(cumulative_cost: float, budget: float) -> None:
    """Check if budget has been exceeded.

    Args:
        cumulative_cost: Current cumulative cost
        budget: Budget cap

    Raises:
        BudgetExceededError: If cumulative_cost >= budget
    """
    from ...services.self_healing.orchestrator import BudgetExceededError

    if cumulative_cost >= budget:
        logger.warning("budget_cap_reached", cumulative_cost=cumulative_cost, budget=budget)
        raise BudgetExceededError(cumulative_cost, budget)


def update_results_from_fix(
    results: dict[str, Any],
    outcome: str,
    cost: float,
) -> None:
    """Update results dictionary from fix outcome.

    Args:
        results: Results dictionary to update
        outcome: Fix outcome
        cost: Cost of fix attempt
    """
    results["cumulative_cost_usd"] += cost

    if outcome in ("escalated_supervisor", "escalated_pipeline"):
        results["escalated"] += 1
    else:
        results[outcome] += 1


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
        budget_cap_usd: Optional budget cap
        cumulative_cost: Starting cumulative cost

    Returns:
        Dict with counts: fixed, failed, escalated, cumulative_cost_usd

    Raises:
        BudgetExceededError: If cumulative_cost exceeds budget_cap_usd
    """
    # Import here to avoid circular dependency
    from ...services.self_healing.orchestrator import BUDGET_CAP_USD
    from . import fix_agent

    effective_budget = budget_cap_usd if budget_cap_usd is not None else BUDGET_CAP_USD
    results: dict[str, Any] = {
        "fixed": 0,
        "failed": 0,
        "escalated": 0,
        "cumulative_cost_usd": cumulative_cost,
    }

    unfixed = qcr_store.list_check_results(
        conn, project_id, check_type=check_type, unfixed_only=True, limit=limit
    )
    lint_type_errors = filter_lint_type_errors(unfixed)

    for result in lint_type_errors:
        check_budget(results["cumulative_cost_usd"], effective_budget)

        fix_result = fix_agent.fix_lint_type_error(conn, result["id"])
        update_results_from_fix(results, fix_result.outcome, fix_result.cost_usd)

    logger.info(
        "batch_fix_complete",
        project_id=project_id,
        fixed=results["fixed"],
        failed=results["failed"],
        escalated=results["escalated"],
        cumulative_cost_usd=results["cumulative_cost_usd"],
    )

    return results
