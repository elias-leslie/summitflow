"""Local completion evidence and intent stay with the claim that ran the gates."""
import subprocess
import sys
from copy import deepcopy
from unittest.mock import Mock

import pytest
import typer

from app.storage import tasks
from app.storage.tasks.closeout import store_verification
from cli.commands import done, done_task

SHA = "a" * 40


def stored_task(task_id: str) -> dict:
    task = tasks.get_task(task_id)
    assert task is not None
    return task


@pytest.fixture
def completion_task(test_project_id, cleanup_task, monkeypatch, tmp_path, local_gate_tools):
    task = tasks.create_task(test_project_id, "Accept owned source")
    cleanup_task(task["id"])
    tasks.claim_task(task["id"], "worker-A")
    monkeypatch.setattr("cli.lib.task_claims.current_worker_id", lambda: "worker-A")
    monkeypatch.setattr("cli.lib.task_claims.renew_local_owned_claim", lambda root, tid: stored_task(tid))
    monkeypatch.setattr(done_task, "get_project_root_path", lambda _: str(tmp_path))
    for args in (("init", "-q"), ("config", "user.name", "Fixture"),
                 ("config", "user.email", "fixture@example.invalid"), ("config", "core.hooksPath", "/dev/null")):
        subprocess.run(["git", *args], cwd=tmp_path, check=True)
    (tmp_path / "owned.py").write_text("value = 1\n")
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-qm", "owned source"], cwd=tmp_path, check=True)
    run = subprocess.run

    def gate(command, *args, **kwargs):
        if command[0] == sys.executable and len(command) > 3 and "from cli.main import app; app()" in command[3]:
            return subprocess.CompletedProcess(command, 0, "RUFF:OK:0", "")
        return run(command, *args, **kwargs)

    monkeypatch.setattr(subprocess, "run", gate)
    return stored_task(task["id"])


def test_clean_foreign_owner_is_refused_before_acceptance(completion_task, monkeypatch):
    tid = completion_task["id"]
    tasks.update_task_status(tid, "paused")
    tasks.claim_task(tid, "worker-B")
    gate = Mock(side_effect=AssertionError("Foreign claim must be refused first"))
    monkeypatch.setattr("cli.lib.acceptance.accept_revision", gate)
    with pytest.raises(ValueError, match="not actively owned"):
        done_task._accept_completed_work(tid, completion_task["project_id"], paths=("owned.py",))
    gate.assert_not_called()
    assert not (stored_task(tid)["verification_result"] or {}).get("acceptance")


@pytest.mark.parametrize("replacement_worker", ["worker-A", "worker-B"])
def test_reclaim_during_acceptance_does_not_attach_or_request(completion_task, monkeypatch, replacement_worker):
    tid, pid = completion_task["id"], completion_task["project_id"]
    newer = {"state": "success", "source_commit": "b" * 40}

    def reclaim():
        tasks.update_task_status(tid, "paused")
        tasks.claim_task(tid, replacement_worker)
        store_verification(tid, pid, {"acceptance": newer})
    run = subprocess.run

    def raced_gate(command, *args, **kwargs):
        if command[0] == sys.executable and len(command) > 3 and "from cli.main import app; app()" in command[3]:
            reclaim()
        return run(command, *args, **kwargs)

    monkeypatch.setattr(subprocess, "run", raced_gate)
    with pytest.raises(ValueError, match="changed while validating"):
        done_task._accept_completed_work(tid, pid, paths=("owned.py",))
    after = stored_task(tid)
    assert after["verification_result"]["acceptance"] == newer
    assert "closeout" not in after["verification_result"]
    assert after["status"] == "running" and after["claimed_by"] == replacement_worker


def test_same_owner_proof_and_durable_request_succeed(completion_task, monkeypatch):
    tid, pid = completion_task["id"], completion_task["project_id"]
    receipt = done_task._accept_completed_work(tid, pid, paths=("owned.py",))
    monkeypatch.setattr("app.services.task_closeout.resume_closeout", Mock(return_value={"action": "pending"}))
    assert done_task._finish_local_completion(tid, pid, message="done", paths=("owned.py",), receipt=receipt)["action"] == "pending"
    stored = stored_task(tid)
    assert stored["verification_result"]["acceptance"] == dict(receipt)
    assert stored["verification_result"]["closeout"]["kind"] == "local_closeout.v1"
    assert "completion_claim" not in stored["verification_result"]["acceptance"]


