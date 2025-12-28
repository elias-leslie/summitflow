"""Celery task for memory health monitoring.

Runs periodically to check memory system health and auto-correct issues:
- Auto-apply approved patterns
- Detect high filter rates
- Warn about missing observation types
"""

from __future__ import annotations

from typing import Any

from celery import shared_task

from ..logging_config import get_logger
from ..services.memory.health_checker import MemoryHealthChecker

logger = get_logger(__name__)


@shared_task(
    name="summitflow.run_memory_health_check",
    bind=True,
    autoretry_for=(Exception,),
    retry_backoff=True,
    max_retries=2,
)
def run_memory_health_check(
    self,
    project_id: str = "summitflow",
) -> dict[str, Any]:
    """Run memory health check and auto-correct any issues.

    Runs every 6 hours to:
    - Apply any approved patterns waiting
    - Check filter rate and warn if too high
    - Detect missing observation types

    Args:
        project_id: Project to check (default: summitflow)

    Returns:
        Health report summary with corrections and warnings.
    """
    logger.info(f"run_memory_health_check: starting for project={project_id}")

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
        logger.error(f"run_memory_health_check: failed - {e}")
        raise
