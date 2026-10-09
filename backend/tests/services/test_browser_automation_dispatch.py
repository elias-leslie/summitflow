"""Browser owner integration never replays an unresolved human checkpoint."""

import asyncio
import json
import os
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from app.services import automation_dispatch as service


def _receipt(status="queued", **changes):
    return {
        "run_id": "run-1", "owner_run_id": "owner-1", "project_id": "agent-hub",
        "workflow_key": "browser_workflow", "status": status, "control_action": None,
        "request_payload": {"config": {"workflow": {"schema_version": 1, "steps": [{"id": "check"}]}, "parameters": {"name": "hello"}}, "policy_config": {}},
        **changes,
    }


@pytest.mark.parametrize("config", [
    {"workflow": {}},
    {"workflow": {"schema_version": 1, "steps": []}},
    {"workflow": {"schema_version": True, "steps": [{}]}},
    {"workflow": {"schema_version": 1, "steps": [{}]}, "target": "proxmox"},
    {"workflow": {"schema_version": 1, "steps": [{}]}, "session": "st-local-ai"},
])
def test_invalid_workflow_config_fails_before_acceptance(config):
    with pytest.raises(ValueError):
        service.validate_browser_workflow_config(config)


@pytest.mark.asyncio
async def test_public_facade_uses_immutable_private_files_and_dedicated_session(mocker):
    receipt = _receipt()
    session = service.browser_automation_session(receipt["run_id"])
    result = {"schema_version": 1, "run_id": "run-1", "session": session, "status": "complete"}
    captured = []

    async def command(project, run_id, arguments):
        captured.append((project, run_id, arguments))
        if arguments[0] == "session":
            return 0, {"status": "created"}
        assert json.loads(Path(arguments[arguments.index("--file") + 1]).read_text()) == receipt["request_payload"]["config"]["workflow"]
        assert json.loads(Path(arguments[arguments.index("--parameters") + 1]).read_text()) == {"name": "hello"}
        return 0, result

    mocker.patch.object(service, "_browser_command", side_effect=command)
    assert await service.execute_browser_workflow(receipt) == result
    assert captured[0][2] == ["session", "create", session]
    assert captured[1][2][:4] == ["--session", session, "workflow", "run"]
    assert captured[1][2][-2:] == ["--run-id", "run-1"]
    assert session != "st-local-ai"
    assert session != service.browser_automation_session("run-2")


@pytest.mark.asyncio
async def test_resume_reconciles_checkpoint_without_replaying_definition(mocker):
    receipt = _receipt(control_action={"action": "resume", "resolution": {"step": "write", "outcome": "completed"}})
    session = service.browser_automation_session("run-1")
    command = mocker.patch.object(service, "_browser_command", return_value=(0, {"schema_version": 1, "run_id": "run-1", "session": session, "status": "complete"}))
    await service.execute_browser_workflow(receipt)
    command.assert_awaited_once_with("agent-hub", "run-1", ["--session", session, "workflow", "resume", "run-1", "--step", "write", "--resolution", "completed"])


@pytest.mark.asyncio
async def test_cancel_addresses_only_owned_run_and_session(mocker):
    session = service.browser_automation_session("run-1")
    command = mocker.patch.object(service, "_browser_command", return_value=(0, {"schema_version": 1, "run_id": "run-1", "session": session, "status": "cancelled"}))
    await service.execute_browser_workflow(_receipt(control_action={"action": "cancel"}))
    command.assert_awaited_once_with("agent-hub", "run-1", ["--session", session, "workflow", "cancel", "run-1"])


@pytest.mark.asyncio
async def test_mismatched_owner_receipt_fails_closed(mocker):
    mocker.patch.object(service, "_browser_command", side_effect=[(0, {}), (0, {"schema_version": 1, "run_id": "run-1", "session": "st-local-ai", "status": "complete"})])
    with pytest.raises(RuntimeError, match="run/session"):
        await service.execute_browser_workflow(_receipt())