def test_reclaim_after_acceptance_before_intent_is_refused(completion_task):
    tid, pid = completion_task["id"], completion_task["project_id"]
    receipt = done_task._accept_completed_work(tid, pid, paths=("owned.py",))
    tasks.update_task_status(tid, "paused")
    tasks.claim_task(tid, "worker-A")
    store_verification(tid, pid, {"acceptance": dict(receipt)})
    with pytest.raises(ValueError, match="same active claim"):
        done_task._finish_local_completion(tid, pid, message="done", paths=("owned.py",), receipt=receipt)
    assert "closeout" not in stored_task(tid)["verification_result"]


@pytest.mark.parametrize("change", ["foreign", "during_import"])
def test_evidence_import_cannot_overwrite_foreign_claim(completion_task, monkeypatch, tmp_path, change):
    tid, pid = completion_task["id"], completion_task["project_id"]
    newer = {"source_commit": "b" * 40}

    def reclaim():
        tasks.update_task_status(tid, "paused")
        tasks.claim_task(tid, "worker-B")
        store_verification(tid, pid, {"deployment": newer})

    if change == "foreign":
        reclaim()
    client = Mock()
    client.get_task.return_value = deepcopy(stored_task(tid))
    monkeypatch.setattr(done, "preflight", Mock())
    monkeypatch.setattr("app.storage.projects.get_project_root_path", lambda _: str(tmp_path))
    complete = Mock(side_effect=AssertionError("Rejected import cannot continue completion"))
    monkeypatch.setattr(done, "complete_task", complete)

    def load(*a, **kw):
        if change == "during_import":
            reclaim()
        return {"deployment": {"source_commit": SHA}}

    monkeypatch.setattr("cli.lib.completion_evidence.load_completion_evidence", load)
    with pytest.raises(typer.Exit):
        done._handle_task_completion(client, tid, "done", evidence=tmp_path / "bundle.json")
    complete.assert_not_called()
    assert stored_task(tid)["verification_result"]["deployment"] == newer


@pytest.mark.parametrize("key", ["deployment", "live_validation"])
def test_selected_evidence_change_after_acceptance_cannot_create_intent(completion_task, key):
    tid, pid = completion_task["id"], completion_task["project_id"]
    receipt = done_task._accept_completed_work(tid, pid, paths=("owned.py",))
    newer = {"source_commit": "b" * 40}
    store_verification(tid, pid, {key: newer})
    result = done_task._finish_local_completion(tid, pid, message="done", paths=("owned.py",), receipt=receipt)
    assert result["reason"] == "completion_request_superseded"
    stored = stored_task(tid)
    assert "closeout" not in stored["verification_result"]
    assert stored["verification_result"][key] == newer


def stored_subtask(task_id: str, subtask_id: str) -> dict:
    from app.storage.subtasks import get_subtask

    subtask = get_subtask(task_id, subtask_id)
    assert subtask is not None
    return subtask


@pytest.fixture
def record_only_task(completion_task, monkeypatch):
    from app.storage.subtasks import get_subtasks_for_task

    tid = completion_task["id"]
    client = Mock()
    client.get_task.side_effect = lambda _: stored_task(tid)
    client.export_task_data.return_value = {"task": {"context": {"work_kind": "read_only"}}}
    client.get_subtasks.side_effect = lambda _: {"subtasks": get_subtasks_for_task(tid)}
    client.get_task_completion_readiness.return_value = {"ready": True}
    monkeypatch.setattr(done_task, "get_snapshot_info", lambda _: None)
    monkeypatch.setattr(done_task, "is_working_tree_clean", lambda _: True)
    cleanup = Mock()
    monkeypatch.setattr(done_task, "_capture_and_remove_snapshot", cleanup)
    monkeypatch.setattr(done_task, "commit_repo", Mock(side_effect=AssertionError("Record-only work has no code commit")))
    return completion_task, client, cleanup


@pytest.mark.parametrize("snapshot", [False, True])
def test_record_only_foreign_owner_cannot_close_or_cleanup(record_only_task, monkeypatch, snapshot):
    task, client, cleanup = record_only_task
    tid, pid = task["id"], task["project_id"]
    tasks.update_task_status(tid, "paused")
    tasks.claim_task(tid, "worker-B")
    if snapshot:
        monkeypatch.setattr(done_task, "get_snapshot_info", lambda _: {"project_id": pid, "base_branch": "main"})
    with pytest.raises(typer.Exit):
        done_task.complete_task(client, tid, admin=True)
    assert stored_task(tid)["status"] == "running"
    assert stored_task(tid)["claimed_by"] == "worker-B"
    client.get_subtasks.assert_not_called()
    client.close_task.assert_not_called()
    cleanup.assert_not_called()


