"""Scheduled (cron) workflows for SummitFlow.

15 cron workflows on Hatchet schedule; 12 enabled by default.
Autonomous work pickup is explicit opt-in so missing project config cannot dispatch work.
Most use ConcurrencyExpression with CANCEL_IN_PROGRESS; explorer maintenance shares
CANCEL_NEWEST concurrency so scan/index jobs do not overlap.

Schedule philosophy (2026-03-16 tuning):
  - Health/smoke: */5 to */30 min — enough for alerting, not so frequent it drains CPU
  - Explorer/indexes: */2h — batch git ops on 6000+ files are the biggest CPU cost
  - Cleanup/maintenance: hourly due checks for opt-in upkeep, daily retention
  - Claims reset: */15 min — lightweight DB query, kept frequent for task flow
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any

from hatchet_sdk import ConcurrencyExpression, ConcurrencyLimitStrategy, Context

from ..hatchet_app import hatchet
from ..services.autonomous_schedule_registry import (
    SUMMITFLOW_CONTROL_PROJECT_ID,
    is_schedule_enabled,
)
from .models import (
    EmptyInput,
    ProjectInput,
    SelfHealingInput,
    StaleCleanupInput,
)

WORK_PICKUP_WORKFLOW = "autonomous_work_pickup"


def _project_schedule_enabled(project_id: str, schedule_id: str) -> bool:
    return is_schedule_enabled(project_id, schedule_id)


def _system_schedule_enabled(schedule_id: str) -> bool:
    return is_schedule_enabled(SUMMITFLOW_CONTROL_PROJECT_ID, schedule_id)


def _disabled_schedule_result(
    schedule_id: str,
    *,
    project_id: str | None = None,
) -> dict[str, Any]:
    result: dict[str, Any] = {"schedule_id": schedule_id, "status": "disabled"}
    if project_id is not None:
        result["project_id"] = project_id
    return result


def _enabled_project_ids(schedule_id: str) -> list[str]:
    from ..storage.projects import list_projects

    return [
        str(project["id"])
        for project in list_projects()
        if _project_schedule_enabled(str(project["id"]), schedule_id)
    ]


def _work_pickup_due(project_id: str) -> bool:
    from ..storage import agent_configs
    from ..storage import maintenance_runs as maintenance_store

    config = agent_configs.get_agent_config(project_id)
    frequency_minutes = int(config.get("autonomous_frequency_minutes", 30) or 30)
    recent = maintenance_store.list_maintenance_runs(
        limit=1,
        workflow_name=WORK_PICKUP_WORKFLOW,
        project_id=project_id,
    )
    if not recent:
        return True
    started_at = recent[0].get("started_at")
    if not isinstance(started_at, datetime):
        return True
    if started_at.tzinfo is None:
        started_at = started_at.replace(tzinfo=UTC)
    return datetime.now(UTC) - started_at >= timedelta(minutes=frequency_minutes)


def _record_work_pickup(project_id: str, started_at: datetime, result: dict[str, Any]) -> None:
    from ..storage import maintenance_runs as maintenance_store

    summary = {"project_id": project_id, **result}
    status = "failed" if result.get("status") in {"disabled", "unhealthy"} else "completed"
    error_message = str(result.get("reason") or "") if status == "failed" else ""
    maintenance_store.record_maintenance_run(
        WORK_PICKUP_WORKFLOW,
        status,
        started_at=started_at,
        finished_at=datetime.now(UTC),
        rows_cleaned=int(result.get("dispatched", 0) or 0),
        summary=summary,
        error_message=error_message or None,
    )


async def _run_work_pickup_for_project(project_id: str) -> dict[str, Any]:
    from ..tasks.autonomous.pickup import autonomous_work_pickup
    from .pipeline import _make_dispatch_callback

    if not _project_schedule_enabled(project_id, "work_pickup"):
        return _disabled_schedule_result("work_pickup", project_id=project_id)
    if not _work_pickup_due(project_id):
        return {
            "schedule_id": "work_pickup",
            "status": "skipped",
            "reason": "not_due",
            "project_id": project_id,
        }

    started_at = datetime.now(UTC)
    dispatch = _make_dispatch_callback()
    result = await asyncio.to_thread(autonomous_work_pickup, project_id, dispatch=dispatch)
    await asyncio.to_thread(_record_work_pickup, project_id, started_at, dict(result))
    return dict(result)


async def _run_task_generation_for_project(project_id: str) -> dict[str, Any]:
    from ..tasks.autonomous.upkeep import run_routine_upkeep

    if not _project_schedule_enabled(project_id, "task_generation"):
        return _disabled_schedule_result("task_generation", project_id=project_id)

    return await asyncio.to_thread(
        run_routine_upkeep,
        project_id,
    )


async def _run_project_schedule_for_enabled_projects(schedule_id: str) -> dict[str, Any]:
    project_ids = _enabled_project_ids(schedule_id)
    results: dict[str, dict[str, Any]] = {}
    for project_id in project_ids:
        if schedule_id == "work_pickup":
            results[project_id] = await _run_work_pickup_for_project(project_id)
        else:
            results[project_id] = await _run_task_generation_for_project(project_id)
    return {
        "schedule_id": schedule_id,
        "status": "completed",
        "project_count": len(project_ids),
        "dispatched": sum(
            int((result.get("dispatch") or {}).get("dispatched", result.get("dispatched", 0)) or 0)
            for result in results.values()
        ),
        "projects": results,
    }


def _explorer_schedule_concurrency() -> ConcurrencyExpression:
    """Shared concurrency guard for memory-heavy explorer maintenance workflows."""

    return ConcurrencyExpression(
        expression="'summitflow-explorer-maintenance'",
        max_runs=1,
        limit_strategy=ConcurrencyLimitStrategy.CANCEL_NEWEST,
    )


@hatchet.task(
    name="summitflow-work-pickup",
    input_validator=ProjectInput,
    execution_timeout="600s",
    retries=3,
    backoff_factor=2.0,
    on_crons=["*/15 * * * *"],
    concurrency=ConcurrencyExpression(
        expression="'summitflow-work-pickup'",
        max_runs=1,
        limit_strategy=ConcurrencyLimitStrategy.CANCEL_IN_PROGRESS,
    ),
)
async def work_pickup_wf(input: ProjectInput, ctx: Context) -> dict[str, Any]:
    if input.project_id == SUMMITFLOW_CONTROL_PROJECT_ID:
        return await _run_project_schedule_for_enabled_projects("work_pickup")
    return await _run_work_pickup_for_project(input.project_id)


@hatchet.task(
    name="summitflow-reset-claims",
    input_validator=EmptyInput,
    execution_timeout="120s",
    retries=3,
    backoff_factor=2.0,
    on_crons=["*/15 * * * *"],
    concurrency=ConcurrencyExpression(
        expression="'summitflow-reset-claims'",
        max_runs=1,
        limit_strategy=ConcurrencyLimitStrategy.CANCEL_IN_PROGRESS,
    ),
)
async def reset_claims_wf(input: EmptyInput, ctx: Context) -> dict[str, Any]:
    from typing import cast

    from ..tasks.autonomous.cleanup import reset_expired_task_claims

    if not _system_schedule_enabled("reset_claims"):
        return _disabled_schedule_result("reset_claims")

    result = await asyncio.to_thread(reset_expired_task_claims)
    return cast(dict[str, Any], result)


@hatchet.task(
    name="summitflow-scan-projects",
    input_validator=EmptyInput,
    execution_timeout="1800s",
    retries=3,
    backoff_factor=2.0,
    on_crons=["0 */6 * * *"],
    concurrency=_explorer_schedule_concurrency(),
)
async def scan_projects_wf(input: EmptyInput, ctx: Context) -> dict[str, Any]:
    from ..tasks.explorer_tasks import scan_all_projects
    from .pipeline import _make_dispatch_callback

    if not _system_schedule_enabled("scan_projects"):
        return _disabled_schedule_result("scan_projects")

    dispatch = _make_dispatch_callback()
    return await asyncio.to_thread(
        scan_all_projects,
        dry_run=False,
        dispatch=dispatch,
        isolate_process=True,
    )


@hatchet.task(
    name="summitflow-refresh-precision-indexes",
    input_validator=EmptyInput,
    execution_timeout="1200s",
    retries=3,
    backoff_factor=2.0,
    on_crons=["10 */2 * * *"],
    concurrency=_explorer_schedule_concurrency(),
)
async def refresh_precision_indexes_wf(input: EmptyInput, ctx: Context) -> dict[str, Any]:
    from ..tasks.explorer_tasks import scan_all_projects

    if not _system_schedule_enabled("refresh_precision_indexes"):
        return _disabled_schedule_result("refresh_precision_indexes")

    return await asyncio.to_thread(
        scan_all_projects,
        entry_type="file",
        dry_run=False,
        dispatch=None,
        isolate_process=True,
    )


@hatchet.task(
    name="summitflow-refresh-graphify-graphs",
    input_validator=EmptyInput,
    execution_timeout="1200s",
    retries=3,
    backoff_factor=2.0,
    on_crons=["25 */2 * * *"],
    concurrency=_explorer_schedule_concurrency(),
)
async def refresh_graphify_graphs_wf(input: EmptyInput, ctx: Context) -> dict[str, Any]:
    from ..tasks.graphify_tasks import refresh_existing_graphify_graphs

    if not _system_schedule_enabled("refresh_graphify_graphs"):
        return _disabled_schedule_result("refresh_graphify_graphs")

    return await asyncio.to_thread(refresh_existing_graphify_graphs)


@hatchet.task(
    name="summitflow-scheduled-backups",
    input_validator=EmptyInput,
    execution_timeout="300s",
    retries=3,
    backoff_factor=2.0,
    on_crons=["30 * * * *"],
    concurrency=ConcurrencyExpression(
        expression="'summitflow-scheduled-backups'",
        max_runs=1,
        limit_strategy=ConcurrencyLimitStrategy.CANCEL_IN_PROGRESS,
    ),
)
async def scheduled_backups_wf(input: EmptyInput, ctx: Context) -> dict[str, Any]:
    from ..tasks.backup import run_scheduled_backups

    if not _system_schedule_enabled("scheduled_backups"):
        return _disabled_schedule_result("scheduled_backups")

    return await asyncio.to_thread(run_scheduled_backups)


@hatchet.task(
    name="summitflow-stale-cleanup",
    input_validator=StaleCleanupInput,
    execution_timeout="600s",
    retries=3,
    backoff_factor=2.0,
    on_crons=["0 4 * * *"],
    concurrency=ConcurrencyExpression(
        expression="'summitflow-stale-cleanup'",
        max_runs=1,
        limit_strategy=ConcurrencyLimitStrategy.CANCEL_IN_PROGRESS,
    ),
)
async def stale_cleanup_wf(input: StaleCleanupInput, ctx: Context) -> dict[str, Any]:
    from ..tasks.maintenance import run_daily_maintenance

    if not _system_schedule_enabled("stale_cleanup"):
        return _disabled_schedule_result("stale_cleanup")

    return await asyncio.to_thread(run_daily_maintenance, input.max_age_days)


@hatchet.task(
    name="summitflow-task-generation",
    input_validator=ProjectInput,
    execution_timeout="600s",
    retries=3,
    backoff_factor=2.0,
    on_crons=["0 * * * *"],
    concurrency=ConcurrencyExpression(
        expression="'summitflow-task-generation'",
        max_runs=1,
        limit_strategy=ConcurrencyLimitStrategy.CANCEL_IN_PROGRESS,
    ),
)
async def task_generation_wf(input: ProjectInput, ctx: Context) -> dict[str, Any]:
    if input.project_id == SUMMITFLOW_CONTROL_PROJECT_ID:
        return await _run_project_schedule_for_enabled_projects("task_generation")
    return await _run_task_generation_for_project(input.project_id)


@hatchet.task(
    name="summitflow-tool-governance",
    input_validator=EmptyInput,
    execution_timeout="300s",
    retries=2,
    backoff_factor=2.0,
    on_crons=["40 16 * * *"],
    concurrency=ConcurrencyExpression(
        expression="'summitflow-tool-governance'",
        max_runs=1,
        limit_strategy=ConcurrencyLimitStrategy.CANCEL_IN_PROGRESS,
    ),
)
async def tool_governance_wf(input: EmptyInput, ctx: Context) -> dict[str, Any]:
    from ..tasks.tool_governance import run_tool_governance_scan

    if not _system_schedule_enabled("tool_governance"):
        return _disabled_schedule_result("tool_governance")

    return await asyncio.to_thread(run_tool_governance_scan)


@hatchet.task(
    name="summitflow-self-healing",
    input_validator=SelfHealingInput,
    execution_timeout="900s",
    retries=3,
    backoff_factor=2.0,
    on_crons=["*/30 * * * *"],
    concurrency=ConcurrencyExpression(
        expression="'summitflow-self-healing'",
        max_runs=1,
        limit_strategy=ConcurrencyLimitStrategy.CANCEL_IN_PROGRESS,
    ),
)
async def self_healing_wf(input: SelfHealingInput, ctx: Context) -> dict[str, Any]:
    from ..tasks.self_healing import orchestrate_self_healing

    if not _system_schedule_enabled("self_healing"):
        return _disabled_schedule_result("self_healing")

    return await asyncio.to_thread(orchestrate_self_healing, input.max_errors, input.enabled)



@hatchet.task(
    name="summitflow-prod-smoke-test",
    input_validator=EmptyInput,
    execution_timeout="60s",
    retries=1,
    on_crons=["*/30 * * * *"],
    concurrency=ConcurrencyExpression(
        expression="'summitflow-prod-smoke-test'",
        max_runs=1,
        limit_strategy=ConcurrencyLimitStrategy.CANCEL_IN_PROGRESS,
    ),
)
async def prod_smoke_test_wf(input: EmptyInput, ctx: Context) -> dict[str, Any]:
    from ..services.smoke_test import run_all_smoke_tests

    if not _system_schedule_enabled("prod_smoke_test"):
        return _disabled_schedule_result("prod_smoke_test")

    result = await asyncio.to_thread(run_all_smoke_tests)

    # Only notify on state transitions (healthy->unhealthy), not every check.
    # Route through create_notification() for dedup and DB persistence.
    if result.get("should_notify"):
        from ..storage.notifications import create_notification

        failures = result.get("failures", [])
        current = result.get("current_status", "unhealthy")

        if current == "unhealthy":
            names = ", ".join(f["project"] for f in failures)
            statuses = "; ".join(f"{f['project']}: {f['status']}" for f in failures[:3])
            await asyncio.to_thread(
                create_notification,
                project_id="summitflow",
                notification_type="system",
                title="Smoke test failed",
                message=f"Unhealthy: {names}. {statuses}",
                severity="error",
                metadata={"smoke_test": True, "failures": [f["project"] for f in failures]},
            )

    return result


@hatchet.task(
    name="summitflow-health-monitor",
    input_validator=EmptyInput,
    execution_timeout="60s",
    retries=1,
    on_crons=["*/5 * * * *"],
    concurrency=ConcurrencyExpression(
        expression="'summitflow-health-monitor'",
        max_runs=1,
        limit_strategy=ConcurrencyLimitStrategy.CANCEL_IN_PROGRESS,
    ),
)
async def health_monitor_wf(input: EmptyInput, ctx: Context) -> dict[str, Any]:
    from ..services.notifications.health_monitor import check_and_notify

    if not _system_schedule_enabled("health_monitor"):
        return _disabled_schedule_result("health_monitor")

    return await asyncio.to_thread(check_and_notify)


@hatchet.task(
    name="summitflow-pending-drain",
    input_validator=EmptyInput,
    execution_timeout="600s",
    retries=2,
    backoff_factor=2.0,
    on_crons=["*/30 * * * *"],
    concurrency=ConcurrencyExpression(
        expression="'summitflow-pending-drain'",
        max_runs=1,
        limit_strategy=ConcurrencyLimitStrategy.CANCEL_IN_PROGRESS,
    ),
)
async def pending_drain_wf(input: EmptyInput, ctx: Context) -> dict[str, Any]:
    from ..tasks.backup_drain import drain_pending_backups

    if not _system_schedule_enabled("pending_drain"):
        return _disabled_schedule_result("pending_drain")

    return await asyncio.to_thread(drain_pending_backups)



@hatchet.task(
    name="summitflow-restore-tests",
    input_validator=EmptyInput,
    execution_timeout="1800s",
    retries=1,
    on_crons=["0 6 * * 0"],
    concurrency=ConcurrencyExpression(
        expression="'summitflow-restore-tests'",
        max_runs=1,
        limit_strategy=ConcurrencyLimitStrategy.CANCEL_IN_PROGRESS,
    ),
)
async def restore_tests_wf(input: EmptyInput, ctx: Context) -> dict[str, Any]:
    from ..tasks.backup_restore_test import run_restore_tests

    if not _system_schedule_enabled("restore_tests"):
        return _disabled_schedule_result("restore_tests")

    return await asyncio.to_thread(run_restore_tests)


@hatchet.task(
    name="summitflow-runtime-hygiene",
    input_validator=EmptyInput,
    execution_timeout="1800s",
    retries=1,
    on_crons=["10 16 * * *"],
    concurrency=ConcurrencyExpression(
        expression="'summitflow-runtime-hygiene'",
        max_runs=1,
        limit_strategy=ConcurrencyLimitStrategy.CANCEL_IN_PROGRESS,
    ),
)
async def runtime_hygiene_wf(input: EmptyInput, ctx: Context) -> dict[str, Any]:
    from ..tasks.runtime_hygiene import run_runtime_hygiene

    if not _system_schedule_enabled("runtime_hygiene"):
        return _disabled_schedule_result("runtime_hygiene")

    return await asyncio.to_thread(run_runtime_hygiene)
