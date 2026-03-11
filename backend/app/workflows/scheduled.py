"""Scheduled (cron) workflows for SummitFlow.

11 active cron workflows on Hatchet schedule (2 disabled: systemd monitor, browser monitor).
All use ConcurrencyExpression with CANCEL_IN_PROGRESS to prevent overlapping runs.
"""

from __future__ import annotations

import asyncio
from typing import Any

from hatchet_sdk import ConcurrencyExpression, ConcurrencyLimitStrategy, Context

from ..hatchet_app import hatchet
from .models import (
    EmptyInput,
    MonitorInput,
    ProjectInput,
    SelfHealingInput,
    StaleCleanupInput,
    SystemdMonitorInput,
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
    on_crons=["0 * * * *"],
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
    from ..tasks.autonomous.task_generation import cleanup_stale_tasks

    return await asyncio.to_thread(cleanup_stale_tasks, input.max_age_days)


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
    name="summitflow-monitor-systemd",
    input_validator=SystemdMonitorInput,
    execution_timeout="300s",
    retries=3,
    backoff_factor=2.0,
    # DISABLED: Creates noisy bug tasks from transient log errors with broken
    # dedup (28 pending, 0 ever completed). Runtime errors belong in
    # observability, not the task system. — 2026-02-20
    # on_crons=["*/5 * * * *"],
    concurrency=ConcurrencyExpression(
        expression="'summitflow-monitor-systemd'",
        max_runs=1,
        limit_strategy=ConcurrencyLimitStrategy.CANCEL_IN_PROGRESS,
    ),
)
async def monitor_systemd_wf(input: SystemdMonitorInput, ctx: Context) -> dict[str, Any]:
    from ..tasks.self_healing import monitor_systemd_errors

    return await asyncio.to_thread(
        monitor_systemd_errors, input.project_id, input.since, input.max_tasks
    )


@hatchet.task(
    name="summitflow-monitor-browser",
    input_validator=MonitorInput,
    execution_timeout="600s",
    retries=3,
    backoff_factor=2.0,
    # DISABLED: Creates bug tasks from console errors that are never resolved
    # autonomously. Console errors should surface in Explorer dashboard for
    # human review, not auto-create tasks. — 2026-02-20
    # on_crons=["30 */6 * * *"],
    concurrency=ConcurrencyExpression(
        expression="'summitflow-monitor-browser'",
        max_runs=1,
        limit_strategy=ConcurrencyLimitStrategy.CANCEL_IN_PROGRESS,
    ),
)
async def monitor_browser_wf(input: MonitorInput, ctx: Context) -> dict[str, Any]:
    from ..tasks.self_healing import monitor_browser_errors

    return await asyncio.to_thread(monitor_browser_errors, input.project_id, input.max_tasks)


@hatchet.task(
    name="summitflow-self-healing",
    input_validator=SelfHealingInput,
    execution_timeout="900s",
    retries=3,
    backoff_factor=2.0,
    on_crons=["*/15 * * * *"],
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
    on_crons=["*/15 * * * *"],
    concurrency=ConcurrencyExpression(
        expression="'summitflow-prod-smoke-test'",
        max_runs=1,
        limit_strategy=ConcurrencyLimitStrategy.CANCEL_IN_PROGRESS,
    ),
)
async def prod_smoke_test_wf(input: EmptyInput, ctx: Context) -> dict[str, Any]:
    from ..services.smoke_test import run_all_smoke_tests

    result = await asyncio.to_thread(run_all_smoke_tests)

    # Only notify on state transitions (healthy->unhealthy), not every check
    if result.get("should_notify"):
        from ..services.notifications import deliver

        failures = result.get("failures", [])
        names = ", ".join(f["project"] for f in failures)
        await deliver({
            "title": "Smoke Test Failed",
            "message": f"Unhealthy: {names}",
            "severity": "error",
        })

    return result


@hatchet.task(
    name="summitflow-health-monitor",
    input_validator=EmptyInput,
    execution_timeout="60s",
    retries=1,
    on_crons=["*/1 * * * *"],
    concurrency=ConcurrencyExpression(
        expression="'summitflow-health-monitor'",
        max_runs=1,
        limit_strategy=ConcurrencyLimitStrategy.CANCEL_IN_PROGRESS,
    ),
)
async def health_monitor_wf(input: EmptyInput, ctx: Context) -> dict[str, Any]:
    from ..services.notifications.health_monitor import check_and_notify

    return await asyncio.to_thread(check_and_notify)
