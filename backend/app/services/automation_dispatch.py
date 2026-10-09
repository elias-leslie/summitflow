"""Accept Agent Hub runs through a durable SummitFlow outbox."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import shutil
import signal
import tempfile
from contextlib import suppress
from pathlib import Path
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from app.api.automation_dispatch import AutomationDispatchRequest
from app.services._agent_hub_config import get_async_client
from app.services.autonomous_policy import use_execution_policy
from app.storage import automation_dispatches

logger = logging.getLogger(__name__)


class BrowserWorkflowOutcomeUnknown(RuntimeError):
    """An invoked workflow may have acted without a verifiable owner receipt."""


def validate_browser_workflow_config(config: dict[str, Any]) -> None:
    """Validate owner-bound configuration before persisting an acceptance."""
    if set(config) - {"workflow", "parameters", "target"}:
        raise ValueError("Browser workflow config contains unsupported fields")
    workflow = config.get("workflow")
    if not isinstance(workflow, dict) or type(workflow.get("schema_version")) is not int or workflow["schema_version"] != 1:
        raise ValueError("Browser workflow requires an immutable schema_version 1 definition")
    if not isinstance(workflow.get("steps"), list) or not workflow["steps"]:
        raise ValueError("Browser workflow requires a nonempty steps array")
    if not isinstance(config.get("parameters", {}), dict):
        raise ValueError("Browser workflow parameters must be an object")
    if config.get("target", "local-ai") != "local-ai":
        raise ValueError("Browser workflows require the managed local-ai target")


def browser_automation_session(run_id: str) -> str:
    return "automation-" + hashlib.sha256(run_id.encode()).hexdigest()[:32]


async def _browser_command(project_id: str, run_id: str, arguments: list[str], *, timeout_seconds: float = 300) -> tuple[int, dict[str, Any]]:
    """Use the public facade without forking the ASGI worker; reap its group."""
    env = dict(os.environ)
    env["ST_BROWSER_OWNER"] = f"automation:{run_id}"
    env["ST_BROWSER_TARGET"] = "local-ai"
    executable = shutil.which("st", path=env.get("PATH"))
    if not executable:
        raise RuntimeError("The managed ST browser facade is unavailable")
    argv = [executable, "--project", project_id, "--no-compact", "browser", "--local-ai", *arguments]
    workflow_action = arguments[3] if len(arguments) > 3 and arguments[2] == "workflow" else None
    # Files avoid pipe backpressure and retain no browser content after return.
    # posix_spawn is the established web-worker-safe launch mechanism. A new
    # group lets cancellation terminate precisely this facade and its children.
    with tempfile.TemporaryFile(prefix="st-browser-receipt-") as output, open(os.devnull, "wb") as errors:
        pid = os.posix_spawn(executable, argv, env, setpgroup=0, file_actions=[
            (os.POSIX_SPAWN_DUP2, output.fileno(), 1),
            (os.POSIX_SPAWN_DUP2, errors.fileno(), 2),
        ])
        waiter = asyncio.create_task(asyncio.to_thread(os.waitpid, pid, 0))
        try:
            _pid, wait_status = await asyncio.wait_for(asyncio.shield(waiter), timeout=timeout_seconds)
        except BaseException as exc:
            with suppress(ProcessLookupError):
                os.killpg(pid, signal.SIGTERM)
            try:
                await asyncio.wait_for(asyncio.shield(waiter), timeout=5)
            except TimeoutError:
                with suppress(ProcessLookupError):
                    os.killpg(pid, signal.SIGKILL)
                await asyncio.shield(waiter)
            if isinstance(exc, TimeoutError) and workflow_action in {"run", "resume"}:
                raise BrowserWorkflowOutcomeUnknown("Browser workflow timed out; reconcile its checkpoint before continuing") from exc
            raise
        output.seek(0)
        stdout = output.read()
    try:
        result = json.loads(stdout)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        error = BrowserWorkflowOutcomeUnknown if workflow_action in {"run", "resume"} else RuntimeError
        raise error("Browser owner returned no structured receipt") from exc
    if not isinstance(result, dict):
        error = BrowserWorkflowOutcomeUnknown if workflow_action in {"run", "resume"} else RuntimeError
        raise error("Browser owner receipt must be an object")
    return os.waitstatus_to_exitcode(wait_status), result


async def execute_browser_workflow(receipt: dict[str, Any]) -> dict[str, Any]:
    """Run or reconcile one semantic workflow with its immutable automation actor."""
    run_id = receipt["run_id"]
    session = browser_automation_session(run_id)
    config = receipt["request_payload"]["config"]
    validate_browser_workflow_config(config)
    control = receipt.get("control_action")
    if control:
        action = control["action"]
        arguments = ["--session", session, "workflow", action, run_id]
        resolution = control.get("resolution")
        if resolution:
            arguments += ["--step", resolution["step"], "--resolution", resolution["outcome"]]
        code, result = await _browser_command(receipt["project_id"], run_id, arguments)
    else:
        code, _created = await _browser_command(receipt["project_id"], run_id, ["session", "create", session])
        if code:
            code, existing = await _browser_command(receipt["project_id"], run_id, ["session", "status", session])
            if code or existing.get("name") != session or existing.get("actor") != f"automation:{run_id}" or existing.get("state") not in {"active", "paused", "closed"}:
                raise RuntimeError("Existing automation session ownership could not be verified")
            # Recover a checkpoint left by a worker crash after the owner saved
            # it but before the outbox state advanced. Inspect before any action.
            code, checkpoint = await _browser_command(receipt["project_id"], run_id, ["--session", session, "workflow", "status", run_id])
            if code == 0:
                if checkpoint.get("status") == "running":
                    code, result = await _browser_command(receipt["project_id"], run_id, ["--session", session, "workflow", "resume", run_id])
                    return _validated_browser_result(code, result, run_id, session)
                return _validated_browser_result(code, checkpoint, run_id, session, inspected=True)
            if existing["state"] == "paused":
                raise RuntimeError("Paused automation session has no recoverable workflow checkpoint")
            if existing["state"] == "closed":
                code, _resumed = await _browser_command(receipt["project_id"], run_id, ["session", "resume", session])
                if code:
                    raise RuntimeError("Unable to resume the verified automation-owned session")
        # Temporary private files carry the admitted snapshot, never a mutable
        # caller pathname. The public facade retains its host policy checks.
        with tempfile.TemporaryDirectory(prefix="st-browser-workflow-") as directory:
            definition = Path(directory) / "definition.json"
            parameters = Path(directory) / "parameters.json"
            definition.write_text(json.dumps(config["workflow"]), encoding="utf-8")
            parameters.write_text(json.dumps(config.get("parameters", {})), encoding="utf-8")
            code, result = await _browser_command(
                receipt["project_id"], run_id,
                ["--session", session, "workflow", "run", "--file", str(definition),
                 "--parameters", str(parameters), "--run-id", run_id],
            )
    return _validated_browser_result(code, result, run_id, session)


def _validated_browser_result(code: int, result: dict[str, Any], run_id: str, session: str, *, inspected: bool = False) -> dict[str, Any]:
    if result.get("schema_version") != 1 or result.get("run_id") != run_id or result.get("session") != session:
        raise BrowserWorkflowOutcomeUnknown("Browser owner receipt does not match the automation run/session")
    expected_codes = {"complete": 0, "cancelled": 0, "waiting_human": 3, "failed": 2, "unknown": 2}
    owner_status = result.get("status")
    if owner_status not in expected_codes or code != (0 if inspected else expected_codes[owner_status]):
        raise BrowserWorkflowOutcomeUnknown("Browser owner returned an unsupported status/exit receipt")
    return result


def _browser_event(receipt: dict[str, Any], status: str) -> None:
    """Record a user-visible lifecycle event without delivering external messages."""
    from app.storage.events import create_event

    try:
        create_event(
            project_id=receipt["project_id"], trace_id=receipt["run_id"],
            event_type="browser_workflow", source="automation-owner",
            name=status, message=f"Browser workflow {status}",
            attributes={"run_id": receipt["run_id"], "owner_run_id": receipt["owner_run_id"],
                        "session": browser_automation_session(receipt["run_id"])},
        )
    except Exception:
        logger.warning("Browser workflow lifecycle event could not be recorded", exc_info=True)


async def control_browser_automation_run(run_id: str, control: dict[str, Any]) -> dict[str, Any]:
    receipt = automation_dispatches.request_browser_workflow_control(run_id, control)
    if receipt["status"] == "pending":
        await enqueue_automation_run(run_id, receipt["owner_run_id"])
        receipt = automation_dispatches.mark_automation_run_queued(run_id)
    if receipt["status"] == "running" and (receipt.get("control_action") or {}).get("action") == "cancel":
        delivered = await _deliver_running_browser_cancel(receipt)
        return {"owner_run_id": receipt["owner_run_id"], "status": "accepted",
                "receipt": {"cancel_requested": True, "delivery": "delivered" if delivered else "pending"}}
    if receipt["status"] == "cancelled":
        if receipt.get("completion_reported_at") is None:
            await _report_completion(receipt)
        return {"owner_run_id": receipt["owner_run_id"], "status": "cancelled"}
    return {"owner_run_id": receipt["owner_run_id"], "status": "accepted"}


async def _deliver_running_browser_cancel(receipt: dict[str, Any]) -> bool:
    """Deliver only the owner's durable marker, leaving the executing fence intact."""
    run_id = receipt["run_id"]
    session = browser_automation_session(run_id)
    try:
        code, result = await _browser_command(
            receipt["project_id"], run_id, ["--session", session, "workflow", "cancel", run_id],
            timeout_seconds=15,
        )
        if code or result.get("schema_version") != 1 or result.get("run_id") != run_id or result.get("session") != session:
            raise RuntimeError("Browser cancellation receipt identity is unverifiable")
        if result.get("status") not in {"complete", "cancelled"} and result.get("cancel_requested") is not True:
            raise RuntimeError("Browser owner did not persist cancellation intent")
        if result.get("status") == "cancelled" and (result.get("cleanup") or {}).get("closed") is True:
            # The owner acquired the session lease and confirmed closure. A
            # crashed or returning worker can now be settled without another
            # browser action; the original claim still fences the DB update.
            current = automation_dispatches.get_automation_run(run_id)
            if current and current["status"] == "running" and current.get("worker_run_id"):
                finished = automation_dispatches.finish_automation_run(
                    run_id, current["worker_run_id"], status="cancelled", result=result,
                )
                _browser_event(finished, "cancelled")
                await _report_completion(finished)
        return True
    except Exception as exc:
        # The request is already durable. A checkpoint may not exist yet;
        # the executing worker and the existing outbox retry delivery safely.
        logger.warning("Browser cancellation delivery awaits retry (%s)", type(exc).__name__)
        return False


