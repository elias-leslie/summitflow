"""Self-healing orchestration service for automated fix triggering.

Polls quality gate for unfixed errors and triggers fix agents automatically.
Respects check type priority: ruff → types → pytest (lint before type before test).

Implements 3-2-1 escalation through existing fix_agent infrastructure.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ...logging_config import get_logger
from .config import (
    BUDGET_CAP_USD,
    CHECK_TYPE_PRIORITY,
    MAX_ERRORS_PER_PROJECT,
    MAX_ERRORS_PER_RUN,
)
from .exceptions import BudgetExceededError
from .project_processor import process_project
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


class SelfHealingOrchestrator:
    """Orchestrates automated fix triggering for quality gate failures.

    Workflow:
    1. Poll all projects for unfixed quality gate errors
    2. Prioritize: ruff → types → pytest
    3. Trigger fix_agent with 3-2-1 escalation
    4. Track results and return summary

    The orchestrator itself is stateless - all state is in the database
    via quality_check_results.
    """

    def __init__(
        self,
        conn: psycopg.Connection[Any],
        max_errors_per_run: int = MAX_ERRORS_PER_RUN,
        max_errors_per_project: int = MAX_ERRORS_PER_PROJECT,
    ):
        """Initialize the orchestrator."""
        self.conn = conn
        self.max_errors_per_run = max_errors_per_run
        self.max_errors_per_project = max_errors_per_project

    def get_health_summary(self) -> dict[str, Any]:
        """Get overall health summary for the orchestrator to decide if it should run."""
        projects = get_projects_with_unfixed_errors(self.conn)
        total_unfixed = sum(sum(counts.values()) for counts in projects.values())
        return {
            "should_run": total_unfixed > 0,
            "total_unfixed": total_unfixed,
            "projects_needing_fixes": len(projects),
            "by_project": {pid: sum(counts.values()) for pid, counts in projects.items()},
        }

    def poll_and_fix(self) -> dict[str, Any]:
        """Poll quality gate and trigger fix agents for unfixed errors."""
        logger.info("orchestrator_poll_started")

        results: dict[str, Any] = {
            "projects_processed": 0,
            "total_fixed": 0,
            "total_failed": 0,
            "total_escalated": 0,
            "cumulative_cost_usd": 0.0,
            "budget_exceeded": False,
            "by_check_type": {},
            "by_project": {},
        }
        total_processed = 0
        cumulative_cost = 0.0

        # Get all projects with unfixed errors
        projects = get_projects_with_unfixed_errors(self.conn)
        if not projects:
            logger.debug("no_projects_with_unfixed_errors")
            return results

        logger.info("projects_with_errors", count=len(projects))

        # Process each project
        for project_id, unfixed_counts in projects.items():
            if total_processed >= self.max_errors_per_run:
                logger.info(
                    "max_errors_reached",
                    processed=total_processed,
                    max=self.max_errors_per_run,
                )
                break

            try:
                project_results = process_project(
                    conn=self.conn,
                    project_id=project_id,
                    unfixed_counts=unfixed_counts,
                    remaining_budget=self.max_errors_per_run - total_processed,
                    cumulative_cost=cumulative_cost,
                    max_errors_per_project=self.max_errors_per_project,
                )
                processed = self._update_results_from_project(results, project_id, project_results)
                cumulative_cost = project_results.get("cumulative_cost_usd", cumulative_cost)
                total_processed += processed
            except BudgetExceededError as e:
                logger.warning(
                    "orchestrator_budget_exceeded",
                    cumulative_cost=e.cumulative_cost,
                    budget=e.budget,
                    project_id=project_id,
                )
                results["budget_exceeded"] = True
                results["cumulative_cost_usd"] = e.cumulative_cost
                break

        self._aggregate_by_check_type(results)

        logger.info(
            "orchestrator_poll_complete",
            projects=results["projects_processed"],
            fixed=results["total_fixed"],
            failed=results["total_failed"],
            escalated=results["total_escalated"],
            cost=results["cumulative_cost_usd"],
            budget_exceeded=results["budget_exceeded"],
        )

        return results

    def _update_results_from_project(
        self,
        results: dict[str, Any],
        project_id: str,
        project_results: dict[str, Any],
    ) -> int:
        """Update overall results from project results. Returns total processed count."""
        results["projects_processed"] += 1
        results["total_fixed"] += project_results["fixed"]
        results["total_failed"] += project_results["failed"]
        results["total_escalated"] += project_results["escalated"]
        results["by_project"][project_id] = project_results
        results["cumulative_cost_usd"] = project_results.get(
            "cumulative_cost_usd", results["cumulative_cost_usd"]
        )
        fixed: int = project_results["fixed"]
        failed: int = project_results["failed"]
        escalated: int = project_results["escalated"]
        return fixed + failed + escalated

    def _aggregate_by_check_type(self, results: dict[str, Any]) -> None:
        """Aggregate results by check type across all projects."""
        for project_data in results["by_project"].values():
            for check_type, counts in project_data.get("by_check_type", {}).items():
                if check_type not in results["by_check_type"]:
                    results["by_check_type"][check_type] = {"fixed": 0, "failed": 0, "escalated": 0}
                for key in ["fixed", "failed", "escalated"]:
                    results["by_check_type"][check_type][key] += counts.get(key, 0)



def poll_and_fix_all(
    conn: psycopg.Connection[Any],
    max_errors: int = MAX_ERRORS_PER_RUN,
) -> dict[str, Any]:
    """Convenience function for scheduled workflow task."""
    orchestrator = SelfHealingOrchestrator(conn, max_errors_per_run=max_errors)
    return orchestrator.poll_and_fix()
