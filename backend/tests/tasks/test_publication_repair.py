"""Rolling repair evidence survives claims and out-of-order nightly callbacks."""
from unittest.mock import patch

import pytest

from app.storage import tasks
from app.storage.tasks.publication_repair import get_repair_task, record_finding


def test_rolling_repair_is_ready_for_normal_pickup(test_project_id, cleanup_task):
    from app.services.task_execution_readiness import load_task_execution_readiness
    from app.storage.subtasks import get_subtasks_for_task
    from app.storage.task_spirit import get_task_spirit

    task_id = record_finding(test_project_id, "codeql", {"observed_at": "2026-10-02T08:00:00+00:00"}, resolved=False)
    assert task_id is not None
    cleanup_task(task_id)
    readiness = load_task_execution_readiness(task_id)
    assert readiness.ready, readiness.issues
    spirit = get_task_spirit(task_id)
    assert spirit is not None and spirit["plan_status"] == "approved"
    assert len(get_subtasks_for_task(task_id)) == 1
    record_finding(test_project_id, "publication", {"observed_at": "2026-10-03T08:00:00+00:00"}, resolved=False)
    assert len(get_subtasks_for_task(task_id)) == 1


@pytest.mark.parametrize("interrupted_api", ["create_subtask", "approve_plan"])
def test_retry_recovers_partial_repair_initialization(test_project_id, cleanup_task, interrupted_api):
    from app.services.task_execution_readiness import load_task_execution_readiness
    from app.storage.subtasks import get_subtasks_for_task
    from app.storage.task_spirit import get_task_spirit

    module = "app.storage.subtasks" if interrupted_api == "create_subtask" else "app.storage.task_spirit"
    observation = {"observed_at": "2026-10-02T08:00:00+00:00"}
    with patch(f"{module}.{interrupted_api}", side_effect=RuntimeError("fixture interruption")), pytest.raises(RuntimeError):
        record_finding(test_project_id, "codeql", observation, resolved=False)
    partial = get_repair_task(test_project_id)
    assert partial is not None
    cleanup_task(partial["id"])
    assert record_finding(test_project_id, "codeql", observation, resolved=False) == partial["id"]
    assert load_task_execution_readiness(partial["id"]).ready
    spirit = get_task_spirit(partial["id"])
    assert spirit is not None and spirit["plan_status"] == "approved"
    assert len(get_subtasks_for_task(partial["id"])) == 1


def test_new_observation_preserves_owner_plan_revision(test_project_id, cleanup_task):
    from app.storage.task_spirit import get_task_spirit, set_plan_status

    task_id = record_finding(test_project_id, "codeql", {"observed_at": "2026-10-02T08:00:00+00:00"}, resolved=False)
    assert task_id is not None
    cleanup_task(task_id)
    set_plan_status(task_id, "draft", actor="owner", notes="Owner revising the repair plan")
    record_finding(test_project_id, "codeql", {"observed_at": "2026-10-03T08:00:00+00:00"}, resolved=False)
    spirit = get_task_spirit(task_id)
    assert spirit is not None and spirit["plan_status"] == "draft"


def test_rolling_findings_merge_and_preserve_newest_failure(test_project_id, cleanup_task):
    newer = {"observed_at": "2026-10-02T08:00:00+00:00", "source_commit": "a" * 40}
    older = {"observed_at": "2026-10-01T08:00:00+00:00", "source_commit": "b" * 40}
    task_id = record_finding(test_project_id, "publication", newer, resolved=False)
    assert task_id is not None
    cleanup_task(task_id)
    assert record_finding(test_project_id, "codeql", newer, resolved=False) == task_id
    assert record_finding(test_project_id, "publication", older, resolved=True) == task_id
    task = get_repair_task(test_project_id)
    assert task is not None
    assert task["execution_mode"] == "manual"
    assert task["verification_result"]["publication_repair"]["publication"]["state"] == "unresolved"
    tasks.update_task_status(task_id, "running")
    running = tasks.get_task(task_id)
    assert running is not None
    assert set(running["verification_result"]["publication_repair"]) == {"publication", "codeql"}
    assert record_finding(test_project_id, "publication", {**newer, "observed_at": "2026-10-03T08:00:00+00:00"}, resolved=True) == task_id
    stored = tasks.get_task(task_id)
    assert stored is not None
    assert stored["verification_result"]["publication_repair"]["codeql"]["state"] == "unresolved"


def test_success_without_existing_repair_does_not_create_task(test_project_id):
    assert record_finding(test_project_id, "publication", {"observed_at": "2026-10-02T08:00:00+00:00"}, resolved=True) is None


def test_claim_cannot_discard_findings(test_project_id, cleanup_task):
    task_id = record_finding(test_project_id, "codeql", {"observed_at": "2026-10-02T08:00:00+00:00"}, resolved=False)
    assert task_id is not None
    cleanup_task(task_id)
    claimed = tasks.claim_task(task_id, "fixture-worker")
    assert claimed is not None
    assert claimed["verification_result"]["publication_repair"]["codeql"]["state"] == "unresolved"


def test_cancel_or_delete_cannot_hide_independent_findings(test_project_id, cleanup_task):
    task_id = record_finding(test_project_id, "codeql", {"observed_at": "2026-10-02T08:00:00+00:00"}, resolved=False)
    assert task_id is not None
    cleanup_task(task_id)
    with pytest.raises(ValueError, match="unresolved repair"):
        tasks.update_task_status(task_id, "cancelled")
    with pytest.raises(ValueError, match="unresolved repair"):
        tasks.delete_task(task_id)
    assert get_repair_task(test_project_id) is not None
