"""Scheduled (cron) workflows for SummitFlow.

12 active cron workflows on Hatchet schedule.
All use ConcurrencyExpression with CANCEL_IN_PROGRESS to prevent overlapping runs.

Schedule philosophy (2026-03-16 tuning):
  - Health/smoke: */5 to */30 min — enough for alerting, not so frequent it drains CPU
  - Explorer/indexes: */2h — batch git ops on 6000+ files are the biggest CPU cost
  - Cleanup/maintenance: daily or weekly — no urgency
  - Claims reset: */15 min — lightweight DB query, kept frequent for task flow
"""

from __future__ import annotations

import asyncio
from typing import Any

from hatchet_sdk import ConcurrencyExpression, ConcurrencyLimitStrategy, Context

from ..hatchet_app import hatchet
from .models import (
    EmptyInput,
    ProjectInput,
    SelfHealingInput,
    StaleCleanupInput,
)


@hatchet.task(
    name="summitflow-work-pickup",
    input_validator=ProjectInput,
    execution_timeout="600s",
    retries=3,
    backoff_factor=2.0,
    on_crons=["15 */2 * * *"],
    concurrency=ConcurrencyExpression(
        expression="'summitflow-work-pickup'",
        max_runs=1,
        limit_strategy=ConcurrencyLimitStrategy.CANCEL_IN_PROGRESS,
    ),
)
async def work_pickup_wf(input: ProjectInput, ctx: Context) -> dict[str, Any]:
    from ..tasks.autonomous.pickup import autonomous_work_pickup
    from .pipeline import _make_dispatch_callback

    dispatch = _make_dispatch_callback()
    return await asyncio.to_thread(autonomous_work_pickup, input.project_id, dispatch=dispatch)


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

    result = await asyncio.to_thread(reset_expired_task_claims)
    return cast(dict[str, Any], result)


@hatchet.task(
    name="summitflow-scan-projects",
    input_validator=EmptyInput,
    execution_timeout="1800s",
    retries=3,
    backoff_factor=2.0,
    on_crons=["0 */6 * * *"],
    concurrency=ConcurrencyExpression(
        expression="'summitflow-scan-projects'",
        max_runs=1,
        limit_strategy=ConcurrencyLimitStrategy.CANCEL_IN_PROGRESS,
    ),
)
async def scan_projects_wf(input: EmptyInput, ctx: Context) -> dict[str, Any]:
    from ..tasks.explorer_tasks import scan_all_projects
    from .pipeline import _make_dispatch_callback

    dispatch = _make_dispatch_callback()
    return await asyncio.to_thread(scan_all_projects, dry_run=False, dispatch=dispatch)


@hatchet.task(
    name="summitflow-refresh-precision-indexes",
    input_validator=EmptyInput,
    execution_timeout="1200s",
    retries=3,
    backoff_factor=2.0,
    on_crons=["10 */2 * * *"],
    concurrency=ConcurrencyExpression(
        expression="'summitflow-refresh-precision-indexes'",
        max_runs=1,
        limit_strategy=ConcurrencyLimitStrategy.CANCEL_IN_PROGRESS,
    ),
)
async def refresh_precision_indexes_wf(input: EmptyInput, ctx: Context) -> dict[str, Any]:
    from ..tasks.explorer_tasks import scan_all_projects

    return await asyncio.to_thread(
        scan_all_projects,
        entry_type="file",
        dry_run=False,
        dispatch=None,
    )


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

    return await asyncio.to_thread(run_daily_maintenance, input.max_age_days)


@hatchet.task(
    name="summitflow-task-generation",
    input_validator=ProjectInput,
    execution_timeout="600s",
    retries=3,
    backoff_factor=2.0,
    on_crons=["0 4 * * 1"],
    concurrency=ConcurrencyExpression(
        expression="'summitflow-task-generation'",
        max_runs=1,
        limit_strategy=ConcurrencyLimitStrategy.CANCEL_IN_PROGRESS,
    ),
)
async def task_generation_wf(input: ProjectInput, ctx: Context) -> dict[str, Any]:
    from ..tasks.autonomous.task_generation import generate_tasks_from_scan

    return await asyncio.to_thread(generate_tasks_from_scan, input.project_id)


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

    return await asyncio.to_thread(run_restore_tests)
