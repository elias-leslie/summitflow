"""Utility (on-demand) workflows for SummitFlow.

12 workflows for backup/restore, enrichment, PR review, checkout cleanup,
and post-scan task generation.
"""

from __future__ import annotations

import asyncio
from typing import Any, cast

from hatchet_sdk import ConcurrencyExpression, ConcurrencyLimitStrategy, Context

from ..hatchet_app import hatchet
from .backup_progress import make_backup_progress_callback
from .models import (
    AutoFixInput,
    BackupInput,
    EnrichInput,
    OffsiteSyncInput,
    ProjectInput,
    RestoreInput,
    ReviewPRInput,
    TaskInput,
)


async def _run_quality_auto_fix_off_thread(input: AutoFixInput) -> dict[str, Any]:
    """Keep synchronous LLM and subprocess work off the worker event loop."""
    from ..tasks.quality_auto_fix import run_quality_auto_fix

    return cast(
        dict[str, Any],
        await asyncio.to_thread(
            run_quality_auto_fix,
            input.project_id,
            input.check_type,
            input.limit,
        ),
    )


@hatchet.task(
    name="summitflow-quality-auto-fix",
    input_validator=AutoFixInput,
    concurrency=[
        ConcurrencyExpression(
            expression="input.project_id",
            max_runs=1,
            limit_strategy=ConcurrencyLimitStrategy.GROUP_ROUND_ROBIN,
        ),
    ],
)
async def quality_auto_fix_wf(input: AutoFixInput, ctx: Context) -> dict[str, Any]:
    """Durably run one project-scoped quality auto-fix batch."""
    return await _run_quality_auto_fix_off_thread(input)


@hatchet.task(
    name="summitflow-backup-create",
    input_validator=BackupInput,
    execution_timeout="900s",
    retries=2,
    backoff_factor=2.0,
    concurrency=[
        ConcurrencyExpression(
            expression="input.source_id",
            max_runs=1,
            limit_strategy=ConcurrencyLimitStrategy.GROUP_ROUND_ROBIN,
        ),
        ConcurrencyExpression(
            expression="'backup-smb'",
            max_runs=2,
            limit_strategy=ConcurrencyLimitStrategy.GROUP_ROUND_ROBIN,
        ),
    ],
)
async def backup_create_wf(input: BackupInput, ctx: Context) -> dict[str, Any]:
    from ..tasks.backup import create_backup

    options: dict[str, Any] = {}
    if input.local_only:
        options["local_only"] = True
    if input.storage_backend_id is not None:
        options["storage_backend_id"] = input.storage_backend_id
    return await asyncio.to_thread(
        create_backup,
        project_id=input.project_id,
        note=input.note,
        backup_type=input.backup_type,
        keep_local=input.keep_local,
        retention_days=input.retention_days,
        source_id=input.source_id,
        on_progress=make_backup_progress_callback(ctx),
        **options,
    )


@hatchet.task(
    name="summitflow-backup-restore",
    input_validator=RestoreInput,
    execution_timeout="2100s",
    retries=2,
    backoff_factor=2.0,
    concurrency=[
        ConcurrencyExpression(
            expression="input.project_id",
            max_runs=1,
            limit_strategy=ConcurrencyLimitStrategy.CANCEL_IN_PROGRESS,
        ),
    ],
)
async def backup_restore_wf(input: RestoreInput, ctx: Context) -> dict[str, Any]:
    from ..tasks.backup import restore_backup

    return await asyncio.to_thread(
        restore_backup,
        input.project_id,
        input.backup_id,
        input.backup_file,
        input.dry_run,
        input.db_only,
        input.files_only,
        input.source_id,
    )


@hatchet.task(
    name="summitflow-backup-offsite-sync",
    input_validator=OffsiteSyncInput,
    execution_timeout="900s",
    retries=2,
    backoff_factor=2.0,
    concurrency=[
        ConcurrencyExpression(
            expression="input.source_id",
            max_runs=1,
            limit_strategy=ConcurrencyLimitStrategy.GROUP_ROUND_ROBIN,
        ),
    ],
)
async def backup_offsite_sync_wf(input: OffsiteSyncInput, ctx: Context) -> dict[str, Any]:
    """Retry Drive replication without capturing a new local archive."""
    from ..storage import backups as backup_store
    from ..tasks.backup_executor import sync_backup_offsite
    from ..tasks.backup_lock import release_backup_lock

    try:
        return await asyncio.to_thread(
            sync_backup_offsite, input.backup_id, on_progress=make_backup_progress_callback(ctx, input.attempt_id),
            owner_token=input.owner_token,
        )
    except Exception as exc:
        failure = {
            "activity": {"active": False, "phase": "failed", "attention": True},
            "offsite": {"status": "failed", "error": str(exc)},
        }
        try:
            backup_store.merge_backup_verification_json(
                input.backup_id, failure, expected_activity_run_id=input.attempt_id or str(ctx.workflow_run_id),
            )
        finally:
            if input.owner_token:
                release_backup_lock(input.source_id, input.owner_token)
        return {"status": "failed", "backup_id": input.backup_id, "error": str(exc)}


