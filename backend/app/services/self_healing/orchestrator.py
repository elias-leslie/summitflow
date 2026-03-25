"""Self-healing orchestration service for automated fix triggering.

Polls quality gate for unfixed errors and triggers fix agents automatically.
Respects check type priority: ruff → types → pytest (lint before type before test).

Implements 3-2-1 escalation through existing fix_agent infrastructure.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, TypedDict, cast

from ...logging_config import get_logger
from .config import (
    BUDGET_CAP_USD,
    CHECK_TYPE_PRIORITY,
    MAX_ERRORS_PER_PROJECT,
    MAX_ERRORS_PER_RUN,
)
from .exceptions import BudgetExceededError
from .project_processor import ProjectResults, process_project
from .project_scanner import get_projects_with_unfixed_errors

if TYPE_CHECKING:
    import psycopg

logger = get_logger(__name__)

# Re-export for backward compatibility
__all__ = [
    "BUDGET_CAP_USD",
    "CHECK_TYPE_PRIORITY",
    "MAX_ERRORS_PER_PROJECT",
    "MAX_ERRORS_PER_RUN",
    "BudgetExceededError",
    "SelfHealingOrchestrator",
    "poll_and_fix_all",
]

ProjectData = ProjectResults
ByCheckType = dict[str, dict[str, int]]


class OrchestrateResult(TypedDict, total=False):
    """Result of poll_and_fix / convenience of poll_and_fix_all."""

    projects_processed: int
    total_fixed: int
    total_failed: int
    total_escalated: int
    cumulative_cost_usd: float
    budget_exceeded: bool
    by_check_type: ByCheckType
    by_project: dict[str, ProjectData]


def _aggregate_check_types(by_project: dict[str, ProjectData]) -> ByCheckType:
    """Aggregate check-type counts across all projects."""
    by_check: ByCheckType = {}
    for pr_data in by_project.values():
        for check_type, counts in cast(ByCheckType, pr_data.get("by_check_type", {})).items():
            if check_type not in by_check:
                by_check[check_type] = {"fixed": 0, "failed": 0, "escalated": 0}
            for key in ("fixed", "failed", "escalated"):
                by_check[check_type][key] += counts.get(key, 0)
    return by_check


def _process_project_into_results(
    conn: psycopg.Connection[Any],
    results: OrchestrateResult,
    project_id: str,
    unfixed_counts: dict[str, int],
    total_processed: int,
    max_errors_per_run: int,
    max_errors_per_project: int,
) -> tuple[int, bool]:
    """Process one project, update results in-place. Returns (total_processed, budget_exceeded)."""
    try:
        pr = process_project(
            conn=conn, project_id=project_id, unfixed_counts=unfixed_counts,
            remaining_budget=max_errors_per_run - total_processed,
            cumulative_cost=results["cumulative_cost_usd"],
            max_errors_per_project=max_errors_per_project,
        )
        results["projects_processed"] += 1
        results["total_fixed"] += pr["fixed"]
        results["total_failed"] += pr["failed"]
        results["total_escalated"] += pr["escalated"]
        results["by_project"][project_id] = pr
        results["cumulative_cost_usd"] = pr.get("cumulative_cost_usd", results["cumulative_cost_usd"])
        return total_processed + pr["fixed"] + pr["failed"] + pr["escalated"], False
    except BudgetExceededError as e:
        logger.warning("orchestrator_budget_exceeded", cumulative_cost=e.cumulative_cost, budget=e.budget, project_id=project_id)
        results["budget_exceeded"] = True
        results["cumulative_cost_usd"] = e.cumulative_cost
        return total_processed, True


class SelfHealingOrchestrator:
    """Orchestrates automated fix triggering for quality gate failures.

    Stateless — all state lives in the database via quality_check_results.
    Priority: ruff → types → pytest.  Escalation: 3-2-1 via fix_agent.
    """

    def __init__(
        self,
        conn: psycopg.Connection[Any],
        max_errors_per_run: int = MAX_ERRORS_PER_RUN,
        max_errors_per_project: int = MAX_ERRORS_PER_PROJECT,
    ) -> None:
        self.conn = conn
        self.max_errors_per_run = max_errors_per_run
        self.max_errors_per_project = max_errors_per_project

    def get_health_summary(self) -> dict[str, object]:
        """Return health summary so callers can decide whether to run."""
        projects = get_projects_with_unfixed_errors(self.conn)
        total_unfixed = sum(sum(counts.values()) for counts in projects.values())
        return {
            "should_run": total_unfixed > 0,
            "total_unfixed": total_unfixed,
            "projects_needing_fixes": len(projects),
            "by_project": {pid: sum(counts.values()) for pid, counts in projects.items()},
        }

    def poll_and_fix(self) -> OrchestrateResult:
        """Poll quality gate and trigger fix agents for unfixed errors."""
        logger.info("orchestrator_poll_started")

        results = OrchestrateResult(
            projects_processed=0, total_fixed=0, total_failed=0, total_escalated=0,
            cumulative_cost_usd=0.0, budget_exceeded=False, by_check_type={}, by_project={},
        )
        total_processed = 0

        projects = get_projects_with_unfixed_errors(self.conn)
        if not projects:
            logger.debug("no_projects_with_unfixed_errors")
            return results

        logger.info("projects_with_errors", count=len(projects))

        for project_id, unfixed_counts in projects.items():
            if total_processed >= self.max_errors_per_run:
                logger.info("max_errors_reached", processed=total_processed, max=self.max_errors_per_run)
                break
            total_processed, exceeded = _process_project_into_results(
                self.conn, results, project_id, unfixed_counts,
                total_processed, self.max_errors_per_run, self.max_errors_per_project,
            )
            if exceeded:
                break

        results["by_check_type"] = _aggregate_check_types(results["by_project"])

        logger.info(
            "orchestrator_poll_complete",
            projects=results["projects_processed"], fixed=results["total_fixed"],
            failed=results["total_failed"], escalated=results["total_escalated"],
            cost=results["cumulative_cost_usd"], budget_exceeded=results["budget_exceeded"],
        )
        return results


def poll_and_fix_all(conn: psycopg.Connection[Any], max_errors: int = MAX_ERRORS_PER_RUN) -> OrchestrateResult:
    """Convenience function for scheduled workflow task."""
    return SelfHealingOrchestrator(conn, max_errors_per_run=max_errors).poll_and_fix()
