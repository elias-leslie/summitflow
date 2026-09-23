"""Pipeline workflows for autonomous task execution.

6 workflows: dispatch, triage, plan, execute, review, escalation.
Each is a thin async wrapper around existing business logic in tasks/.
"""

from __future__ import annotations

import asyncio
from functools import wraps
from typing import Any

from hatchet_sdk import ConcurrencyExpression, ConcurrencyLimitStrategy, Context

from ..hatchet_app import hatchet
from ..logging_config import get_logger
from ..services.autonomous_policy import use_execution_policy
from .automation_dispatch import automation_owner_run_wf as _automation_owner_run_wf  # noqa: F401
from .models import TaskInput

logger = get_logger(__name__)

# Worker imports this module's pipeline tasks; import the owner callback task so
# it is registered in the same Hatchet worker process.


def _with_execution_policy(function: Any) -> Any:
    @wraps(function)
    async def wrapped(input: TaskInput, ctx: Context) -> dict[str, Any]:
        with use_execution_policy(input.execution_policy):
            return await function(input, ctx)

    return wrapped


async def _trigger_workflow(
    stage: str,
    task_id: str,
    project_id: str,
    *,
    manual_dispatch: bool = False,
    execution_policy: dict[str, Any] | None = None,
) -> None:
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
        "critique": critique_wf,
        "execute": execute_wf,
        "review": review_wf,
    }
    wf = workflow_map.get(stage)
    if wf:
        await wf.aio_run_no_wait(
            TaskInput(
                task_id=task_id,
                project_id=project_id,
                manual_dispatch=manual_dispatch,
                execution_policy=execution_policy,
            )
        )
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


def _make_dispatch_callback(
    *,
    manual_dispatch: bool = False,
    execution_policy: dict[str, Any] | None = None,
) -> Any:
    """Create a dispatch callback for use inside asyncio.to_thread."""
    def dispatch(stage: str, task_id: str, project_id: str) -> None:
        loop = asyncio.new_event_loop()
        try:
            try:
                trigger_kwargs: dict[str, Any] = {"manual_dispatch": manual_dispatch}
                if execution_policy is not None:
                    trigger_kwargs["execution_policy"] = execution_policy
                loop.run_until_complete(
                    _trigger_workflow(
                        stage,
                        task_id,
                        project_id,
                        **trigger_kwargs,
                    )
                )
            except ValueError:
                raise
            except Exception:
                logger.exception("dispatch_callback_failed", stage=stage, task_id=task_id)
                raise
        finally:
            loop.close()
    return dispatch


async def _drain_project_queue_after_execution(
    project_id: str,
    *,
    manual_dispatch: bool,
    execution_policy: dict[str, Any] | None = None,
) -> None:
    """Start queued autonomous work after a task frees project capacity."""
    from ..tasks.autonomous.pickup import autonomous_work_pickup

    callback_kwargs: dict[str, Any] = {"manual_dispatch": manual_dispatch}
    if execution_policy is not None:
        callback_kwargs["execution_policy"] = execution_policy
    dispatch = _make_dispatch_callback(**callback_kwargs)
    pickup_kwargs: dict[str, Any] = {
        "dispatch": dispatch,
        "require_enabled": not manual_dispatch,
    }
    if execution_policy is not None:
        pickup_kwargs.update(policy_config=execution_policy, agent_hub_owned=True)
    try:
        result = await asyncio.to_thread(
            autonomous_work_pickup,
            project_id,
            **pickup_kwargs,
        )
        logger.info("execution_queue_drain_complete", project_id=project_id, result=result)
    except Exception:
        logger.exception("execution_queue_drain_failed", project_id=project_id)