@hatchet.task(
    name="summitflow-enrich",
    input_validator=EnrichInput,
    execution_timeout="300s",
    retries=2,
    backoff_factor=2.0,
)
async def enrich_wf(input: EnrichInput, ctx: Context) -> dict[str, Any]:
    from ..tasks.enrichment import enrich_task_async

    return await asyncio.to_thread(
        enrich_task_async, input.project_id, input.task_id, input.raw_request
    )


@hatchet.task(
    name="summitflow-pr-review",
    input_validator=ReviewPRInput,
    execution_timeout="900s",
    retries=3,
    backoff_factor=2.0,
)
async def pr_review_wf(input: ReviewPRInput, ctx: Context) -> dict[str, Any]:
    from ..tasks.ai_review import review_pull_request

    return await asyncio.to_thread(review_pull_request, input.task_id, input.pr_url)


@hatchet.task(
    name="summitflow-checkout-cleanup",
    input_validator=TaskInput,
    execution_timeout="180s",
    retries=3,
    backoff_factor=2.0,
    concurrency=ConcurrencyExpression(
        expression="input.task_id",
        max_runs=1,
        limit_strategy=ConcurrencyLimitStrategy.CANCEL_NEWEST,
    ),
)
async def checkpoint_cleanup_wf(input: TaskInput, ctx: Context) -> dict[str, Any]:
    from typing import cast

    from ..tasks.autonomous.cleanup import cleanup_task_checkpoint

    result = await asyncio.to_thread(cleanup_task_checkpoint, input.task_id, project_id=input.project_id)
    return cast(dict[str, Any], result)


@hatchet.task(
    name="summitflow-refactor-regen",
    input_validator=ProjectInput,
    execution_timeout="900s",
    retries=3,
    backoff_factor=2.0,
)
async def refactor_regen_wf(input: ProjectInput, ctx: Context) -> dict[str, Any]:
    from ..tasks.autonomous.task_generation import regenerate_refactor_tasks

    return await asyncio.to_thread(regenerate_refactor_tasks, input.project_id)


@hatchet.task(
    name="summitflow-schema-tasks",
    input_validator=ProjectInput,
    execution_timeout="600s",
    retries=3,
    backoff_factor=2.0,
)
async def schema_tasks_wf(input: ProjectInput, ctx: Context) -> dict[str, Any]:
    from ..tasks.autonomous.task_generation import generate_schema_tasks

    return await asyncio.to_thread(generate_schema_tasks, input.project_id)


@hatchet.task(
    name="summitflow-arch-tasks",
    input_validator=ProjectInput,
    execution_timeout="600s",
    retries=3,
    backoff_factor=2.0,
)
async def arch_tasks_wf(input: ProjectInput, ctx: Context) -> dict[str, Any]:
    from ..tasks.autonomous.task_generation import generate_architecture_tasks

    return await asyncio.to_thread(generate_architecture_tasks, input.project_id)


@hatchet.task(
    name="summitflow-check-resolved",
    input_validator=ProjectInput,
    execution_timeout="600s",
    retries=3,
    backoff_factor=2.0,
)
async def check_resolved_wf(input: ProjectInput, ctx: Context) -> dict[str, Any]:
    from ..tasks.explorer_tasks import check_resolved_issues

    return await asyncio.to_thread(check_resolved_issues, input.project_id)


@hatchet.task(
    name="summitflow-page-health",
    input_validator=ProjectInput,
    execution_timeout="1200s",
    retries=3,
    backoff_factor=2.0,
)
async def page_health_wf(input: ProjectInput, ctx: Context) -> dict[str, Any]:
    from ..tasks.explorer_tasks import run_page_health_checks

    return await asyncio.to_thread(run_page_health_checks, input.project_id)
