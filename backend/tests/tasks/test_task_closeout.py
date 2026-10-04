"""Local continuation protects accepted source and lifecycle without remote I/O."""
from unittest.mock import Mock

import pytest

from app.services import task_closeout as closeout
from app.storage import tasks
from app.storage.tasks.closeout import (
    closeout_lock,
    finish_closeout_cleanup,
    retire_remote_closeout,
    store_closeout,
    store_execution_verification,
    store_owned_acceptance,
    store_verification,
)

SHA = "a" * 40


def stored_task(task_id: str) -> dict:
    value = tasks.get_task(task_id)
    assert value is not None
    return value


def stored_closeout(task_id: str) -> dict:
    value = closeout.get_closeout(task_id)
    assert value is not None
    return value


@pytest.fixture
def pending_task(test_project_id, cleanup_task, monkeypatch, tmp_path):
    task = tasks.create_task(test_project_id, "Resume exact-source local closeout")
    cleanup_task(task["id"])
    tasks.update_task(task["id"], verification_result={
        "independent": {"retained": True}, "acceptance": {"state": "success", "source_commit": SHA},
        "publication": {"ci": {"state": "failed"}},
    })
    closeout.request_closeout(task["id"], test_project_id, source_sha=SHA, message="Finish tested work")
    monkeypatch.setattr("app.storage.projects.get_project_root_path", lambda _: str(tmp_path))
    monkeypatch.setattr("cli.lib.acceptance.validate_acceptance_receipt", Mock())
    from contextlib import nullcontext
    monkeypatch.setattr("cli.lib.acceptance.repo_lock", lambda *a, **kw: nullcontext())
    monkeypatch.setattr("cli.client.STClient", Mock())
    monkeypatch.setattr("cli.commands.done_task._auto_verify_readiness", Mock())
    monkeypatch.setattr("cli.commands.done_task._selected_work_is_clean", lambda *a, **kw: True)
    monkeypatch.setattr("cli.commands.done_task_acceptance.require_scope_matches_revision", Mock())
    monkeypatch.setattr("cli.commands.done_task._capture_and_remove_snapshot", Mock())
    monkeypatch.setattr("cli.commands.done._release_task_leases", Mock())
    monkeypatch.setattr("cli.lib.publish_workflow.publish_git", Mock(side_effect=AssertionError("No remote publication")))
    monkeypatch.setattr("cli.lib.commit_workflow.commit_repo", Mock(side_effect=AssertionError("No later work checkpoint")))
    return task


def test_local_completion_preserves_remote_history_and_unrelated_work(pending_task, tmp_path):
    (tmp_path / "later-work").write_text("uncommitted")
    tid = pending_task["id"]
    assert closeout.resume_closeout(tid)["action"] == "completed"
    assert closeout.resume_closeout(tid)["action"] == "completed"
    stored = stored_task(tid)
    assert stored["status"] == "completed"
    verification = stored["verification_result"]
    assert verification["independent"] == {"retained": True}
    assert verification["publication"]["ci"]["state"] == "failed"
    assert verification["closeout"]["source_sha"] == SHA
    assert verification["closeout"]["state"] == "complete"
    assert (tmp_path / "later-work").read_text() == "uncommitted"


def test_cleanup_failure_retains_completed_source_for_explicit_recovery(pending_task, monkeypatch):
    cleanup = Mock(side_effect=RuntimeError("snapshot store unavailable"))
    monkeypatch.setattr("cli.commands.done_task._capture_and_remove_snapshot", cleanup)
    tid = pending_task["id"]
    assert closeout.resume_closeout(tid)["action"] == "blocked"
    assert stored_task(tid)["status"] == "completed"
    assert closeout.resume_closeout(tid)["action"] == "blocked"
    assert cleanup.call_count == 1
    cleanup.side_effect = None
    assert closeout.resume_closeout(tid, explicit=True)["action"] == "completed"