@pytest.mark.parametrize("change", ["foreign", "reclaimed", "expired", "renewed"])
def test_record_only_claim_change_during_readiness_is_atomic(record_only_task, monkeypatch, change):
    task, client, cleanup = record_only_task
    tid, pid = task["id"], task["project_id"]
    monkeypatch.setattr(done_task, "get_snapshot_info", lambda _: {"project_id": pid, "base_branch": "main"})
    changed = False

    def readiness(_):
        nonlocal changed
        if not changed:
            changed = True
            if change in {"foreign", "reclaimed"}:
                tasks.update_task_status(tid, "paused")
                tasks.claim_task(tid, "worker-B" if change == "foreign" else "worker-A")
            else:
                tasks.renew_task_claim(tid, "worker-A", lock_duration_minutes=60 if change == "renewed" else -1)
        return {"ready": True}

    client.get_task_completion_readiness.side_effect = readiness
    if change == "renewed":
        assert done_task.complete_task(client, tid, admin=True)["action"] == "completed"
        assert stored_task(tid)["status"] == "completed"
        cleanup.assert_called_once()
    else:
        with pytest.raises(typer.Exit):
            done_task.complete_task(client, tid, admin=True)
        assert stored_task(tid)["status"] == "running"
        cleanup.assert_not_called()
    client.close_task.assert_not_called()


@pytest.mark.parametrize("snapshot", [False, True])
def test_record_only_current_owner_completes_subtasks_without_citations(record_only_task, monkeypatch, snapshot):
    from app.storage.subtasks import create_subtask

    task, client, cleanup = record_only_task
    tid, pid = task["id"], task["project_id"]
    create_subtask(tid, "1.1", "Review evidence", 1)
    create_subtask(tid, "1.2", "Record review", 2, depends_on=["1.1"])
    if snapshot:
        monkeypatch.setattr(done_task, "get_snapshot_info", lambda _: {"project_id": pid, "base_branch": "main"})
    assert done_task.complete_task(client, tid, admin=True)["action"] == "completed"
    assert stored_task(tid)["status"] == "completed"
    assert stored_subtask(tid, "1.1")["passes"] is True
    assert stored_subtask(tid, "1.2")["passes"] is True
    client.acknowledge_no_citations.assert_not_called()
    client.update_subtask.assert_not_called()
    client.close_task.assert_not_called()
    assert cleanup.call_count == int(snapshot)


def test_record_only_pending_unclaimed_requires_claim(record_only_task):
    task, client, cleanup = record_only_task
    tid = task["id"]
    tasks.release_task(tid)
    with pytest.raises(typer.Exit):
        done_task.complete_task(client, tid, admin=True)
    after = stored_task(tid)
    assert after["status"] == "pending" and after["claimed_by"] is None
    client.get_subtasks.assert_not_called()
    client.close_task.assert_not_called()
    cleanup.assert_not_called()


@pytest.mark.parametrize("sync", [False, True])
def test_record_only_reclaim_before_prerequisite_write_preserves_new_worker(record_only_task, monkeypatch, sync):
    from app.storage.subtasks import create_subtask

    task, client, cleanup = record_only_task
    tid = task["id"]
    create_subtask(tid, "1.1", "Review evidence", 1)
    changed = False

    def subtasks(_):
        nonlocal changed
        if not changed:
            changed = True
            tasks.update_task_status(tid, "paused")
            tasks.claim_task(tid, "worker-B")
        subtask = stored_subtask(tid, "1.1")
        if sync:
            subtask = {**subtask, "steps": [{"step_number": 1, "passes": True}], "citations_acknowledged_at": True}
        return {"subtasks": [subtask]}

    client.get_subtasks.side_effect = subtasks
    with pytest.raises(typer.Exit):
        done_task.complete_task(client, tid, admin=True)
    assert stored_subtask(tid, "1.1")["passes"] is False
    assert stored_task(tid)["status"] == "running" and stored_task(tid)["claimed_by"] == "worker-B"
    cleanup.assert_not_called()
    client.update_subtask.assert_not_called()


def test_completed_record_only_checkpoint_cleanup_needs_no_new_claim(record_only_task, monkeypatch):
    task, client, cleanup = record_only_task
    tid, pid = task["id"], task["project_id"]
    tasks.update_task_status(tid, "completed")
    monkeypatch.setattr(done_task, "get_snapshot_info", lambda _: {"project_id": pid, "base_branch": "main"})
    before = stored_task(tid)
    assert done_task.complete_task(client, tid, admin=True)["action"] == "completed"
    assert stored_task(tid)["verification_result"] == before["verification_result"]
    assert stored_task(tid)["claimed_by"] is None
    client.get_task_completion_readiness.assert_not_called()
    client.close_task.assert_not_called()
    cleanup.assert_called_once()
