"""Exercise migrations and browser outbox fencing in an isolated test schema."""

from __future__ import annotations

import importlib.util
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest
from psycopg import sql

from app.storage import automation_dispatches as store


def _migration(filename):
    path = Path(__file__).resolve().parents[2] / "alembic" / "versions" / filename
    spec = importlib.util.spec_from_file_location(filename[:-3], path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def isolated_receipts(test_db_url, mocker):
    schema = "test_browser_outbox_" + uuid4().hex
    connection = psycopg.connect(test_db_url.replace("postgresql+psycopg://", "postgresql://"))
    connection.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
    connection.execute(sql.SQL("SET search_path TO {}").format(sql.Identifier(schema)))
    migration = _migration("9ab4d2e6c810_add_automation_dispatch_receipts.py")
    mocker.patch.object(migration.op, "execute", side_effect=connection.execute)
    migration.upgrade()
    extension = _migration("c32e8b917a60_browser_workflow_automation.py")
    extension.upgrade()
    connection.commit()

    @contextmanager
    def get_connection():
        yield connection

    @contextmanager
    def get_cursor():
        with connection.cursor() as cursor:
            yield cursor

    mocker.patch.object(store, "get_connection", get_connection)
    mocker.patch.object(store, "get_cursor", get_cursor)
    try:
        yield connection, extension
    finally:
        connection.rollback()
        connection.execute("SET search_path TO public")
        connection.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))
        connection.commit()
        connection.close()


def _payload():
    return {
        "run_id": "browser-1", "profile_id": "profile-1", "project_id": "summitflow",
        "workflow_key": "browser_workflow", "definition_version": 1, "profile_revision": 2,
        "occurrence_key": "manual:browser-1", "trigger": "manual", "scheduled_for": "2026-10-02T14:00:00Z",
        "config": {"workflow": {"schema_version": 1, "steps": [{"id": "read"}]}}, "policy_config": {},
    }


def test_browser_receipt_identity_and_human_checkpoint_worker_fences(isolated_receipts):
    connection, _migration = isolated_receipts
    payload = _payload()
    first = store.create_or_get_automation_run(payload, "owner-1")
    assert first["status"] == "pending"
    assert store.create_or_get_automation_run(payload, "owner-1")["owner_run_id"] == "owner-1"
    with pytest.raises(ValueError, match="different callback envelope"):
        store.create_or_get_automation_run({**payload, "profile_revision": 3}, "owner-1")
    claimed = store.claim_automation_run("browser-1", "worker-1")
    assert claimed is not None and claimed["status"] == "running"
    assert store.claim_automation_run("browser-1", "worker-other") is None
    # A later enqueue acknowledgement cannot overwrite the active worker.
    assert store.mark_automation_run_queued("browser-1")["status"] == "running"
    with pytest.raises(RuntimeError, match="owned"):
        store.wait_automation_run("browser-1", "worker-other", {"status": "waiting_human"})
    waiting = store.wait_automation_run("browser-1", "worker-1", {"status": "waiting_human", "checkpoint": "read"})
    assert waiting["worker_run_id"] is None
    assert waiting["completed_at"] is None
    assert store.claim_automation_run("browser-1", "worker-1") is None
    control = {"action": "resume", "resolution": {"step": "read", "outcome": "completed"}, "idempotency_key": "resume-1"}
    queued = store.request_browser_workflow_control("browser-1", control)
    assert queued["status"] == "pending"
    assert queued["request_payload"] == payload
    assert store.request_browser_workflow_control("browser-1", control)["control_action"] == control
    with pytest.raises(ValueError, match="another action"):
        store.request_browser_workflow_control("browser-1", {"action": "cancel", "idempotency_key": "resume-1"})
    connection.rollback()
    claimed = store.claim_automation_run("browser-1", "worker-2")
    assert claimed is not None
    assert claimed["control_action"] == control
    with pytest.raises(ValueError, match="waiting human"):
        store.request_browser_workflow_control("browser-1", {"action": "resume", "idempotency_key": "resume-2"})
    connection.rollback()
    with pytest.raises(RuntimeError, match="owned"):
        store.finish_automation_run("browser-1", "worker-1", status="cancelled")
    finished = store.finish_automation_run("browser-1", "worker-2", status="succeeded", result={"status": "complete"})
    assert finished["control_action"] is None
    assert finished["completed_at"] is not None
    assert store.claim_automation_run("browser-1", "worker-3") is None


