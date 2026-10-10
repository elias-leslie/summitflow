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


def test_administration_disposition_preserves_failed_receipt_without_remote_pass(test_project_id, cleanup_task):
    observation = {"observed_at": "2026-10-02T08:00:00+00:00", "source_commit": "a" * 40, "reason": "cloud_ci_missing"}
    task_id = record_finding(test_project_id, "cloud_ci", observation, resolved=False)
    assert task_id is not None
    cleanup_task(task_id)
    original = tasks.get_task(task_id)
    assert original is not None
    finding = original["verification_result"]["publication_repair"]["cloud_ci"]
    assert repair.disposition_finding(task_id, test_project_id, "cloud_ci", expected_finding=finding,
        classification="administrative", reason="Owner retired scheduled publication", evidence="fixture://owner-plan")
    updated = tasks.get_task(task_id)
    assert updated is not None
    retained = updated["verification_result"]["publication_repair"]["cloud_ci"]
    assert retained["state"] == "unresolved"
    assert retained["disposition"]["state"] == "no_longer_required"
    assert retained["disposition"]["prior_finding"] == finding
    assert repair.unresolved_repair(updated) == []
    assert not repair.disposition_finding(task_id, test_project_id, "cloud_ci", expected_finding=finding,
        classification="administrative", reason="Stale writer", evidence="fixture://old")
    record_finding(test_project_id, "cloud_ci", {**observation, "observed_at": "2026-10-03T08:00:00+00:00"}, resolved=False)
    later = tasks.get_task(task_id)
    assert later is not None
    assert repair.unresolved_repair(later) == ["cloud_ci"]


def test_security_cannot_be_retired_as_optional_administration(test_project_id):
    finding = {"reason": "security_findings_open", "state": "unresolved"}
    with pytest.raises(ValueError, match="cannot be retired"):
        repair.disposition_finding("task", test_project_id, "outgoing_security", expected_finding=finding,
            classification="administrative", reason="Ignore", evidence="fixture://invalid")
    forged = {**finding, "disposition": {"kind": "publication_disposition.v1", "classification": "administrative", "state": "no_longer_required"}}
    assert repair.finding_actionable(forged)


def test_failed_remote_repair_requires_investigation(test_project_id):
    finding = {"reason": "nightly_repair_attempt_failed", "state": "unresolved"}
    assert repair.classify_retained_finding("publication", finding) == "investigation"
    with pytest.raises(ValueError, match="cannot be retired"):
        repair.disposition_finding("task", test_project_id, "publication", expected_finding=finding,
            classification="administrative", reason="Retire a wait", evidence="fixture://owner-plan")


@pytest.fixture
def rewritten_history(tmp_path, monkeypatch):
    def git(*arguments):
        return subprocess.run(["git", *arguments], cwd=tmp_path, check=True,
                              capture_output=True, text=True).stdout.strip()

    git("init", "-q", "--initial-branch=main")
    git("config", "user.name", "Fixture")
    git("config", "user.email", "fixture@example.invalid")
    git("config", "core.hooksPath", "/dev/null")
    (tmp_path / "source.txt").write_text("base")
    git("add", "source.txt")
    git("commit", "-qm", "base")
    (tmp_path / "source.txt").write_text("blocked by the outgoing scan")
    git("commit", "-qam", "blocked")
    blocked = git("rev-parse", "HEAD")
    # Amended before publication: the blocked commit leaves every ref.
    git("reset", "-q", "--hard", "HEAD^")
    (tmp_path / "source.txt").write_text("clean")
    git("commit", "-qam", "clean")
    clean = git("rev-parse", "HEAD")
    monkeypatch.setattr("app.storage.projects.get_project_root_path", lambda *_args, **_kwargs: str(tmp_path))
    return {"blocked": blocked, "clean": clean, "git": git, "root": tmp_path}


@pytest.mark.parametrize(("case", "resolved"), [
    ("unreachable", True), ("scan_not_proven", False), ("branch_keeps_it", False),
    ("remote_ref_keeps_it", False), ("worktree_head_keeps_it", False), ("other_category", False),
    ("verified_source_missing", False), ("shallow_clone", False),
])
def test_outgoing_finding_on_rewritten_source_resolves_only_when_unreachable_and_scanned(
    test_project_id, cleanup_task, rewritten_history, monkeypatch, case, resolved,
):
    git, blocked, clean = rewritten_history["git"], rewritten_history["blocked"], rewritten_history["clean"]
    category = "publication" if case == "other_category" else "outgoing_security"
    if case == "branch_keeps_it":
        git("branch", "kept", blocked)
    elif case == "remote_ref_keeps_it":
        git("update-ref", "refs/remotes/origin/kept", blocked)
    elif case == "worktree_head_keeps_it":
        git("worktree", "add", "-q", "--detach", str(rewritten_history["root"] / "wt"), blocked)
    elif case == "shallow_clone":
        real_git = repair._local_git
        monkeypatch.setattr(repair, "_local_git", lambda root, *arguments: (
            subprocess.CompletedProcess(arguments, 0, "true\n", "")
            if arguments == ("rev-parse", "--is-shallow-repository") else real_git(root, *arguments)))
    failed = {"observed_at": "2026-10-02T08:00:00+00:00", "source_commit": blocked, "reason": "security_findings_open"}
    task_id = record_finding(test_project_id, category, failed, resolved=False)
    assert task_id is not None
    cleanup_task(task_id)
    success = {"observed_at": "2026-10-03T08:00:00+00:00", "reason": "source_publication_verified",
               "source_commit": "f" * 40 if case == "verified_source_missing" else clean}
    record_finding(test_project_id, category, success, resolved=True,
                   outgoing_scan_verified=case != "scan_not_proven")
    task = get_repair_task(test_project_id)
    assert task is not None
    finding = task["verification_result"]["publication_repair"][category]
    assert finding == {**(success if resolved else failed), "state": "resolved" if resolved else "unresolved"}


