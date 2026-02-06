"""Orchestration for batch fixing quality gate errors."""

from __future__ import annotations

from typing import Any

import psycopg

from ...logging_config import get_logger
from ...storage import quality_check_results as qcr_store
from .fix_agent import fix_lint_type_error

logger = get_logger(__name__)


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
