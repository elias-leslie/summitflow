"""Rolling repair evidence survives claims and out-of-order nightly callbacks."""
import subprocess
from unittest.mock import patch

import psycopg
import pytest
from psycopg.types.json import Jsonb

from app.storage import tasks
from app.storage.tasks import publication_repair as repair
from app.storage.tasks.publication_repair import get_repair_task, record_finding
from app.utils import safe_subprocess


@pytest.fixture
def source_history(tmp_path, monkeypatch):
    def git(*arguments):
        return subprocess.run(["git", *arguments], cwd=tmp_path, check=True,
                              capture_output=True, text=True).stdout.strip()

    git("init", "-q", "--initial-branch=main")
    git("config", "user.name", "Fixture")
    git("config", "user.email", "fixture@example.invalid")
    git("config", "core.hooksPath", "/dev/null")
    for value in ("base", "failed", "fixed"):
        (tmp_path / "source.txt").write_text(value)
        git("add", "source.txt")
        git("commit", "-qm", value)
    fixed = git("rev-parse", "HEAD")
    failed = git("rev-parse", "HEAD^")
    base = git("rev-parse", "HEAD^^")
    git("checkout", "--detach", base)
    (tmp_path / "source.txt").write_text("different branch")
    git("commit", "-qam", "divergent")
    divergent = git("rev-parse", "HEAD")
    git("checkout", "main")
    monkeypatch.setattr("app.storage.projects.get_project_root_path", lambda *_args, **_kwargs: str(tmp_path))
    return {"base": base, "failed": failed, "fixed": fixed, "divergent": divergent}


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


@pytest.mark.parametrize("category", ["publication", "outgoing_security", "codeql", "cloud_ci"])
@pytest.mark.parametrize(("failed_key", "successful_key", "resolved"), [
    ("failed", "failed", True), ("failed", "fixed", True),
    ("failed", "base", False), ("failed", "divergent", False),
    (None, "fixed", False), ("failed", None, False),
    ("unknown", "fixed", False), ("failed", "unknown", False),
])
def test_later_success_must_include_failed_source(
    test_project_id, cleanup_task, source_history, category, failed_key, successful_key, resolved,
):
    def observation(key, timestamp):
        return {"observed_at": timestamp,
                **({"source_commit": source_history.get(key, "f" * 40)} if key else {})}

    failed = observation(failed_key, "2026-10-02T08:00:00+00:00")
    task_id = record_finding(test_project_id, category, failed, resolved=False)
    assert task_id is not None
    cleanup_task(task_id)
    success = observation(successful_key, "2026-10-03T08:00:00+00:00")
    assert record_finding(test_project_id, category, success, resolved=True) == task_id
    task = get_repair_task(test_project_id)
    assert task is not None
    finding = task["verification_result"]["publication_repair"][category]
    assert finding == {**(success if resolved else failed), "state": "resolved" if resolved else "unresolved"}


@pytest.mark.parametrize("reason", ["cloud_ci_missing", "ci_policy_needs_review", None])
def test_restricted_resolution_preserves_other_ci_causes(
    test_project_id, cleanup_task, source_history, reason,
):
    failed = {"observed_at": "2026-10-02T08:00:00+00:00",
              "source_commit": source_history["failed"], "reason": reason}
    task_id = record_finding(test_project_id, "cloud_ci", failed, resolved=False)
    assert task_id is not None
    cleanup_task(task_id)
    success = {"observed_at": "2026-10-03T08:00:00+00:00",
               "source_commit": source_history["fixed"], "reason": "source_publication_verified"}
    record_finding(test_project_id, "cloud_ci", success, resolved=True,
                   resolution_reasons=frozenset({"cloud_ci_missing"}))
    task = get_repair_task(test_project_id)
    assert task is not None
    resolved = reason == "cloud_ci_missing"
    assert task["verification_result"]["publication_repair"]["cloud_ci"] == {
        **(success if resolved else failed), "state": "resolved" if resolved else "unresolved",
    }


def test_resolution_does_not_substitute_accepted_source_for_actual_failed_source(
    test_project_id, cleanup_task, source_history,
):
    failed = {"observed_at": "2026-10-02T08:00:00+00:00", "source_commit": source_history["divergent"],
              "accepted_source_commit": source_history["failed"]}
    task_id = record_finding(test_project_id, "codeql", failed, resolved=False)
    assert task_id is not None
    cleanup_task(task_id)
    record_finding(test_project_id, "codeql", {"observed_at": "2026-10-03T08:00:00+00:00",
                   "source_commit": source_history["fixed"]}, resolved=True)
    task = get_repair_task(test_project_id)
    assert task is not None
    assert task["verification_result"]["publication_repair"]["codeql"] == {**failed, "state": "unresolved"}


@pytest.mark.parametrize("replacement_key", ["failed", "divergent"])
def test_resolution_cas_preserves_finding_replaced_during_ancestry_proof(
    test_project_id, cleanup_task, source_history, monkeypatch, replacement_key,
):
    task_id = record_finding(test_project_id, "publication", {
        "observed_at": "2026-10-02T08:00:00+00:00", "source_commit": source_history["failed"],
    }, resolved=False)
    assert task_id is not None
    cleanup_task(task_id)
    replacement = {"state": "unresolved", "observed_at": "2026-10-03T09:00:00+00:00",
                   "source_commit": source_history[replacement_key]}
    original_run = safe_subprocess.run
    replaced = False

    def concurrent_replacement(command, **kwargs):
        nonlocal replaced
        result = original_run(command, **kwargs)
        if "merge-base" in command and result.returncode == 0 and not replaced:
            assert repair.DATABASE_URL is not None
            with psycopg.connect(repair.DATABASE_URL) as conn, conn.cursor() as cur:
                cur.execute("""UPDATE tasks SET verification_result = jsonb_set(
                    verification_result, '{publication_repair,publication}', %s::jsonb)
                    WHERE id = %s""", (Jsonb(replacement), task_id))
            replaced = True
        return result

    monkeypatch.setattr(safe_subprocess, "run", concurrent_replacement)
    record_finding(test_project_id, "publication", {
        "observed_at": "2026-10-03T08:00:00+00:00", "source_commit": source_history["fixed"],
    }, resolved=True)
    assert replaced, "fixture must replace the finding after actual ancestry proof"
    task = get_repair_task(test_project_id)
    assert task is not None
    assert task["verification_result"]["publication_repair"]["publication"] == replacement
