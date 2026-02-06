"""Self-healing orchestration service for automated fix triggering.

Polls quality gate for unfixed errors and triggers fix agents automatically.
Respects check type priority: ruff → mypy → pytest (lint before type before test).

Implements 3-2-1 escalation through existing fix_agent infrastructure.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ...logging_config import get_logger
from ...storage import quality_check_results as qcr_store
from ...storage.projects import list_projects

if TYPE_CHECKING:
    import psycopg

logger = get_logger(__name__)

# =============================================================================
# Safety Constraints (hardcoded, not configurable per d14)
# =============================================================================
# Budget cap per orchestration run. Prevents runaway costs from autonomous fixes.
# Set conservatively at $2 to limit exposure while allowing meaningful work.
BUDGET_CAP_USD = 2.0


class BudgetExceededError(Exception):
    """Raised when cumulative cost exceeds BUDGET_CAP_USD.

    This is a safety constraint that cannot be disabled or configured.
    When raised, the orchestrator should stop all fix attempts immediately.
    """

    def __init__(self, cumulative_cost: float, budget: float = BUDGET_CAP_USD):
        self.cumulative_cost = cumulative_cost
        self.budget = budget
        super().__init__(
            f"Budget exceeded: ${cumulative_cost:.4f} >= ${budget:.2f}. "
            "Stopping autonomous fixes to prevent runaway costs."
        )


# Priority order for check types: fix lint first, then types, then tests
# Rationale: Lint errors are usually simpler, type errors may cascade from lint,
# and test failures often require both to be clean first.
CHECK_TYPE_PRIORITY = ["ruff", "biome", "mypy", "tsc", "pytest"]

# Maximum errors to fix per orchestration run (prevents runaway)
MAX_ERRORS_PER_RUN = 20

# Maximum errors to fix per project per run
MAX_ERRORS_PER_PROJECT = 10


class SelfHealingOrchestrator:
    """Orchestrates automated fix triggering for quality gate failures.

    Workflow:
    1. Poll all projects for unfixed quality gate errors
    2. Prioritize: ruff → mypy → pytest
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
        """Initialize the orchestrator.

        Args:
            conn: Database connection
            max_errors_per_run: Maximum total errors to process in one run
            max_errors_per_project: Maximum errors per project per run
        """
        self.conn = conn
        self.max_errors_per_run = max_errors_per_run
        self.max_errors_per_project = max_errors_per_project

    def poll_and_fix(self) -> dict[str, Any]:
        """Poll quality gate and trigger fix agents for unfixed errors.

        Returns:
            Summary dict with:
            - projects_processed: int
            - total_fixed: int
            - total_failed: int
            - total_escalated: int
            - by_check_type: dict[str, dict] - breakdown per check type
            - by_project: dict[str, dict] - breakdown per project
        """
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
        projects = self._get_projects_with_unfixed_errors()
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
                project_results = self._process_project(
                    project_id,
                    unfixed_counts,
                    remaining_budget=self.max_errors_per_run - total_processed,
                    cumulative_cost=cumulative_cost,
                )
            except BudgetExceededError as e:
                # Budget exceeded - stop processing but don't crash
                logger.warning(
                    "orchestrator_budget_exceeded",
                    cumulative_cost=e.cumulative_cost,
                    budget=e.budget,
                    project_id=project_id,
                )
                results["budget_exceeded"] = True
                results["cumulative_cost_usd"] = e.cumulative_cost
                break

            results["projects_processed"] += 1
            results["total_fixed"] += project_results["fixed"]
            results["total_failed"] += project_results["failed"]
            results["total_escalated"] += project_results["escalated"]
            results["by_project"][project_id] = project_results

            # Update cumulative cost from project results
            cumulative_cost = project_results.get("cumulative_cost_usd", cumulative_cost)
            results["cumulative_cost_usd"] = cumulative_cost

            total_processed += (
                project_results["fixed"] + project_results["failed"] + project_results["escalated"]
            )

        # Aggregate by check type
        for _project_id, project_data in results["by_project"].items():
            for check_type, counts in project_data.get("by_check_type", {}).items():
                if check_type not in results["by_check_type"]:
                    results["by_check_type"][check_type] = {
                        "fixed": 0,
                        "failed": 0,
                        "escalated": 0,
                    }
                results["by_check_type"][check_type]["fixed"] += counts.get("fixed", 0)
                results["by_check_type"][check_type]["failed"] += counts.get("failed", 0)
                results["by_check_type"][check_type]["escalated"] += counts.get("escalated", 0)

        logger.info(
            "orchestrator_poll_complete",
            projects=results["projects_processed"],
            fixed=results["total_fixed"],
            failed=results["total_failed"],
            escalated=results["total_escalated"],
            cumulative_cost_usd=results["cumulative_cost_usd"],
            budget_exceeded=results["budget_exceeded"],
        )

        return results

    def _get_projects_with_unfixed_errors(self) -> dict[str, dict[str, int]]:
        """Get all projects that have unfixed quality gate errors.

        Returns:
            Dict mapping project_id → {check_type → count}
        """
        projects_with_errors: dict[str, dict[str, int]] = {}

        # Get all active projects
        projects = list_projects()

        for project in projects:
            project_id = project["id"]
            unfixed_counts: dict[str, int] = {}

            # Check each fixable check type
            for check_type in ["ruff", "mypy", "biome", "tsc"]:
                count = qcr_store.get_unfixed_count(
                    self.conn,
                    project_id,
                    check_type=check_type,  # type: ignore[arg-type]
                )
                if count > 0:
                    unfixed_counts[check_type] = count

            if unfixed_counts:
                projects_with_errors[project_id] = unfixed_counts
                logger.debug(
                    "project_has_unfixed",
                    project_id=project_id,
                    counts=unfixed_counts,
                )

        return projects_with_errors

    def _process_project(
        self,
        project_id: str,
        unfixed_counts: dict[str, int],
        remaining_budget: int,
        cumulative_cost: float = 0.0,
    ) -> dict[str, Any]:
        """Process a single project, fixing errors in priority order.

        Args:
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
        from ..quality_gate import fix_unfixed_errors

        project_results: dict[str, Any] = {
            "fixed": 0,
            "failed": 0,
            "escalated": 0,
            "by_check_type": {},
            "cumulative_cost_usd": cumulative_cost,
        }

        project_budget = min(self.max_errors_per_project, remaining_budget)

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
                conn=self.conn,
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

    def get_health_summary(self) -> dict[str, Any]:
        """Get overall health summary for the orchestrator to decide if it should run.

        Returns:
            Dict with:
            - should_run: bool - whether there are unfixed errors to process
            - total_unfixed: int - total unfixed errors across all projects
            - projects_needing_fixes: int - count of projects with unfixed errors
        """
        projects = self._get_projects_with_unfixed_errors()

        total_unfixed = sum(sum(counts.values()) for counts in projects.values())

        return {
            "should_run": total_unfixed > 0,
            "total_unfixed": total_unfixed,
            "projects_needing_fixes": len(projects),
            "by_project": {pid: sum(counts.values()) for pid, counts in projects.items()},
        }


def poll_and_fix_all(
    conn: psycopg.Connection[Any],
    max_errors: int = MAX_ERRORS_PER_RUN,
) -> dict[str, Any]:
    """Convenience function for Celery task.

    Args:
        conn: Database connection
        max_errors: Maximum errors to process

    Returns:
        Orchestration results
    """
    orchestrator = SelfHealingOrchestrator(conn, max_errors_per_run=max_errors)
    return orchestrator.poll_and_fix()