async def _enqueue_pending_browser_cancel(receipt: dict[str, Any]) -> bool:
    if receipt["status"] != "pending" or (receipt.get("control_action") or {}).get("action") != "cancel":
        return False
    await enqueue_automation_run(receipt["run_id"], receipt["owner_run_id"])
    automation_dispatches.mark_automation_run_queued(receipt["run_id"])
    return True


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

    status = "accepted" if receipt["status"] in {"queued", "running", "waiting"} else receipt["status"]
    response = {"owner_run_id": receipt["owner_run_id"], "status": status}
    if request.workflow_key == "browser_workflow" and receipt.get("result"):
        response["receipt"] = receipt["result"]
    return response


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
    result: dict[str, Any] = {"pending": len(receipts), "enqueued": enqueued, "failures": failures}
    cancellations = automation_dispatches.list_browser_cancellation_requests(limit=min(limit, 10))
    if cancellations:
        delivered = 0
        for receipt in cancellations:
            if await _deliver_running_browser_cancel(receipt):
                delivered += 1
        result["cancellation_requests"] = len(cancellations)
        result["cancellations_delivered"] = delivered
    return result


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
    async with get_async_client(timeout=10.0, client_name="summitflow-automation-completion") as client:
        await client.complete_automation_run(receipt["run_id"], body, internal_secret=secret)
    automation_dispatches.mark_automation_completion_reported(receipt["run_id"])


