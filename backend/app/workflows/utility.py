"""Utility (on-demand) workflows for SummitFlow.

10 workflows for backup/restore, enrichment, PR review, worktree cleanup,
and post-scan task generation.
"""

from __future__ import annotations

import asyncio
from typing import Any

from hatchet_sdk import ConcurrencyExpression, ConcurrencyLimitStrategy, Context

from ..hatchet_app import hatchet
from .models import (
    BackupInput,
    EnrichInput,
    ProjectInput,
    RestoreInput,
    ReviewPRInput,
    TaskInput,
)


@hatchet.task(
    name="summitflow-backup-create",
    input_validator=BackupInput,
    execution_timeout="900s",
    retries=0,
    concurrency=ConcurrencyExpression(
        expression="input.project_id",
        max_runs=1,
        limit_strategy=ConcurrencyLimitStrategy.CANCEL_IN_PROGRESS,
    ),
)
async def backup_create_wf(input: BackupInput, ctx: Context) -> dict[str, Any]:
    from ..tasks.backup import create_backup

    return await asyncio.to_thread(
        create_backup,
        input.project_id,
        input.note,
        input.backup_type,
        input.keep_local,
        input.retention_days,
    )


@hatchet.task(
    name="summitflow-backup-restore",
    input_validator=RestoreInput,
    execution_timeout="2100s",
    retries=2,
    backoff_factor=2.0,
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
    )


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
    name="summitflow-worktree-cleanup",
    input_validator=TaskInput,
    execution_timeout="180s",
    retries=3,
    backoff_factor=2.0,
)
async def worktree_cleanup_wf(input: TaskInput, ctx: Context) -> dict[str, Any]:
    from typing import cast

    from ..tasks.autonomous.cleanup import cleanup_task_worktree

    result = await asyncio.to_thread(cleanup_task_worktree, input.task_id)
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
