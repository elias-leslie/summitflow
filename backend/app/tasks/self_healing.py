"""Background tasks for self-healing monitoring and orchestration."""

from __future__ import annotations

from collections.abc import Callable

from ..logging_config import get_logger
from ..services.self_healing.browser_monitor import (
    BrowserErrorMonitor,
    create_browser_error_task,
)
from ..services.self_healing.monitor import (
    SystemdMonitor,
    create_error_task,
)
from ..storage.connection import get_connection
from ..workflows._model_constants import DEFAULT_PROJECT_ID

logger = get_logger(__name__)

MAX_TASKS_PER_RUN = 10
DEFAULT_MAX_ERRORS = 20
DEFAULT_ENABLED = True
ResultDict = dict[str, int]
OrchestrateResult = dict[str, int | str | bool]

_ZERO_ORCHESTRATE: OrchestrateResult = {"enabled": True, "projects_processed": 0, "total_fixed": 0, "total_failed": 0, "total_escalated": 0}


def _resolve_project_id(project_id: str | None = None) -> str:
    """Resolve project scope for self-healing task entry points."""
    return project_id or DEFAULT_PROJECT_ID


def _process_error_batch(
    errors: list[object],
    max_tasks: int,
    create_fn: Callable[..., dict[str, str] | None],
    project_id: str,
    log_key: str,
    log_attr: str,
) -> ResultDict:
    """Rate-limit and process a batch of errors, creating tasks for each."""
    results: ResultDict = {"created": 0, "skipped": 0, "errors": 0}

    for error in errors[:max_tasks]:
        try:
            task = create_fn(project_id, error)
            if task:
                results["created"] += 1
                logger.info(log_key, task_id=task["id"], **{log_attr: getattr(error, log_attr)})
            else:
                results["skipped"] += 1
        except Exception as exc:
            logger.error("task_creation_failed", error_hash=getattr(error, "error_hash", "unknown"), error=str(exc))
            results["errors"] += 1

    if len(errors) > max_tasks:
        logger.warning("monitoring_rate_limited", total_errors=len(errors), processed=max_tasks, skipped=len(errors) - max_tasks)

    return results


def monitor_browser_errors(
    project_id: str | None = None,
    max_tasks: int = MAX_TASKS_PER_RUN,
) -> ResultDict:
    """Monitor browser console errors and create bug tasks."""
    resolved_project_id = _resolve_project_id(project_id)
    logger.info("starting_browser_error_monitoring", project_id=resolved_project_id, max_tasks=max_tasks)
    results: ResultDict = {"created": 0, "skipped": 0, "errors": 0}

    try:
        new_errors = BrowserErrorMonitor(resolved_project_id).get_new_errors()
        if not new_errors:
            logger.debug("no_new_browser_errors_detected")
            return results

        logger.info("new_browser_errors_found", count=len(new_errors))
        results = _process_error_batch(
            new_errors, max_tasks, create_browser_error_task, resolved_project_id,
            "created_browser_error_task", "page_path",
        )
    except Exception as exc:
        logger.error("browser_monitoring_failed", error=str(exc))
        results["errors"] += 1

    logger.info("browser_monitoring_complete", **results)
    return results


def monitor_systemd_errors(
    project_id: str | None = None,
    since: str = "5 minutes ago",
    max_tasks: int = MAX_TASKS_PER_RUN,
) -> ResultDict:
    """Monitor systemd journal for errors and create bug tasks."""
    resolved_project_id = _resolve_project_id(project_id)
    logger.info("starting_systemd_monitoring", project_id=resolved_project_id, since=since, max_tasks=max_tasks)
    results: ResultDict = {"created": 0, "skipped": 0, "errors": 0}

    try:
        new_errors = SystemdMonitor(since=since).get_new_errors()
        if not new_errors:
            logger.debug("no_new_errors_detected")
            return results

        logger.info("new_errors_found", count=len(new_errors))
        results = _process_error_batch(
            new_errors, max_tasks, create_error_task, resolved_project_id,
            "created_task", "unit",
        )
    except Exception as exc:
        logger.error("monitoring_failed", error=str(exc))
        results["errors"] += 1

    logger.info("monitoring_complete", **results)
    return results


def _run_orchestration(max_errors: int) -> OrchestrateResult:
    """Run the orchestration within a database connection."""
    # Lazy import to avoid circular dependency at module load
    from ..services.self_healing.orchestrator import SelfHealingOrchestrator

    with get_connection() as conn:
        orchestrator = SelfHealingOrchestrator(conn, max_errors_per_run=max_errors)
        health = orchestrator.get_health_summary()

        if not health["should_run"]:
            logger.info("no_unfixed_errors")
            return {**_ZERO_ORCHESTRATE, "message": "No unfixed errors to process"}

        logger.info("unfixed_errors_found", total=health["total_unfixed"], projects=health["projects_needing_fixes"])
        results = orchestrator.poll_and_fix()
        conn.commit()

        logger.info("self_healing_complete", projects=results["projects_processed"], fixed=results["total_fixed"], failed=results["total_failed"], escalated=results["total_escalated"])
        return {"enabled": True, **results}


def orchestrate_self_healing(
    max_errors: int = DEFAULT_MAX_ERRORS,
    enabled: bool = DEFAULT_ENABLED,
) -> OrchestrateResult:
    """Orchestrate automated fix triggering for quality gate failures."""
    if not enabled:
        logger.info("self_healing_disabled")
        return {"enabled": False, "skipped": True}

    logger.info("starting_self_healing_orchestration", max_errors=max_errors)

    try:
        return _run_orchestration(max_errors)
    except Exception as exc:
        logger.error("self_healing_orchestration_failed", error=str(exc))
        return {**_ZERO_ORCHESTRATE, "error": str(exc)}
