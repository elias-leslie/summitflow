"""Hatchet owner workflow for accepted Agent Hub automation runs."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from hatchet_sdk import ConcurrencyExpression, ConcurrencyLimitStrategy, Context
from pydantic import BaseModel, ConfigDict

from ..hatchet_app import hatchet


class AutomationOwnerRunInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: str
    owner_run_id: str


class AutomationOutboxInput(BaseModel):
    model_config = ConfigDict(extra="forbid")


@hatchet.task(
    name="summitflow-agent-hub-automation-owner",
    input_validator=AutomationOwnerRunInput,
    execution_timeout=timedelta(minutes=10),
    retries=5,
    backoff_factor=2.0,
)
async def automation_owner_run_wf(input: AutomationOwnerRunInput, ctx: Context) -> dict[str, Any]:
    from ..services.automation_dispatch import execute_automation_run

    return await execute_automation_run(
        input.run_id,
        input.owner_run_id,
        worker_run_id=str(ctx.workflow_run_id),
    )


@hatchet.task(
    name="summitflow-agent-hub-automation-outbox-reconcile",
    input_validator=AutomationOutboxInput,
    execution_timeout=timedelta(minutes=5),
    on_crons=["*/2 * * * *"],
    retries=1,
    concurrency=ConcurrencyExpression(
        expression="'summitflow-agent-hub-automation-outbox-reconcile'",
        max_runs=1,
        limit_strategy=ConcurrencyLimitStrategy.CANCEL_IN_PROGRESS,
    ),
)
async def automation_outbox_reconcile_wf(input: AutomationOutboxInput, ctx: Context) -> dict[str, Any]:
    """Retry durable callback receipts whose first enqueue was interrupted."""
    from ..services.automation_dispatch import reconcile_pending_automation_runs

    return await reconcile_pending_automation_runs()
