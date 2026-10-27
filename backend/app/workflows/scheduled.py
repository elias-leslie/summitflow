"""Scheduled (cron) workflows for SummitFlow.

System maintenance crons, each gated by a flag in app.services.schedule_registry.
Most use ConcurrencyExpression with CANCEL_IN_PROGRESS; explorer maintenance shares
CANCEL_NEWEST concurrency so scan/index jobs do not overlap.

Schedule philosophy (2026-03-16 tuning):
  - Health/smoke: */5 to */30 min — enough for alerting, not so frequent it drains CPU
  - Explorer: full scan */6h plus a daily 03:10 file sweep; per-file analysis, not git, is the cost
  - Cleanup/maintenance: daily retention
  - Claims reset: */15 min — lightweight DB query, kept frequent for task flow
"""

from __future__ import annotations

import asyncio
from typing import Any

from hatchet_sdk import ConcurrencyExpression, ConcurrencyLimitStrategy, Context

from ..hatchet_app import hatchet
from ..services.schedule_registry import (
    SUMMITFLOW_CONTROL_PROJECT_ID,
    is_schedule_enabled,
    schedule_cron,
)
from .models import (
    EmptyInput,
    StaleCleanupInput,
)


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


def _explorer_schedule_concurrency() -> ConcurrencyExpression:
    """Shared concurrency guard for memory-heavy explorer maintenance workflows."""

    return ConcurrencyExpression(
        expression="'summitflow-explorer-maintenance'",
        max_runs=1,
        limit_strategy=ConcurrencyLimitStrategy.CANCEL_NEWEST,
    )


@hatchet.task(
    name="summitflow-reset-claims",
    input_validator=EmptyInput,
    execution_timeout="120s",
    retries=3,
    backoff_factor=2.0,
    on_crons=[schedule_cron("reset_claims")],
    concurrency=ConcurrencyExpression(
        expression="'summitflow-reset-claims'",
        max_runs=1,
        limit_strategy=ConcurrencyLimitStrategy.CANCEL_IN_PROGRESS,
    ),
)
async def reset_claims_wf(input: EmptyInput, ctx: Context) -> dict[str, Any]:
    from typing import cast

    from ..tasks.task_claims import reset_expired_task_claims

    if not _system_schedule_enabled("reset_claims"):
        return _disabled_schedule_result("reset_claims")
    return cast(dict[str, Any], await asyncio.to_thread(reset_expired_task_claims))


@hatchet.task(
    name="summitflow-scan-projects",
    input_validator=EmptyInput,
    execution_timeout="1800s",
    retries=3,
    backoff_factor=2.0,
    on_crons=[schedule_cron("scan_projects")],
    concurrency=_explorer_schedule_concurrency(),
)
async def scan_projects_wf(input: EmptyInput, ctx: Context) -> dict[str, Any]:
    from ..tasks.explorer_tasks import scan_all_projects
    from .utility import make_post_scan_dispatch

    if not _system_schedule_enabled("scan_projects"):
        return _disabled_schedule_result("scan_projects")

    dispatch = make_post_scan_dispatch()
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
    on_crons=[schedule_cron("refresh_precision_indexes")],
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
    on_crons=[schedule_cron("refresh_graphify_graphs")],
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
    # The backups run from systemd; this hourly tick only checks their health and tidies old records.
    execution_timeout="900s",
    retries=1,
    on_crons=[schedule_cron("scheduled_backups")],
    concurrency=ConcurrencyExpression(
        expression="'summitflow-scheduled-backups'",
        max_runs=1,
        limit_strategy=ConcurrencyLimitStrategy.CANCEL_NEWEST,
    ),
)
async def scheduled_backups_wf(input: EmptyInput, ctx: Context) -> dict[str, Any]:
    from ..tasks.backup_scheduler import run_scheduled_backups

    if not _system_schedule_enabled("scheduled_backups"):
        return _disabled_schedule_result("scheduled_backups")

    return await asyncio.to_thread(run_scheduled_backups)