def test_rewritten_source_never_outranks_a_newer_failure(test_project_id, cleanup_task, rewritten_history):
    failed = {"observed_at": "2026-10-03T09:00:00+00:00", "source_commit": rewritten_history["blocked"]}
    task_id = record_finding(test_project_id, "outgoing_security", failed, resolved=False)
    assert task_id is not None
    cleanup_task(task_id)
    record_finding(test_project_id, "outgoing_security", {"observed_at": "2026-10-03T08:00:00+00:00",
                   "source_commit": rewritten_history["clean"]}, resolved=True, outgoing_scan_verified=True)
    task = get_repair_task(test_project_id)
    assert task is not None
    assert task["verification_result"]["publication_repair"]["outgoing_security"]["state"] == "unresolved"


def _duplicate_repair_task(project_id, findings, *, status="pending"):
    from app.storage.connection import get_connection
    from app.storage.tasks.core import create_task

    task = create_task(project_id=project_id, title="Duplicate repair", labels=[repair.REPAIR_LABEL],
                       execution_mode="manual")
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("""UPDATE tasks SET verification_result = jsonb_build_object('publication_repair', %s::jsonb),
                       created_at = NOW() + interval '1 minute' WHERE id = %s""", (Jsonb(findings), task["id"]))
        conn.commit()
    if status != "pending":
        tasks.update_task_status(task["id"], status)
    return task["id"]


def test_duplicate_repair_tasks_fold_into_the_oldest_deterministically(test_project_id, cleanup_task):
    canonical = record_finding(test_project_id, "codeql", {
        "observed_at": "2026-10-03T08:00:00+00:00", "source_commit": "a" * 40}, resolved=False)
    assert canonical is not None
    cleanup_task(canonical)
    tasks.update_task_status(canonical, "running")
    record_finding(test_project_id, "publication", {
        "observed_at": "2026-10-04T08:00:00+00:00", "source_commit": "a" * 40}, resolved=False)
    duplicate_findings = {
        "outgoing_security": {"state": "unresolved", "observed_at": "2026-10-02T08:00:00+00:00", "source_commit": "b" * 40},
        # An older unresolved finding survives a newer resolution without proof.
        "publication": {"state": "resolved", "observed_at": "2026-10-05T08:00:00+00:00", "source_commit": "c" * 40},
    }
    pending = _duplicate_repair_task(test_project_id, duplicate_findings)
    cleanup_task(pending)
    claimed = _duplicate_repair_task(test_project_id, {
        "cloud_ci": {"state": "unresolved", "observed_at": "2026-10-02T08:00:00+00:00", "reason": "cloud_ci_missing"}},
        status="running")
    cleanup_task(claimed)

    assert record_finding(test_project_id, "codeql", {
        "observed_at": "2026-10-06T08:00:00+00:00", "source_commit": "a" * 40}, resolved=False) == canonical

    kept = tasks.get_task(canonical)
    assert kept is not None
    findings = kept["verification_result"]["publication_repair"]
    assert set(findings) == {"codeql", "publication", "outgoing_security", "cloud_ci"}
    assert findings["publication"]["state"] == "unresolved"
    assert findings["outgoing_security"]["source_commit"] == "b" * 40
    assert findings["codeql"]["observed_at"] == "2026-10-06T08:00:00+00:00"
    cancelled = tasks.get_task(pending)
    still_claimed = tasks.get_task(claimed)
    assert cancelled is not None and cancelled["status"] == "cancelled"
    assert still_claimed is not None and still_claimed["status"] == "running"
    assert canonical in (cancelled.get("error_message") or "")
    for duplicate in (cancelled, still_claimed):
        assert repair.REPAIR_LABEL not in (duplicate.get("labels") or [])
        assert "publication_repair" not in (duplicate.get("verification_result") or {})
    found = get_repair_task(test_project_id)
    assert found is not None and found["id"] == canonical