@pytest.mark.asyncio
async def test_crash_retry_inspects_existing_owned_checkpoint_without_replay(mocker):
    session = service.browser_automation_session("run-1")
    waiting = {"schema_version": 1, "run_id": "run-1", "session": session, "status": "waiting_human"}
    command = mocker.patch.object(service, "_browser_command", side_effect=[
        (1, {"error": "already exists"}),
        (0, {"name": session, "actor": "automation:run-1", "state": "paused"}),
        (0, waiting),
    ])
    assert await service.execute_browser_workflow(_receipt()) == waiting
    assert command.call_args_list[-1].args[2] == ["--session", session, "workflow", "status", "run-1"]
    assert command.await_count == 3


@pytest.mark.asyncio
async def test_existing_session_with_another_actor_is_never_reclaimed(mocker):
    session = service.browser_automation_session("run-1")
    command = mocker.patch.object(service, "_browser_command", side_effect=[
        (1, {"error": "already exists"}),
        (0, {"name": session, "actor": "another-owner", "state": "closed"}),
    ])
    with pytest.raises(RuntimeError, match="ownership"):
        await service.execute_browser_workflow(_receipt())
    assert command.await_count == 2


@pytest.mark.asyncio
async def test_interrupted_checkpoint_uses_owner_resume_without_replaying_run(mocker):
    session = service.browser_automation_session("run-1")
    base = {"schema_version": 1, "run_id": "run-1", "session": session}
    command = mocker.patch.object(service, "_browser_command", side_effect=[
        (1, {}), (0, {"name": session, "actor": "automation:run-1", "state": "active"}),
        (0, {**base, "status": "running"}), (3, {**base, "status": "waiting_human"}),
    ])
    assert (await service.execute_browser_workflow(_receipt()))["status"] == "waiting_human"
    assert command.call_args_list[-1].args[2] == ["--session", session, "workflow", "resume", "run-1"]


@pytest.mark.asyncio
async def test_human_wait_releases_worker_and_keeps_agent_hub_nonterminal(mocker):
    receipt = _receipt()
    result = {"schema_version": 1, "run_id": "run-1", "session": service.browser_automation_session("run-1"), "status": "waiting_human", "checkpoint": "read"}
    mocker.patch.object(service.automation_dispatches, "get_automation_run", return_value=receipt)
    mocker.patch.object(service.automation_dispatches, "claim_automation_run", return_value=receipt)
    mocker.patch.object(service, "execute_browser_workflow", return_value=result)
    wait = mocker.patch.object(service.automation_dispatches, "wait_automation_run", return_value={**receipt, "status": "waiting", "result": result})
    report = mocker.patch.object(service, "_report_browser_wait", new_callable=AsyncMock)
    completion = mocker.patch.object(service, "_report_completion", new_callable=AsyncMock)
    finish = mocker.patch.object(service.automation_dispatches, "finish_automation_run")
    mocker.patch.object(service, "_browser_event")
    output = await service.execute_automation_run("run-1", "owner-1", worker_run_id="worker-1")
    assert output["status"] == "waiting_human"
    wait.assert_called_once_with("run-1", "worker-1", result)
    report.assert_awaited_once()
    completion.assert_not_awaited()
    finish.assert_not_called()


@pytest.mark.asyncio
async def test_wait_report_retry_does_not_execute_owner_again(mocker):
    receipt = _receipt("waiting", result={"status": "waiting_human"})
    mocker.patch.object(service.automation_dispatches, "get_automation_run", return_value=receipt)
    execute = mocker.patch.object(service, "execute_browser_workflow")
    claim = mocker.patch.object(service.automation_dispatches, "claim_automation_run")
    report = mocker.patch.object(service, "_report_browser_wait", new_callable=AsyncMock)
    assert (await service.execute_automation_run("run-1", "owner-1", worker_run_id="worker-2"))["status"] == "waiting_human"
    report.assert_awaited_once_with(receipt)
    execute.assert_not_called()
    claim.assert_not_called()


@pytest.mark.asyncio
async def test_unverifiable_execution_receipt_waits_for_reconciliation(mocker):
    receipt = _receipt()
    mocker.patch.object(service.automation_dispatches, "get_automation_run", return_value=receipt)
    mocker.patch.object(service.automation_dispatches, "claim_automation_run", return_value=receipt)
    mocker.patch.object(service, "execute_browser_workflow", side_effect=service.BrowserWorkflowOutcomeUnknown("Outcome unverifiable"))
    wait = mocker.patch.object(service.automation_dispatches, "wait_automation_run", side_effect=lambda _run, _worker, result: {**receipt, "status": "waiting", "result": result})
    finish = mocker.patch.object(service.automation_dispatches, "finish_automation_run")
    mocker.patch.object(service, "_report_browser_wait", new_callable=AsyncMock)
    mocker.patch.object(service, "_browser_event")
    result = await service.execute_automation_run("run-1", "owner-1", worker_run_id="worker-1")
    assert result["status"] == "waiting_human"
    assert result["result"]["outcome"] == "unknown"
    wait.assert_called_once()
    finish.assert_not_called()


