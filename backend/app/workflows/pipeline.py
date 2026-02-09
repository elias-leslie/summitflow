"""Pipeline workflows for autonomous task execution.

7 workflows: dispatch, triage, plan, execute, review, merge-cleanup, escalation.
Each is a thin async wrapper around existing business logic in tasks/.
"""

from __future__ import annotations

import asyncio
from typing import Any

from hatchet_sdk import ConcurrencyExpression, ConcurrencyLimitStrategy, Context

from ..hatchet_app import hatchet
from .models import TaskInput


async def _trigger_workflow(stage: str, task_id: str, project_id: str) -> None:
    """Trigger a downstream pipeline workflow by stage name."""
    workflow_map = {
        "triage": triage_wf,
        "plan": plan_wf,
        "execute": execute_wf,
        "review": review_wf,
        "merge": merge_cleanup_wf,
    }
    wf = workflow_map.get(stage)
    if wf:
        await wf.aio_run_no_wait(TaskInput(task_id=task_id, project_id=project_id))


def _make_dispatch_callback() -> Any:
    """Create a dispatch callback for use inside asyncio.to_thread."""
    def dispatch(stage: str, task_id: str, project_id: str) -> None:
        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(_trigger_workflow(stage, task_id, project_id))
        finally:
            loop.close()
    return dispatch


@hatchet.task(
    name="summitflow-dispatch",
    input_validator=TaskInput,
    execution_timeout="300s",
    retries=3,
    backoff_factor=2.0,
    concurrency=ConcurrencyExpression(
        expression="input.task_id",
        max_runs=1,
        limit_strategy=ConcurrencyLimitStrategy.CANCEL_IN_PROGRESS,
    ),
)
async def dispatch_wf(input: TaskInput, ctx: Context) -> dict[str, Any]:
    from ..tasks.autonomous.pickup import dispatch_task_immediate

    return await asyncio.to_thread(dispatch_task_immediate, input.task_id, input.project_id)


@hatchet.task(
    name="summitflow-triage",
    input_validator=TaskInput,
    execution_timeout="300s",
    retries=3,
    backoff_factor=2.0,
    concurrency=ConcurrencyExpression(
        expression="input.task_id",
        max_runs=1,
        limit_strategy=ConcurrencyLimitStrategy.CANCEL_IN_PROGRESS,
    ),
)
async def triage_wf(input: TaskInput, ctx: Context) -> dict[str, Any]:
    from ..tasks.autonomous.triage import triage_idea

    return await asyncio.to_thread(triage_idea, input.task_id, input.project_id)


@hatchet.task(
    name="summitflow-plan",
    input_validator=TaskInput,
    execution_timeout="600s",
    retries=3,
    backoff_factor=2.0,
    concurrency=ConcurrencyExpression(
        expression="input.task_id",
        max_runs=1,
        limit_strategy=ConcurrencyLimitStrategy.CANCEL_IN_PROGRESS,
    ),
)
async def plan_wf(input: TaskInput, ctx: Context) -> dict[str, Any]:
    from ..tasks.autonomous.planning import create_plan

    return await asyncio.to_thread(create_plan, input.task_id, input.project_id)


@hatchet.task(
    name="summitflow-execute",
    input_validator=TaskInput,
    execution_timeout="3600s",
    retries=2,
    backoff_factor=2.0,
    concurrency=ConcurrencyExpression(
        expression="input.task_id",
        max_runs=1,
        limit_strategy=ConcurrencyLimitStrategy.CANCEL_IN_PROGRESS,
    ),
)
async def execute_wf(input: TaskInput, ctx: Context) -> dict[str, Any]:
    from ..tasks.autonomous.execution import start_execution

    dispatch = _make_dispatch_callback()
    return await asyncio.to_thread(start_execution, input.task_id, input.project_id, dispatch=dispatch)


@hatchet.task(
    name="summitflow-review",
    input_validator=TaskInput,
    execution_timeout="600s",
    retries=3,
    backoff_factor=2.0,
    concurrency=ConcurrencyExpression(
        expression="input.task_id",
        max_runs=1,
        limit_strategy=ConcurrencyLimitStrategy.CANCEL_IN_PROGRESS,
    ),
)
async def review_wf(input: TaskInput, ctx: Context) -> dict[str, Any]:
    from ..tasks.autonomous.review import ai_review

    dispatch = _make_dispatch_callback()
    return await asyncio.to_thread(ai_review, input.task_id, input.project_id, dispatch=dispatch)


@hatchet.task(
    name="summitflow-merge-cleanup",
    input_validator=TaskInput,
    execution_timeout="300s",
    retries=3,
    backoff_factor=2.0,
)
async def merge_cleanup_wf(input: TaskInput, ctx: Context) -> dict[str, Any]:
    from ..tasks.autonomous.cleanup import merge_and_cleanup_task_worktree

    return await asyncio.to_thread(merge_and_cleanup_task_worktree, input.task_id, input.project_id)


@hatchet.task(
    name="summitflow-escalation",
    input_validator=TaskInput,
    execution_timeout="300s",
    retries=0,
)
async def escalation_wf(input: TaskInput, ctx: Context) -> dict[str, Any]:
    from ..tasks.autonomous.escalation import supervisor_guidance as supervisor_guidance_fn

    return await asyncio.to_thread(
        supervisor_guidance_fn,
        input.task_id,
        "",
        "",
        0,
        project_id=input.project_id,
    )