@hatchet.task(
    name="summitflow-dispatch",
    input_validator=TaskInput,
    retries=3,
    backoff_factor=2.0,
    concurrency=ConcurrencyExpression(
        expression="input.task_id",
        max_runs=1,
        limit_strategy=ConcurrencyLimitStrategy.CANCEL_IN_PROGRESS,
    ),
)
@_with_execution_policy
async def dispatch_wf(input: TaskInput, ctx: Context) -> dict[str, Any]:
    from ..tasks.autonomous.pickup import dispatch_task_immediate

    callback_kwargs: dict[str, Any] = {"manual_dispatch": input.manual_dispatch}
    if input.execution_policy is not None:
        callback_kwargs["execution_policy"] = input.execution_policy
    dispatch = _make_dispatch_callback(**callback_kwargs)
    return await asyncio.to_thread(
        dispatch_task_immediate,
        input.task_id,
        input.project_id,
        dispatch,
    )


@hatchet.task(
    name="summitflow-ideate",
    input_validator=TaskInput,
    retries=3,
    backoff_factor=2.0,
    concurrency=ConcurrencyExpression(
        expression="input.task_id",
        max_runs=1,
        limit_strategy=ConcurrencyLimitStrategy.CANCEL_IN_PROGRESS,
    ),
)
@_with_execution_policy
async def ideate_wf(input: TaskInput, ctx: Context) -> dict[str, Any]:
    from ..tasks.autonomous.ideation import ideate_task

    result = await asyncio.to_thread(ideate_task, input.task_id, input.project_id)

    # Auto-advance to triage on success
    if result.get("status") == "ideated":
        await _trigger_workflow("triage", input.task_id, input.project_id, manual_dispatch=input.manual_dispatch, execution_policy=input.execution_policy)

    return result


@hatchet.task(
    name="summitflow-triage",
    input_validator=TaskInput,
    retries=3,
    backoff_factor=2.0,
    concurrency=ConcurrencyExpression(
        expression="input.task_id",
        max_runs=1,
        limit_strategy=ConcurrencyLimitStrategy.CANCEL_IN_PROGRESS,
    ),
)
@_with_execution_policy
async def triage_wf(input: TaskInput, ctx: Context) -> dict[str, Any]:
    from ..tasks.autonomous.triage import triage_idea

    result = await asyncio.to_thread(triage_idea, input.task_id, input.project_id)

    # Auto-advance on success: determine next stage (planning, critique, or execution)
    if result.get("status") == "completed":
        from ..tasks.autonomous.pickup import _determine_next_stage

        _STAGE_TO_WF = {"planning": "plan", "critique": "critique", "execution": "execute"}
        next_stage = _determine_next_stage(input.task_id)
        wf_stage = _STAGE_TO_WF.get(next_stage)
        if wf_stage:
            await _trigger_workflow(wf_stage, input.task_id, input.project_id, manual_dispatch=input.manual_dispatch, execution_policy=input.execution_policy)

    return result


@hatchet.task(
    name="summitflow-plan",
    input_validator=TaskInput,
    retries=3,
    backoff_factor=2.0,
    concurrency=ConcurrencyExpression(
        expression="input.task_id",
        max_runs=1,
        limit_strategy=ConcurrencyLimitStrategy.CANCEL_IN_PROGRESS,
    ),
)
@_with_execution_policy
async def plan_wf(input: TaskInput, ctx: Context) -> dict[str, Any]:
    from ..tasks.autonomous.planning import create_plan

    result = await asyncio.to_thread(create_plan, input.task_id, input.project_id)

    # Auto-advance after planning based on the refreshed readiness state.
    if result.get("status") == "completed":
        from ..tasks.autonomous.pickup import _determine_next_stage

        _STAGE_TO_WF = {"critique": "critique", "execution": "execute"}
        next_stage = _determine_next_stage(input.task_id)
        wf_stage = _STAGE_TO_WF.get(next_stage)
        if wf_stage:
            await _trigger_workflow(wf_stage, input.task_id, input.project_id, manual_dispatch=input.manual_dispatch, execution_policy=input.execution_policy)

    return result