@pytest.mark.asyncio
async def test_active_cancel_delivers_only_marker_without_replacing_worker(mocker):
    session = service.browser_automation_session("run-1")
    control = {"action": "cancel", "idempotency_key": "cancel-1"}
    receipt = _receipt("running", worker_run_id="worker-1", control_action=control)
    persist = mocker.patch.object(service.automation_dispatches, "request_browser_workflow_control", return_value=receipt)
    command = mocker.patch.object(service, "_browser_command", return_value=(0, {"schema_version": 1, "run_id": "run-1", "session": session, "status": "running", "cancel_requested": True}))
    enqueue = mocker.patch.object(service, "enqueue_automation_run")
    finish = mocker.patch.object(service.automation_dispatches, "finish_automation_run")
    report = mocker.patch.object(service, "_report_completion")
    result = await service.control_browser_automation_run("run-1", control)
    persist.assert_called_once_with("run-1", control)
    command.assert_awaited_once_with("agent-hub", "run-1", ["--session", session, "workflow", "cancel", "run-1"], timeout_seconds=15)
    assert result["status"] == "accepted"
    assert result["receipt"] == {"cancel_requested": True, "delivery": "delivered"}
    enqueue.assert_not_called()
    finish.assert_not_called()
    report.assert_not_called()


@pytest.mark.asyncio
async def test_cancel_before_owner_checkpoint_exists_remains_durable_for_retry(mocker):
    control = {"action": "cancel", "idempotency_key": "cancel-1"}
    receipt = _receipt("running", control_action=control)
    mocker.patch.object(service.automation_dispatches, "request_browser_workflow_control", return_value=receipt)
    mocker.patch.object(service, "_browser_command", return_value=(2, {"error": "checkpoint not yet created"}))
    result = await service.control_browser_automation_run("run-1", control)
    assert result["status"] == "accepted"
    assert result["receipt"]["delivery"] == "pending"


@pytest.mark.asyncio
async def test_existing_outbox_retries_running_cancel_marker_without_workflow_replay(mocker):
    control = {"action": "cancel", "idempotency_key": "cancel-1"}
    receipt = _receipt("running", control_action=control)
    mocker.patch.object(service.automation_dispatches, "list_pending_automation_runs", return_value=[])
    mocker.patch.object(service.automation_dispatches, "list_browser_cancellation_requests", return_value=[receipt])
    delivery = mocker.patch.object(service, "_deliver_running_browser_cancel", return_value=True)
    enqueue = mocker.patch.object(service, "enqueue_automation_run")
    result = await service.reconcile_pending_automation_runs()
    assert result["cancellations_delivered"] == 1
    delivery.assert_awaited_once_with(receipt)
    enqueue.assert_not_called()


@pytest.mark.asyncio
async def test_worker_reconciles_cancel_after_session_lease_is_released(mocker):
    receipt = _receipt()
    cancel = _receipt("running", worker_run_id="worker-1", control_action={"action": "cancel", "idempotency_key": "cancel-1"})
    mocker.patch.object(service.automation_dispatches, "get_automation_run", side_effect=[receipt, cancel])
    mocker.patch.object(service.automation_dispatches, "claim_automation_run", return_value=receipt)
    owner = mocker.patch.object(service, "execute_browser_workflow", side_effect=[{"status": "waiting_human"}, {"status": "cancelled"}])
    finish = mocker.patch.object(service.automation_dispatches, "finish_automation_run", return_value={**cancel, "status": "cancelled"})
    mocker.patch.object(service, "_browser_event")
    report = mocker.patch.object(service, "_report_completion", new_callable=AsyncMock)
    output = await service.execute_automation_run("run-1", "owner-1", worker_run_id="worker-1")
    assert output["status"] == "cancelled"
    assert owner.await_count == 2
    assert owner.call_args.args[0]["control_action"]["action"] == "cancel"
    finish.assert_called_once_with("run-1", "worker-1", status="cancelled", result={"status": "cancelled"})
    report.assert_awaited_once()