def test_changed_acceptance_source_cannot_close(pending_task):
    store_verification(pending_task["id"], pending_task["project_id"], {"acceptance": {"state": "success", "source_commit": "b" * 40}})
    result = closeout.resume_closeout(pending_task["id"])
    assert result["action"] == "blocked"
    assert "acceptance source changed" in result["reason"]
    assert stored_task(pending_task["id"])[ "status"] == "pending"


def test_pause_at_final_status_boundary_cannot_resurrect_completion(pending_task, monkeypatch):
    monkeypatch.setattr("cli.commands.done_task._auto_verify_readiness", lambda *_: tasks.update_task_status(pending_task["id"], "paused"))
    assert closeout.resume_closeout(pending_task["id"])["action"] == "skipped"
    assert stored_task(pending_task["id"])[ "status"] == "paused"


def test_source_change_at_final_status_boundary_is_revision_protected(pending_task, monkeypatch):
    monkeypatch.setattr("cli.commands.done_task._auto_verify_readiness", lambda *_: store_verification(
        pending_task["id"], pending_task["project_id"], {"acceptance": {"state": "success", "source_commit": "b" * 40}}))
    assert closeout.resume_closeout(pending_task["id"])["action"] == "blocked"
    assert stored_task(pending_task["id"])[ "status"] == "pending"


def test_concurrent_continuation_preserves_inflight_request(pending_task):
    with closeout_lock(pending_task["id"]) as acquired:
        assert acquired
        assert closeout.resume_closeout(pending_task["id"])["reason"] == "closeout_in_progress"


def test_cleanup_guard_rejects_superseded_request_without_touching_metadata(pending_task):
    tasks.update_task_status(pending_task["id"], "completed", validate_transition=False)
    cleanup = Mock()
    assert not finish_closeout_cleanup(pending_task["id"], pending_task["project_id"], "other-request", SHA, cleanup)
    cleanup.assert_not_called()


def test_completed_cleanup_tolerates_later_work_without_reacceptance(pending_task, monkeypatch):
    tasks.update_task_status(pending_task["id"], "completed", validate_transition=False)
    validator = Mock(side_effect=AssertionError("Accepted status needs metadata cleanup only"))
    monkeypatch.setattr("cli.lib.acceptance.validate_acceptance_receipt", validator)
    assert closeout.resume_closeout(pending_task["id"])["action"] == "completed"
    validator.assert_not_called()


def test_completed_request_does_not_report_reopened_task_complete(pending_task):
    intent = stored_closeout(pending_task["id"])
    intent["state"] = "complete"
    store_closeout(pending_task["id"], pending_task["project_id"], intent)
    result = closeout.resume_closeout(pending_task["id"])
    assert result["action"] == "skipped"
    assert stored_task(pending_task["id"])["status"] == "pending"


def test_lifecycle_invalidates_local_request_without_losing_its_history(pending_task):
    tid = pending_task["id"]
    before = stored_closeout(tid)
    tasks.claim_task(tid, "fixture-worker")
    stored = stored_closeout(tid)
    assert stored["kind"] == "lifecycle_closeout_history.v1"
    assert stored["previous_closeout"] == before
    assert closeout.resume_closeout(tid, explicit=True)["action"] == "skipped"


def test_execution_facts_preserve_independent_receipts(pending_task):
    tid = pending_task["id"]
    store_execution_verification(tid, pending_task["project_id"], {"execution_clean": True, "subtask_count": 1})
    verification = stored_task(tid)["verification_result"]
    assert verification["execution_clean"] is True
    assert verification["acceptance"]["source_commit"] == SHA
    assert verification["closeout"]["kind"] == "local_closeout.v1"