async def _report_browser_wait(receipt: dict[str, Any]) -> None:
    secret = os.environ.get("INTERNAL_SERVICE_SECRET", "").strip()
    if not secret:
        raise RuntimeError("Agent Hub internal progress authentication is unavailable")
    async with get_async_client(timeout=10.0, client_name="summitflow-browser-workflow-progress") as client:
        await client.accept_automation_run(
            receipt["run_id"],
            {"owner_run_id": receipt["owner_run_id"], "receipt": receipt["result"]},
            internal_secret=secret,
        )


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
    if receipt["status"] == "waiting":
        await _report_browser_wait(receipt)
        return {"run_id": run_id, "status": "waiting_human", "result": receipt["result"]}

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
    if claimed["workflow_key"] != "browser_workflow" and policy.get(required_gate) is not True:
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
            if claimed["workflow_key"] == "browser_workflow":
                result = await execute_browser_workflow(claimed)
                current = automation_dispatches.get_automation_run(run_id)
                if current and current["status"] == "running" and (current.get("control_action") or {}).get("action") == "cancel" and (claimed.get("control_action") or {}).get("action") != "cancel":
                    # The owner invocation has released its session lease.
                    # Reconcile any intent delivered before its checkpoint
                    # existed, or racing a human/failed-read return.
                    result = await execute_browser_workflow(current)
            elif claimed["workflow_key"] == "work_pickup":
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
        if claimed["workflow_key"] == "browser_workflow" and result_status == "waiting_human":
            waiting = automation_dispatches.wait_automation_run(run_id, worker_run_id, result)
            _browser_event(waiting, "waiting_human")
            await _report_browser_wait(waiting)
            if await _enqueue_pending_browser_cancel(waiting):
                return {"run_id": run_id, "status": "cancellation_pending", "result": result}
            return {"run_id": run_id, "status": "waiting_human", "result": result}
        terminal_status = "skipped" if result_status in {"disabled", "skipped", "blocked"} else (
            "failed" if result_status in {"error", "failed", "unhealthy", "unknown"} else (
                "cancelled" if result_status == "cancelled" else "succeeded"
            )
        )
        finished = automation_dispatches.finish_automation_run(
            run_id,
            worker_run_id,
            status=terminal_status,
            result=dict(result),
        )
    except Exception as exc:
        # A progress-report failure must never convert a durable human wait to
        # terminal failure. Hatchet retries the receipt report without replay.
        current = automation_dispatches.get_automation_run(run_id)
        if current:
            if current["status"] in terminal:
                if current.get("completion_reported_at") is None:
                    await _report_completion(current)
                return {"run_id": run_id, "status": current["status"], "resumed_completion": True}
            if current["status"] == "waiting":
                raise
            if current["status"] in {"pending", "queued"} and (current.get("control_action") or {}).get("action") == "cancel":
                await _enqueue_pending_browser_cancel(current)
                return {"run_id": run_id, "status": "cancellation_pending"}
        if isinstance(exc, BrowserWorkflowOutcomeUnknown):
            result = {
                "schema_version": 1, "run_id": run_id,
                "session": browser_automation_session(run_id), "status": "waiting_human",
                "error": str(exc), "outcome": "unknown",
            }
            waiting = automation_dispatches.wait_automation_run(run_id, worker_run_id, result)
            _browser_event(waiting, "waiting_human")
            await _report_browser_wait(waiting)
            if await _enqueue_pending_browser_cancel(waiting):
                return {"run_id": run_id, "status": "cancellation_pending", "result": result}
            return {"run_id": run_id, "status": "waiting_human", "result": result}
        finished = automation_dispatches.finish_automation_run(
            run_id,
            worker_run_id,
            status="failed",
            error=f"{type(exc).__name__}: {exc}",
        )
        if await _enqueue_pending_browser_cancel(finished):
            return {"run_id": run_id, "status": "cancellation_pending"}
        await _report_completion(finished)
        raise

    if await _enqueue_pending_browser_cancel(finished):
        return {"run_id": run_id, "status": "cancellation_pending", "result": result}
    if claimed["workflow_key"] == "browser_workflow":
        _browser_event(finished, finished["status"])
    await _report_completion(finished)
    return {"run_id": run_id, "status": finished["status"], "result": result}