@pytest.mark.asyncio
async def test_owner_confirmed_cancel_settles_original_fence_after_session_closed(mocker):
    session = service.browser_automation_session("run-1")
    receipt = _receipt("running", worker_run_id="worker-1", control_action={"action": "cancel", "idempotency_key": "cancel-1"})
    result = {"schema_version": 1, "run_id": "run-1", "session": session, "status": "cancelled", "cancel_requested": True, "cleanup": {"closed": True}}
    mocker.patch.object(service, "_browser_command", return_value=(0, result))
    mocker.patch.object(service.automation_dispatches, "get_automation_run", return_value=receipt)
    finish = mocker.patch.object(service.automation_dispatches, "finish_automation_run", return_value={**receipt, "status": "cancelled", "result": result})
    report = mocker.patch.object(service, "_report_completion", new_callable=AsyncMock)
    mocker.patch.object(service, "_browser_event")
    assert await service._deliver_running_browser_cancel(receipt) is True
    finish.assert_called_once_with("run-1", "worker-1", status="cancelled", result=result)
    report.assert_awaited_once()


@pytest.mark.asyncio
async def test_late_worker_honors_terminal_cancel_and_does_not_replace_receipt(mocker):
    receipt = _receipt()
    cancelled = _receipt("cancelled", worker_run_id="worker-1", completion_reported_at="reported", result={"status": "cancelled"})
    mocker.patch.object(service.automation_dispatches, "get_automation_run", side_effect=[receipt, cancelled, cancelled])
    mocker.patch.object(service.automation_dispatches, "claim_automation_run", return_value=receipt)
    owner = mocker.patch.object(service, "execute_browser_workflow", return_value={"status": "complete"})
    finish = mocker.patch.object(service.automation_dispatches, "finish_automation_run", side_effect=RuntimeError("Automation run is not owned by this worker"))
    report = mocker.patch.object(service, "_report_completion")
    output = await service.execute_automation_run("run-1", "owner-1", worker_run_id="worker-1")
    assert output == {"run_id": "run-1", "status": "cancelled", "resumed_completion": True}
    owner.assert_awaited_once()
    finish.assert_called_once()
    report.assert_not_called()


@pytest.mark.asyncio
async def test_subprocess_actor_is_durable_automation_identity(mocker):
    def spawned(_executable, _arguments, _environment, **options):
        import os

        os.write(options["file_actions"][0][1], b'{"status":"complete"}')
        return 100

    mocker.patch.object(service.shutil, "which", return_value="/managed/bin/st")
    spawn = mocker.patch.object(service.os, "posix_spawn", side_effect=spawned)
    mocker.patch.object(service.os, "waitpid", return_value=(100, 0))
    await service._browser_command("agent-hub", "run-1", ["session", "create", "automation-one"])
    assert spawn.call_args.args[1][:7] == ["/managed/bin/st", "--project", "agent-hub", "--no-compact", "browser", "--local-ai", "session"]
    assert spawn.call_args.args[2]["ST_BROWSER_OWNER"] == "automation:run-1"
    assert spawn.call_args.kwargs["setpgroup"] == 0


@pytest.mark.asyncio
async def test_facade_process_cancellation_terminates_and_reaps_owned_group(mocker, tmp_path):
    executable = tmp_path / "synthetic-st"
    pid_file = tmp_path / "owned-pid"
    executable.write_text("#!/usr/bin/env python3\nimport os, time\nfrom pathlib import Path\nPath(" + repr(str(pid_file)) + ").write_text(str(os.getpid()))\ntime.sleep(30)\n")
    executable.chmod(0o700)
    mocker.patch.object(service.shutil, "which", return_value=str(executable))
    task = asyncio.create_task(service._browser_command("summitflow", "run-1", ["synthetic"]))
    for _attempt in range(100):
        if pid_file.exists():
            break
        if task.done():
            await task
        await asyncio.sleep(0.01)
    assert pid_file.exists()
    pid = int(pid_file.read_text())
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    with pytest.raises(ChildProcessError):
        os.waitpid(pid, os.WNOHANG)
