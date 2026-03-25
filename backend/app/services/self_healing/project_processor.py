"""Project-level error processing for self-healing orchestration."""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING, Any, TypedDict, cast

from ...logging_config import get_logger
from ...storage import quality_check_results as qcr_store
from .config import BUDGET_CAP_USD, CHECK_TYPE_PRIORITY, MAX_ERRORS_PER_PROJECT

if TYPE_CHECKING:
    import psycopg

logger = get_logger(__name__)

_CHECK_TYPE_PRIORITY = cast(Sequence[qcr_store.CheckType], CHECK_TYPE_PRIORITY)


class FixResults(TypedDict):
    """Results returned by fix_unfixed_errors for a single check type."""

    fixed: int
    failed: int
    escalated: int
    cumulative_cost_usd: float


class ProjectResults(TypedDict):
    """Aggregated results for a project across all check types."""

    fixed: int
    failed: int
    escalated: int
    by_check_type: dict[str, FixResults]
    cumulative_cost_usd: float


def _initialize_project_results(cumulative_cost: float) -> ProjectResults:
    """Create a fresh ProjectResults dict with zero counts.

    Args:
        cumulative_cost: Starting cumulative cost carried from prior runs.

    Returns:
        Initialized ProjectResults dict.
    """
    return ProjectResults(
        fixed=0,
        failed=0,
        escalated=0,
        by_check_type={},
        cumulative_cost_usd=cumulative_cost,
    )


def _update_project_results(
    project_results: ProjectResults,
    check_type: str,
    fix_results: FixResults,
) -> int:
    """Merge fix_results for one check_type into project_results.

    Args:
        project_results: Accumulator dict updated in place.
        check_type: The check type that was just processed.
        fix_results: Results returned by fix_unfixed_errors.

    Returns:
        Number of errors consumed from the budget this iteration.
    """
    project_results["by_check_type"][check_type] = fix_results
    project_results["fixed"] += fix_results.get("fixed", 0)
    project_results["failed"] += fix_results.get("failed", 0)
    project_results["escalated"] += fix_results.get("escalated", 0)
    project_results["cumulative_cost_usd"] = fix_results.get(
        "cumulative_cost_usd", project_results["cumulative_cost_usd"]
    )
    return (
        fix_results.get("fixed", 0)
        + fix_results.get("failed", 0)
        + fix_results.get("escalated", 0)
    )


def _fix_check_type(
    conn: psycopg.Connection[Any],
    project_id: str,
    check_type: qcr_store.CheckType,
    unfixed_count: int,
    project_budget: int,
    cumulative_cost_usd: float,
) -> FixResults:
    """Invoke fix_unfixed_errors for a single check type.

    Args:
        conn: Database connection.
        project_id: Project being processed.
        check_type: The check type to fix.
        unfixed_count: Number of unfixed errors of this type (for logging).
        project_budget: Remaining error budget for this project.
        cumulative_cost_usd: Current cumulative cost for budget tracking.

    Returns:
        FixResults with counts and updated cumulative cost.

    Raises:
        BudgetExceededError: If cumulative_cost exceeds BUDGET_CAP_USD.
    """
    # Lazy import to avoid circular dependency
    # (fix_agent imports from self_healing for pattern memory)
    from ..quality_gate.fix_agent import fix_unfixed_errors

    logger.info(
        "fixing_check_type",
        project_id=project_id,
        check_type=check_type,
        unfixed=unfixed_count,
        budget=project_budget,
    )
    raw = fix_unfixed_errors(
        conn=conn,
        project_id=project_id,
        check_type=check_type,
        limit=project_budget,
        budget_cap_usd=BUDGET_CAP_USD,
        cumulative_cost=cumulative_cost_usd,
    )
    return cast(FixResults, raw)


def process_project(
    conn: psycopg.Connection[Any],
    project_id: str,
    unfixed_counts: dict[str, int],
    remaining_budget: int,
    cumulative_cost: float = 0.0,
    max_errors_per_project: int | None = None,
) -> ProjectResults:
    """Process a single project, fixing errors in priority order.

    Raises BudgetExceededError if cumulative_cost exceeds BUDGET_CAP_USD.
    """
    effective_max = max_errors_per_project if max_errors_per_project is not None else MAX_ERRORS_PER_PROJECT
    project_results = _initialize_project_results(cumulative_cost)
    project_budget = min(remaining_budget, effective_max)

    # Process check types in priority order
    for check_type in _CHECK_TYPE_PRIORITY:
        if check_type not in unfixed_counts:
            continue

        if project_budget <= 0:
            logger.debug(
                "project_budget_exhausted",
                project_id=project_id,
                check_type=check_type,
            )
            break

        fix_results = _fix_check_type(
            conn=conn,
            project_id=project_id,
            check_type=check_type,
            unfixed_count=unfixed_counts[check_type],
            project_budget=project_budget,
            cumulative_cost_usd=project_results["cumulative_cost_usd"],
        )
        project_budget -= _update_project_results(project_results, check_type, fix_results)

    return project_results
