"""Accept Agent Hub runs through a durable SummitFlow outbox."""

from __future__ import annotations

import asyncio
import os
from typing import Any
from uuid import NAMESPACE_URL, uuid5

import httpx

from app.api.automation_dispatch import AutomationDispatchRequest
from app.services._agent_hub_config import AGENT_HUB_URL, build_agent_hub_headers
from app.services.autonomous_policy import use_execution_policy
from app.storage import automation_dispatches


def _owner_run_id(run_id: str) -> str:
    """Derive a stable SummitFlow owner ID before enqueueing work."""
    return str(uuid5(NAMESPACE_URL, f"summitflow-agent-hub-automation:{run_id}"))


def _work_pickup_batch_limit(config: dict[str, Any]) -> int:
    """Read the AH typed limit, preserving 10 for profiles without one."""
    value = config.get("batch_limit", 10)
    if type(value) is not int or value < 1:
        raise ValueError("Agent Hub work-pickup batch_limit must be a positive integer")
    return value


async def enqueue_automation_run(run_id: str, owner_run_id: str) -> None:
    """Queue a receipt processor; DB claim logic dedupes repeated triggers."""
    from app.workflows.automation_dispatch import (
        AutomationOwnerRunInput,
        automation_owner_run_wf,
    )

    await automation_owner_run_wf.aio_run_no_wait(
        AutomationOwnerRunInput(run_id=run_id, owner_run_id=owner_run_id),
    )


async def accept_automation_dispatch(
    request: AutomationDispatchRequest,
) -> dict[str, Any]:
    """Persist the receipt, enqueue pending work, then acknowledge acceptance.

    If Hatchet does not accept the workflow, the durable receipt remains pending
    and the Agent Hub retry can resume the enqueue operation with the same IDs.
    Duplicate Hatchet deliveries compete for one DB claim in the owner worker.
    """
    payload = request.model_dump(mode="json")
    receipt = automation_dispatches.create_or_get_automation_run(
        payload,
        _owner_run_id(request.run_id),
    )

    if receipt["status"] == "pending":
        await enqueue_automation_run(request.run_id, receipt["owner_run_id"])
        receipt = automation_dispatches.mark_automation_run_queued(request.run_id)

    status = "accepted" if receipt["status"] in {"queued", "running"} else receipt["status"]
    return {"owner_run_id": receipt["owner_run_id"], "status": status}


async def reconcile_pending_automation_runs(limit: int = 50) -> dict[str, Any]:
    """Resume receipts left pending by a callback process crash."""
    receipts = automation_dispatches.list_pending_automation_runs(limit=limit)
    enqueued = 0
    failures: list[str] = []
    for receipt in receipts:
        try:
            await enqueue_automation_run(receipt["run_id"], receipt["owner_run_id"])
            automation_dispatches.mark_automation_run_queued(receipt["run_id"])
            enqueued += 1
        except Exception as exc:
            automation_dispatches.defer_pending_automation_run(receipt["run_id"])
            failures.append(f"{receipt['run_id']}: {type(exc).__name__}")
    return {"pending": len(receipts), "enqueued": enqueued, "failures": failures}


async def _report_completion(receipt: dict[str, Any]) -> None:
    secret = os.environ.get("INTERNAL_SERVICE_SECRET", "").strip()
    if not secret:
        raise RuntimeError("Agent Hub internal completion authentication is unavailable")
    result = receipt.get("result")
    body: dict[str, Any] = {
        "status": receipt["status"],
        "owner_run_id": receipt["owner_run_id"],
    }
    if receipt.get("error"):
        body["error"] = receipt["error"]
    if result is not None:
        body["receipt"] = result
    headers = build_agent_hub_headers(
        request_source="summitflow-automation-completion",
        extra_headers={"X-Agent-Hub-Internal": secret},
    )
    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.post(
            f"{AGENT_HUB_URL.rstrip('/')}/api/automations/runs/{receipt['run_id']}/complete",
            json=body,
            headers=headers,
        )
        response.raise_for_status()
    automation_dispatches.mark_automation_completion_reported(receipt["run_id"])


async def execute_automation_run(
    run_id: str,
    owner_run_id: str,
    *,
    worker_run_id: str,
) -> dict[str, Any]:
    """Claim and execute one durable receipt, then report terminal status to AH."""
    receipt = automation_dispatches.get_automation_run(run_id)
    if receipt is None or receipt["owner_run_id"] != owner_run_id:
        raise ValueError("Automation run receipt is missing or owner ID does not match")
    terminal = {"succeeded", "failed", "skipped", "cancelled"}
    if receipt["status"] in terminal:
        if receipt.get("completion_reported_at") is None:
            await _report_completion(receipt)
        return {"run_id": run_id, "status": receipt["status"], "resumed_completion": True}

    claimed = automation_dispatches.claim_automation_run(run_id, worker_run_id)
    if claimed is None:
        return {"run_id": run_id, "status": "claimed_elsewhere"}

    payload = claimed["request_payload"]
    policy = payload.get("policy_config")
    config = payload.get("config")
    if not isinstance(policy, dict) or not isinstance(config, dict):
        finished = automation_dispatches.finish_automation_run(
            run_id,
            worker_run_id,
            status="failed",
            error="Agent Hub policy/config snapshot is malformed",
        )
        await _report_completion(finished)
        return {"run_id": run_id, "status": "failed"}

    required_gate = "autonomous_enabled" if claimed["workflow_key"] == "work_pickup" else "routine_upkeep_enabled"
    if policy.get(required_gate) is not True:
        result = {
            "project_id": claimed["project_id"],
            "status": "disabled",
            "reason": f"{required_gate}_disabled",
        }
        finished = automation_dispatches.finish_automation_run(
            run_id,
            worker_run_id,
            status="skipped",
            result=result,
        )
        await _report_completion(finished)
        return {"run_id": run_id, "status": "skipped", "result": result}

    try:
        with use_execution_policy(policy):
            if claimed["workflow_key"] == "work_pickup":
                from app.tasks.autonomous.pickup import autonomous_work_pickup
                from app.workflows.pipeline import _make_dispatch_callback

                result = await asyncio.to_thread(
                    autonomous_work_pickup,
                    claimed["project_id"],
                    dispatch=_make_dispatch_callback(execution_policy=policy),
                    require_enabled=True,
                    limit=_work_pickup_batch_limit(config),
                    policy_config=policy,
                    agent_hub_owned=True,
                )
            elif claimed["workflow_key"] == "task_generation":
                from app.tasks.autonomous.upkeep import run_routine_upkeep

                result = await asyncio.to_thread(
                    run_routine_upkeep,
                    claimed["project_id"],
                    force=True,
                    policy_config=policy,
                    config=config,
                )
            else:
                raise ValueError("Unsupported Agent Hub workflow key")
        result_status = str(result.get("status") or "completed")
        terminal_status = "skipped" if result_status in {"disabled", "skipped", "blocked"} else (
            "failed" if result_status in {"error", "failed", "unhealthy"} else "succeeded"
        )
        finished = automation_dispatches.finish_automation_run(
            run_id,
            worker_run_id,
            status=terminal_status,
            result=dict(result),
        )
    except Exception as exc:
        finished = automation_dispatches.finish_automation_run(
            run_id,
            worker_run_id,
            status="failed",
            error=f"{type(exc).__name__}: {exc}",
        )
        await _report_completion(finished)
        raise

    await _report_completion(finished)
    return {"run_id": run_id, "status": finished["status"], "result": result}
