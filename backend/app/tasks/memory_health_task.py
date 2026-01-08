"""Celery task for memory health monitoring.

Runs periodically to check memory system health and auto-correct issues:
- Auto-apply approved patterns
- Detect high filter rates
- Warn about missing observation types
"""

from __future__ import annotations

import os
from typing import Any

from celery import shared_task

from ..logging_config import get_logger
from ..services.memory.health_checker import MemoryHealthChecker

logger = get_logger(__name__)

# Global memory system kill switch - checked before processing
MEMORY_SYSTEM_ENABLED = os.getenv("MEMORY_SYSTEM_ENABLED", "true").lower() in ("true", "1", "yes")


@shared_task(  # type: ignore[untyped-decorator]
    name="summitflow.run_memory_health_check",
    bind=True,
    autoretry_for=(Exception,),
    retry_backoff=True,
    max_retries=2,
)
def run_memory_health_check(
    self: Any,
    project_id: str | None = None,
) -> dict[str, Any]:
    """Run memory health check and auto-correct any issues.

    Runs every 6 hours to:
    - Apply any approved patterns waiting
    - Check filter rate and warn if too high
    - Detect missing observation types

    Args:
        project_id: Project to check. If None, iterates all projects.

    Returns:
        Health report summary with corrections and warnings.
    """
    # Global kill switch - memory system disabled pending migration
    if not MEMORY_SYSTEM_ENABLED:
        logger.debug("memory_health_check_skipped: memory system disabled")
        return {"status": "skipped", "reason": "memory_system_disabled"}

    # If no project specified, run for all projects
    if project_id is None:
        from ..storage.projects import list_projects

        all_projects = list_projects()
        all_results: dict[str, Any] = {"projects": {}}

        for proj in all_projects:
            proj_id = proj["id"]
            logger.info(f"run_memory_health_check: starting for project={proj_id}")
            result = _run_health_check_for_project(proj_id)
            all_results["projects"][proj_id] = result

        return all_results

    logger.info(f"run_memory_health_check: starting for project={project_id}")
    return _run_health_check_for_project(project_id)


def _run_health_check_for_project(project_id: str) -> dict[str, Any]:
    """Run health check for a single project."""
    try:
        checker = MemoryHealthChecker(project_id)
        report = checker.check_and_correct()

        # Log summary
        corrections_count = len(report.corrections)
        warnings_count = len(report.warnings)

        logger.info(
            f"run_memory_health_check: completed "
            f"status={report.status} "
            f"corrections={corrections_count} "
            f"warnings={warnings_count}"
        )

        # Log individual corrections
        for correction in report.corrections:
            logger.info(
                f"run_memory_health_check: correction applied - "
                f"{correction.correction_type}: {correction.description}"
            )

        # Log warnings
        for warning in report.warnings:
            log_fn = logger.warning if warning.severity == "high" else logger.info
            log_fn(
                f"run_memory_health_check: warning - "
                f"[{warning.severity}] {warning.warning_type}: {warning.message}"
            )

        return report.to_dict()

    except Exception as e:
        logger.error(f"run_memory_health_check: failed for {project_id} - {e}")
        return {"status": "error", "error": str(e)}


@shared_task(  # type: ignore[untyped-decorator]
    name="summitflow.run_weekly_deep_review",
    bind=True,
    autoretry_for=(Exception,),
    retry_backoff=True,
    max_retries=1,
)
def run_weekly_deep_review(self: Any) -> dict[str, Any]:
    """Run comprehensive deep review of all projects' instruction surfaces.

    Runs weekly (Sundays at 2am) to:
    - Review CLAUDE.md and AGENTS.md for staleness
    - Check for broken references
    - Run LLM content review for outdated sections
    - Calculate token waste
    - Create cleanup tasks if critical issues found

    Returns:
        Summary of all project reviews with issues found.
    """
    # Global kill switch - memory system disabled pending migration
    if not MEMORY_SYSTEM_ENABLED:
        logger.debug("run_weekly_deep_review_skipped: memory system disabled")
        return {"status": "skipped", "reason": "memory_system_disabled"}

    from ..storage.connection import get_connection

    logger.info("run_weekly_deep_review: starting weekly review")

    results: dict[str, Any] = {
        "projects_reviewed": 0,
        "total_broken_refs": 0,
        "total_stale_sections": 0,
        "total_token_waste_pct": 0.0,
        "project_reports": [],
    }

    try:
        # Get all projects with memory enabled via direct query
        with get_connection() as conn, conn.cursor() as cur:
            cur.execute("""
                SELECT id FROM projects
                WHERE id IN (
                    SELECT project_id FROM agent_configs
                    WHERE memory_enabled = true
                )
            """)
            rows = cur.fetchall()
            projects = [{"project_id": row[0]} for row in rows]

        for project_config in projects:
            project_id = project_config.get("project_id")
            if not project_id:
                continue

            logger.info(f"run_weekly_deep_review: reviewing project {project_id}")

            try:
                checker = MemoryHealthChecker(project_id)
                report = checker.deep_review()

                project_summary = {
                    "project_id": project_id,
                    "broken_refs": len(report.broken_refs),
                    "stale_sections": len(report.stale_sections),
                    "token_waste_pct": report.token_waste.get("waste_pct", 0),
                    "rules_count": len(report.rules_files),
                    "global_rules_count": len(report.global_rules_files),
                }

                results["project_reports"].append(project_summary)
                results["projects_reviewed"] += 1
                results["total_broken_refs"] += len(report.broken_refs)
                results["total_stale_sections"] += len(report.stale_sections)

                # Log critical issues
                if len(report.broken_refs) > 5:
                    logger.warning(
                        f"run_weekly_deep_review: {project_id} has {len(report.broken_refs)} broken refs"
                    )

                if report.token_waste.get("waste_pct", 0) > 10:
                    logger.warning(
                        f"run_weekly_deep_review: {project_id} has "
                        f"{report.token_waste.get('waste_pct')}% token waste"
                    )

            except Exception as e:
                logger.error(f"run_weekly_deep_review: failed for {project_id} - {e}")
                results["project_reports"].append(
                    {
                        "project_id": project_id,
                        "error": str(e),
                    }
                )

        # Calculate overall stats
        if results["projects_reviewed"] > 0:
            total_waste = sum(
                p.get("token_waste_pct", 0)
                for p in results["project_reports"]
                if isinstance(p.get("token_waste_pct"), int | float)
            )
            results["total_token_waste_pct"] = total_waste / results["projects_reviewed"]

        logger.info(
            f"run_weekly_deep_review: completed - "
            f"projects={results['projects_reviewed']} "
            f"broken_refs={results['total_broken_refs']} "
            f"stale_sections={results['total_stale_sections']}"
        )

        return results

    except Exception as e:
        logger.error(f"run_weekly_deep_review: failed - {e}")
        raise
