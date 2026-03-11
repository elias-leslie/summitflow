"""Pipeline workflows for autonomous task execution.

7 workflows: dispatch, triage, plan, execute, review, merge-cleanup, escalation.
Each is a thin async wrapper around existing business logic in tasks/.
"""

from __future__ import annotations

import asyncio
from typing import Any

from hatchet_sdk import ConcurrencyExpression, ConcurrencyLimitStrategy, Context

from ..hatchet_app import hatchet
from ..logging_config import get_logger
from .models import TaskInput

logger = get_logger(__name__)


async def _trigger_workflow(stage: str, task_id: str, project_id: str) -> None:
    """Trigger a downstream workflow by stage name.

    Supports both pipeline stages and utility/post-scan stages.
    For pipeline stages, task_id is the actual task ID.
    For post-scan stages, project_id is used (task_id may be empty).
    """
    from .models import ProjectInput

    workflow_map = {
        "ideate": ideate_wf,
        "triage": triage_wf,
        "plan": plan_wf,
        "execute": execute_wf,
        "review": review_wf,
        "merge": merge_cleanup_wf,
    }
    wf = workflow_map.get(stage)
    if wf:
        await wf.aio_run_no_wait(TaskInput(task_id=task_id, project_id=project_id))
        return

    # Post-scan utility workflows (keyed by project_id)
    from .scheduled import task_generation_wf
    from .utility import (
        arch_tasks_wf,
        check_resolved_wf,
        schema_tasks_wf,
    )

    utility_map = {
        "generate_tasks": task_generation_wf,
        "schema_tasks": schema_tasks_wf,
        "architecture_tasks": arch_tasks_wf,
        "check_resolved": check_resolved_wf,
    }
    util_wf = utility_map.get(stage)
    if util_wf:
        await util_wf.aio_run_no_wait(ProjectInput(project_id=project_id))
        return

    raise ValueError(f"Unknown workflow stage: {stage}")


def _make_dispatch_callback() -> Any:
    """Create a dispatch callback for use inside asyncio.to_thread."""
    def dispatch(stage: str, task_id: str, project_id: str) -> None:
        loop = asyncio.new_event_loop()
        try:
            try:
                loop.run_until_complete(_trigger_workflow(stage, task_id, project_id))
            except Exception:
                logger.exception("dispatch_callback_failed", stage=stage, task_id=task_id)
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
    name="summitflow-ideate",
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
async def ideate_wf(input: TaskInput, ctx: Context) -> dict[str, Any]:
    from ..tasks.autonomous.ideation import ideate_task

    result = await asyncio.to_thread(ideate_task, input.task_id, input.project_id)

    # Auto-advance to triage on success
    if result.get("status") == "ideated":
        await _trigger_workflow("triage", input.task_id, input.project_id)

    return result


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

    result = await asyncio.to_thread(triage_idea, input.task_id, input.project_id)

    # Auto-advance on success: determine next stage (planning or execution)
    if result.get("status") == "completed":
        from ..tasks.autonomous.pickup import _determine_next_stage

        _STAGE_TO_WF = {"planning": "plan", "execution": "execute"}
        next_stage = _determine_next_stage(input.task_id)
        wf_stage = _STAGE_TO_WF.get(next_stage)
        if wf_stage:
            await _trigger_workflow(wf_stage, input.task_id, input.project_id)

    return result


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

    result = await asyncio.to_thread(create_plan, input.task_id, input.project_id)

    # Auto-advance to execution on success
    if result.get("status") == "completed":
        await _trigger_workflow("execute", input.task_id, input.project_id)

    return result


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
    from typing import cast

    from ..tasks.autonomous.cleanup import merge_and_cleanup_task_worktree

    result = await asyncio.to_thread(merge_and_cleanup_task_worktree, input.task_id, input.project_id)
    return cast(dict[str, Any], result)


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