def test_legacy_remote_intent_is_inert_and_retirement_preserves_history(pending_task):
    tid = pending_task["id"]
    legacy = {"request_id": "old", "state": "pending", "source_sha": SHA,
              "project_id": pending_task["project_id"], "require_remote_confirmation": True,
              "publication": {"ci": {"state": "failed"}}}
    store_closeout(tid, pending_task["project_id"], legacy)
    assert closeout.resume_closeout(tid, explicit=True)["action"] == "skipped"
    assert not retire_remote_closeout(tid, pending_task["project_id"], expected_closeout={**legacy, "state": "blocked"})
    assert retire_remote_closeout(tid, pending_task["project_id"], expected_closeout=legacy)
    stored = stored_task(tid)
    assert stored["status"] == "pending"
    intent = stored["verification_result"]["closeout"]
    assert intent["state"] == "retired" and intent["reason"] == "no_longer_required"
    assert intent["previous_closeout"] == legacy
    assert stored["verification_result"]["acceptance"]["source_commit"] == SHA
    assert not retire_remote_closeout(tid, pending_task["project_id"], expected_closeout=legacy)


def test_retirement_cannot_target_local_cleanup(pending_task):
    with pytest.raises(ValueError, match="legacy remote"):
        retire_remote_closeout(pending_task["id"], pending_task["project_id"], expected_closeout=stored_closeout(pending_task["id"]))


def test_selected_work_changed_after_request_cannot_close(pending_task, monkeypatch):
    monkeypatch.setattr("cli.commands.done_task._selected_work_is_clean", lambda *a, **kw: False)
    result = closeout.resume_closeout(pending_task["id"])
    assert result["action"] == "blocked"
    assert "Selected task paths changed" in result["reason"]
    assert stored_task(pending_task["id"])[ "status"] == "pending"


def test_historical_owned_revision_drift_is_checked_again_at_closeout(pending_task, monkeypatch):
    checker = Mock(side_effect=ValueError("Task-owned source changed since the selected acceptance revision"))
    monkeypatch.setattr("cli.commands.done_task_acceptance.require_scope_matches_revision", checker)
    result = closeout.resume_closeout(pending_task["id"])
    assert result["action"] == "blocked"
    assert "Task-owned source changed" in result["reason"]
    assert stored_task(pending_task["id"])["status"] == "pending"
    checker.assert_called_once()


def test_request_creation_is_source_and_previous_intent_protected(pending_task, monkeypatch):
    tid = pending_task["id"]
    previous = stored_closeout(tid)
    previous["state"] = "retired"
    store_closeout(tid, pending_task["project_id"], previous)
    original_store = closeout.store_closeout

    def change_source_then_store(*args, **kwargs):
        store_verification(tid, pending_task["project_id"], {"acceptance": {"state": "success", "source_commit": "b" * 40}})
        return original_store(*args, **kwargs)

    monkeypatch.setattr(closeout, "store_closeout", change_source_then_store)
    result = closeout.request_closeout(tid, pending_task["project_id"], source_sha=SHA, message="done")
    assert result["reason"] == "completion_request_superseded"
    assert closeout.get_closeout(tid) == previous


@pytest.mark.parametrize("change", ["none", "acceptance", "paused", "reclaimed", "expired"])
def test_check_proof_attachment_is_exact_claim_and_evidence_protected(pending_task, change):
    tid = pending_task["id"]
    tasks.claim_task(tid, "fixture-worker", lock_duration_minutes=-1 if change == "expired" else 30)
    before = stored_task(tid)
    previous = before["verification_result"]["acceptance"]
    receipt = {"state": "success", "source_commit": SHA, "acceptance_id": "new-proof"}
    if change == "acceptance":
        store_verification(tid, before["project_id"], {"acceptance": {"state": "success", "source_commit": "b" * 40}})
    elif change in {"paused", "reclaimed"}:
        tasks.update_task_status(tid, "paused")
        if change == "reclaimed":
            tasks.claim_task(tid, "fixture-worker")
    attached = store_owned_acceptance(tid, before["project_id"], receipt,
        expected_worker="fixture-worker", expected_claimed_at=before["claimed_at"], expected_acceptance=previous)
    assert attached is (change == "none")
    after = stored_task(tid)
    if attached:
        assert after["verification_result"]["acceptance"] == receipt
        assert after["verification_result"]["publication"]["ci"]["state"] == "failed"
    else:
        assert after["verification_result"]["acceptance"] != receipt
