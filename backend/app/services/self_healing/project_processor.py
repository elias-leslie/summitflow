"""Project-level error processing for self-healing orchestration."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ...logging_config import get_logger
from .config import BUDGET_CAP_USD, CHECK_TYPE_PRIORITY

if TYPE_CHECKING:
    import psycopg

logger = get_logger(__name__)


def process_project(
    conn: psycopg.Connection[Any],
    project_id: str,
    unfixed_counts: dict[str, int],
    remaining_budget: int,
    cumulative_cost: float = 0.0,
) -> dict[str, Any]:
    """Process a single project, fixing errors in priority order.

    Args:
        conn: Database connection
        project_id: Project to process
        unfixed_counts: Dict of check_type → unfixed count
        remaining_budget: Max errors we can still process this run
        cumulative_cost: Current cumulative cost for budget tracking

    Returns:
        Results dict for this project including cumulative_cost_usd

    Raises:
        BudgetExceededError: If cumulative_cost exceeds BUDGET_CAP_USD
    """
    # Lazy import to avoid circular dependency
    # (fix_agent imports from self_healing for pattern memory)
    from ..quality_gate.fix_agent import fix_unfixed_errors

    project_results: dict[str, Any] = {
        "fixed": 0,
        "failed": 0,
        "escalated": 0,
        "by_check_type": {},
        "cumulative_cost_usd": cumulative_cost,
    }

    project_budget = min(remaining_budget, MAX_ERRORS_PER_PROJECT)

    # Process check types in priority order
    for check_type in CHECK_TYPE_PRIORITY:
        if check_type not in unfixed_counts:
            continue

        if project_budget <= 0:
            logger.debug(
                "project_budget_exhausted",
                project_id=project_id,
                check_type=check_type,
            )
            break

        logger.info(
            "fixing_check_type",
            project_id=project_id,
            check_type=check_type,
            unfixed=unfixed_counts[check_type],
            budget=project_budget,
        )

        # Call fix_unfixed_errors with budget tracking
        # BudgetExceededError will propagate up if limit is hit
        fix_results = fix_unfixed_errors(
            conn=conn,
            project_id=project_id,
            check_type=check_type,  # type: ignore[arg-type]
            limit=project_budget,
            budget_cap_usd=BUDGET_CAP_USD,
            cumulative_cost=project_results["cumulative_cost_usd"],
        )

        project_results["by_check_type"][check_type] = fix_results
        project_results["fixed"] += fix_results.get("fixed", 0)
        project_results["failed"] += fix_results.get("failed", 0)
        project_results["escalated"] += fix_results.get("escalated", 0)
        project_results["cumulative_cost_usd"] = fix_results.get(
            "cumulative_cost_usd", project_results["cumulative_cost_usd"]
        )

        project_budget -= (
            fix_results.get("fixed", 0)
            + fix_results.get("failed", 0)
            + fix_results.get("escalated", 0)
        )

    return project_results


# Import to avoid NameError
from .config import MAX_ERRORS_PER_PROJECT  # noqa: E402