@hatchet.task(
    name="summitflow-critique",
    input_validator=TaskInput,
    retries=3,
    backoff_factor=2.0,
    concurrency=ConcurrencyExpression(
        expression="input.task_id",
        max_runs=1,
        limit_strategy=ConcurrencyLimitStrategy.CANCEL_IN_PROGRESS,
    ),
)
@_with_execution_policy
async def critique_wf(input: TaskInput, ctx: Context) -> dict[str, Any]:
    from ..tasks.autonomous.critique import run_task_shape_critique

    result = await asyncio.to_thread(run_task_shape_critique, input.task_id, input.project_id)

    if result.get("status") == "completed":
        verdict = str(result.get("verdict") or "").upper()
        if verdict == "APPROVED":
            await _trigger_workflow("execute", input.task_id, input.project_id, manual_dispatch=input.manual_dispatch, execution_policy=input.execution_policy)
        elif verdict == "NEEDS_REVISION":
            logger.info(
                "Task-shape critique parked for revision",
                task_id=input.task_id,
                project_id=input.project_id,
            )

    return result


@hatchet.task(
    name="summitflow-execute",
    input_validator=TaskInput,
    retries=2,
    backoff_factor=2.0,
    concurrency=ConcurrencyExpression(
        expression="input.task_id",
        max_runs=1,
        limit_strategy=ConcurrencyLimitStrategy.CANCEL_IN_PROGRESS,
    ),
)
@_with_execution_policy
async def execute_wf(input: TaskInput, ctx: Context) -> dict[str, Any]:
    from ..storage import tasks as task_store
    from ..tasks.autonomous.execution import start_execution
    from ..tasks.autonomous.pickup_guards import validate_autonomous_dispatch

    task = task_store.get_task(input.task_id) or {}
    task_type = str(task.get("task_type") or "").strip() or None
    claimed_by = str(task.get("claimed_by") or "").strip()
    preclaimed_execution = claimed_by.startswith(("pickup-", "dispatch-"))
    if input.manual_dispatch:
        guard_error = validate_autonomous_dispatch(
            input.project_id,
            task_type,
            require_enabled=False,
            exclude_task_id=input.task_id,
            skip_concurrency=preclaimed_execution,
        )
    else:
        guard_error = validate_autonomous_dispatch(
            input.project_id,
            task_type,
            external_origin=task.get("external_origin"),
            exclude_task_id=input.task_id,
            skip_concurrency=preclaimed_execution,
        )
    if guard_error:
        status = str(guard_error.get("status") or "blocked")
        logger.warning(
            "Execution workflow blocked by autonomous guard",
            task_id=input.task_id,
            project_id=input.project_id,
            status=status,
            details=guard_error,
        )
        task_store.release_task(input.task_id)
        return {
            "task_id": input.task_id,
            "project_id": input.project_id,
            "stage": "execution",
            "status": status,
            "details": guard_error,
        }

    policy_kwargs: dict[str, Any] = {"execution_policy": input.execution_policy} if input.execution_policy is not None else {}
    dispatch = _make_dispatch_callback(**policy_kwargs)
    result = await asyncio.to_thread(start_execution, input.task_id, input.project_id, dispatch=dispatch)
    drain_kwargs: dict[str, Any] = {"manual_dispatch": input.manual_dispatch}
    if input.execution_policy is not None:
        drain_kwargs["execution_policy"] = input.execution_policy
    await _drain_project_queue_after_execution(input.project_id, **drain_kwargs)
    return result


@hatchet.task(
    name="summitflow-review",
    input_validator=TaskInput,
    retries=3,
    backoff_factor=2.0,
    concurrency=ConcurrencyExpression(
        expression="input.task_id",
        max_runs=1,
        limit_strategy=ConcurrencyLimitStrategy.CANCEL_IN_PROGRESS,
    ),
)
@_with_execution_policy
async def review_wf(input: TaskInput, ctx: Context) -> dict[str, Any]:
    from ..tasks.autonomous.review import ai_review

    policy_kwargs: dict[str, Any] = {"execution_policy": input.execution_policy} if input.execution_policy is not None else {}
    dispatch = _make_dispatch_callback(**policy_kwargs)
    return await asyncio.to_thread(ai_review, input.task_id, input.project_id, dispatch=dispatch)


@hatchet.task(
    name="summitflow-escalation",
    input_validator=TaskInput,
    retries=0,
)
@_with_execution_policy
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