@hatchet.task(
    name="summitflow-stale-cleanup",
    input_validator=StaleCleanupInput,
    execution_timeout="600s",
    retries=3,
    backoff_factor=2.0,
    on_crons=[schedule_cron("stale_cleanup")],
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
    name="summitflow-hatchet-retention",
    input_validator=EmptyInput,
    execution_timeout="7200s",
    retries=1,
    on_crons=[schedule_cron("hatchet_retention")],
    concurrency=ConcurrencyExpression(
        expression="'summitflow-hatchet-retention'",
        max_runs=1,
        limit_strategy=ConcurrencyLimitStrategy.CANCEL_IN_PROGRESS,
    ),
)
async def hatchet_retention_wf(input: EmptyInput, ctx: Context) -> dict[str, Any]:
    from ..tasks.hatchet_retention import run_hatchet_retention_guard

    if not _system_schedule_enabled("hatchet_retention"):
        return _disabled_schedule_result("hatchet_retention")

    return await asyncio.to_thread(run_hatchet_retention_guard)


@hatchet.task(
    name="summitflow-prod-smoke-test",
    input_validator=EmptyInput,
    execution_timeout="60s",
    retries=1,
    on_crons=[schedule_cron("prod_smoke_test")],
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
    on_crons=[schedule_cron("health_monitor")],
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
    name="summitflow-runtime-hygiene",
    input_validator=EmptyInput,
    execution_timeout="1800s",
    retries=1,
    on_crons=[schedule_cron("runtime_hygiene")],
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


@hatchet.task(
    name="summitflow-nightly-publication",
    input_validator=EmptyInput,
    # Hourly plain pushes; a pass that overruns skips the next trigger.
    on_crons=[schedule_cron("nightly_publication")],
    execution_timeout="3300s",
    retries=0,
    concurrency=ConcurrencyExpression(
        expression="'summitflow-nightly-publication'",
        max_runs=1,
        # A running sweep continues; the next hourly trigger is skipped.
        limit_strategy=ConcurrencyLimitStrategy.CANCEL_NEWEST,
    ),
)
async def nightly_publication_wf(input: EmptyInput, ctx: Context) -> dict[str, Any]:
    from ..tasks.nightly_publication import run_nightly_publication

    if not _system_schedule_enabled("nightly_publication"):
        return _disabled_schedule_result("nightly_publication")
    return await asyncio.to_thread(run_nightly_publication)


@hatchet.task(
    name="summitflow-nightly-deep-lane",
    input_validator=EmptyInput,
    # UTC 05-11 covers the 01:00-07:00 New York window across DST; offset from
    # publication so the busy heavy lane defers whichever starts second.
    on_crons=[schedule_cron("nightly_deep_lane")],
    execution_timeout="21600s",
    retries=0,
    concurrency=ConcurrencyExpression(
        expression="'summitflow-nightly-deep-lane'",
        max_runs=1,
        limit_strategy=ConcurrencyLimitStrategy.CANCEL_NEWEST,
    ),
)
async def nightly_deep_lane_wf(input: EmptyInput, ctx: Context) -> dict[str, Any]:
    from ..tasks.nightly_deep_lane import run_nightly_deep_lane

    if not _system_schedule_enabled("nightly_deep_lane"):
        return _disabled_schedule_result("nightly_deep_lane")
    return await asyncio.to_thread(run_nightly_deep_lane)


@hatchet.task(
    name="summitflow-nightly-security-alert",
    input_validator=EmptyInput,
    execution_timeout="3600s",
    retries=0,
    on_crons=[schedule_cron("nightly_security_alert")],
    concurrency=ConcurrencyExpression(
        expression="'summitflow-nightly-security-alert'",
        max_runs=1,
        limit_strategy=ConcurrencyLimitStrategy.CANCEL_NEWEST,
    ),
)
async def nightly_security_alert_wf(input: EmptyInput, ctx: Context) -> dict[str, Any]:
    from ..tasks.nightly_security_alert import run_nightly_security_alert

    if not _system_schedule_enabled("nightly_security_alert"):
        return _disabled_schedule_result("nightly_security_alert")
    return await asyncio.to_thread(run_nightly_security_alert)