def test_control_retry_cannot_resume_a_later_human_wait(isolated_receipts):
    store.create_or_get_automation_run(_payload(), "owner-1")
    store.claim_automation_run("browser-1", "worker-1")
    store.wait_automation_run("browser-1", "worker-1", {"status": "waiting_human", "checkpoint": "first"})
    control = {"action": "resume", "idempotency_key": "human-1"}
    store.request_browser_workflow_control("browser-1", control)
    store.claim_automation_run("browser-1", "worker-2")
    store.wait_automation_run("browser-1", "worker-2", {"status": "waiting_human", "checkpoint": "second"})
    retry = store.request_browser_workflow_control("browser-1", control)
    assert retry["status"] == "waiting"
    assert retry["result"]["checkpoint"] == "second"
    assert retry["control_action"] is None


def test_queued_cancel_fences_worker_without_creating_a_browser(isolated_receipts):
    store.create_or_get_automation_run(_payload(), "owner-1")
    store.mark_automation_run_queued("browser-1")
    control = {"action": "cancel", "idempotency_key": "cancel-1"}
    cancelled = store.request_browser_workflow_control("browser-1", control)
    assert cancelled["status"] == "cancelled"
    assert cancelled["completed_at"] is not None
    assert store.claim_automation_run("browser-1", "worker-1") is None
    assert store.request_browser_workflow_control("browser-1", control)["status"] == "cancelled"


def test_running_cancel_preserves_worker_fence_and_wait_race_preserves_intent(isolated_receipts):
    store.create_or_get_automation_run(_payload(), "owner-1")
    store.claim_automation_run("browser-1", "worker-1")
    control = {"action": "cancel", "idempotency_key": "cancel-active"}
    requested = store.request_browser_workflow_control("browser-1", control)
    assert requested["status"] == "running"
    assert requested["worker_run_id"] == "worker-1"
    assert requested["completed_at"] is None
    assert store.claim_automation_run("browser-1", "worker-other") is None
    assert store.list_browser_cancellation_requests()[0]["control_action"] == control
    pending = store.wait_automation_run("browser-1", "worker-1", {"status": "waiting_human"})
    assert pending["status"] == "pending"
    assert pending["control_action"] == control
    assert pending["worker_run_id"] is None
    claimed = store.claim_automation_run("browser-1", "worker-cancel")
    assert claimed is not None and claimed["control_action"] == control
    finished = store.finish_automation_run("browser-1", "worker-cancel", status="cancelled")
    assert finished["status"] == "cancelled"
    assert store.list_browser_cancellation_requests() == []


def test_failed_read_racing_active_cancel_queues_cleanup_instead_of_losing_intent(isolated_receipts):
    store.create_or_get_automation_run(_payload(), "owner-1")
    store.claim_automation_run("browser-1", "worker-1")
    control = {"action": "cancel", "idempotency_key": "cancel-active"}
    store.request_browser_workflow_control("browser-1", control)
    result = store.finish_automation_run("browser-1", "worker-1", status="failed", result={"status": "failed"})
    assert result["status"] == "pending"
    assert result["completed_at"] is None
    assert result["worker_run_id"] is None
    assert result["control_action"] == control
    assert result["request_payload"] == _payload()


def test_migration_downgrade_preserves_unresolved_browser_receipts(isolated_receipts):
    connection, migration = isolated_receipts
    store.create_or_get_automation_run(_payload(), "owner-1")
    with pytest.raises(psycopg.errors.CheckViolation):
        migration.downgrade()
    connection.rollback()
    receipt = store.get_automation_run("browser-1")
    assert receipt is not None and receipt["status"] == "pending"


def test_migration_downgrade_is_reversible_before_browser_runs(isolated_receipts):
    connection, migration = isolated_receipts
    migration.downgrade()
    connection.commit()
    payload = {**_payload(), "workflow_key": "work_pickup", "config": {}}
    # The old schema still accepts old workflow rows after a safe downgrade.
    with connection.cursor() as cursor:
        cursor.execute("SELECT column_name FROM information_schema.columns WHERE table_schema = current_schema() AND table_name = 'automation_dispatch_receipts'")
        assert "control_action" not in {row[0] for row in cursor.fetchall()}
    migration.upgrade()
    assert store.create_or_get_automation_run(payload, "owner-legacy")["workflow_key"] == "work_pickup"
