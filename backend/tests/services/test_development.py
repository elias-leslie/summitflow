"""Development status is a read-only projection, not a gate or recovery action."""
import json
import subprocess

import pytest

from app.services import development as service


def _stores(mocker, tmp_path):
    mocker.patch.object(service.tasks, "list_tasks", return_value=[])
    mocker.patch.object(service.tasks, "list_blocked_tasks", return_value=[])
    mocker.patch.object(service.backups, "list_backups", return_value=([], 0))
    mocker.patch.object(service.backups, "list_sources", return_value=[])
    mocker.patch.object(service, "current_source_root", return_value=None)
    mocker.patch("app.services.native_deployment._store_root", return_value=tmp_path / "native")


def test_projection_preserves_neutral_work_and_independent_recovery(tmp_path, mocker):
    _stores(mocker, tmp_path)
    mocker.patch.object(service, "_git_common_dir", return_value=tmp_path)
    git = mocker.patch.object(service, "_git", side_effect=lambda _root, *args: {
        ("rev-parse", "HEAD"): "a" * 40,
        ("status", "--porcelain", "--untracked-files=all"): " M file\n?? new",
        ("rev-parse", "--verify", "@{upstream}"): "b" * 40,
        ("rev-list", "--count", "@{upstream}..HEAD"): "2",
    }[args])
    mocker.patch.object(service.backups, "list_backups", return_value=([{
        "id": "bkp-1", "status": "completed", "completed_at": "2026-10-03T20:00:00Z",
        "verification_json": {"snapshot_id": "snap-1", "offsite": {"status": "failed", "error": "Destination unavailable"}},
    }], 1))
    result = service.build_development_projection("alpha", tmp_path)
    assert result["version"] == "development.v1"
    assert result["working_tree"]["uncommitted"] == 2
    assert result["working_tree"]["unpublished"] == 2
    assert result["accepted"]["state"] == "unavailable"
    assert result["recovery"]["capture"]["state"] == "completed"
    assert result["recovery"]["offsite"]["state"] == "failed"
    assert result["recovery"]["snapshot"]["state"] == "recorded"
    assert result["recovery"]["restore"]["state"] == "unavailable"
    assert all(not set(call.args[1:]) & {"fetch", "push", "commit"} for call in git.call_args_list)


def test_acceptance_validates_current_inputs_and_marks_drift(tmp_path, mocker):
    directory = tmp_path / "st" / "acceptance"
    directory.mkdir(parents=True)
    path = directory / "receipt.json"
    path.write_text('{"state":"success","source":{"commit":"old"},"completed_at":"2026-10-03"}')
    validator = mocker.patch.object(service, "validate_acceptance_receipt", return_value={"completed_at": "2026-10-03", "check_count": 12})
    result = service._accepted(tmp_path, tmp_path, "new")
    assert result["state"] == "stale"
    assert result["drift"] is True
    assert result["full_coverage"] is True
    validator.assert_called_once_with(tmp_path, path)
    validator.side_effect = service.AcceptanceError("local inputs changed")
    result = service._accepted(tmp_path, tmp_path, "old")
    assert result["state"] == "stale"
    assert result["full_coverage"] is False


def test_missing_stores_do_not_become_zero_or_success(tmp_path, mocker):
    _stores(mocker, tmp_path)
    mocker.patch.object(service, "_git", side_effect=ValueError("Git unavailable"))
    mocker.patch.object(service.tasks, "list_tasks", side_effect=RuntimeError("Store unavailable"))
    mocker.patch.object(service.backups, "list_backups", side_effect=RuntimeError("Store unavailable"))
    result = service.build_development_projection("alpha", tmp_path)
    assert result["working_tree"]["state"] == "error"
    assert "uncommitted" not in result["working_tree"]
    assert result["blockers"]["state"] == "unavailable"
    assert result["recovery"]["offsite"]["state"] == "error"


def test_managed_runtime_uses_current_receipt_without_polling(tmp_path, mocker):
    root = tmp_path / "projects" / "alpha" / "releases" / "build" / "source"
    path = root.parents[2] / "receipts" / "build.json"
    path.parent.mkdir(parents=True)
    path.write_text('{"completed_at": 100}')
    mocker.patch.object(service, "current_source_root", return_value=root)
    validator = mocker.patch.object(service, "validate_deployment_receipt", return_value={"source_commit": "deployed"})
    result = service._running("alpha", tmp_path, {"source_commit": "accepted"})
    assert result["source_commit"] == "deployed"
    assert result["runtime_health"] == "recorded_success"
    assert result["drift"] is True
    validator.assert_called_once_with(path, project_root=tmp_path)


def test_publication_reads_only_authenticated_current_receipts(tmp_path, mocker):
    directory = tmp_path / "st" / "publication"
    directory.mkdir(parents=True)
    sha = "a" * 40
    (directory / (sha + ".json")).write_text("unused")
    (directory / (sha + "-digest.json")).write_text("unused")
    reader = mocker.patch("app.tasks.backup_manual_publish.latest_publication_receipt", return_value=(directory / (sha + ".json"), {
        "kind": "manual_publication.v1", "project_id": "alpha", "source_commit": sha,
        "observed_at": "2026-10-03", "observation": {"status": "pending", "reason": "ci_pending"},
    }))
    result = service._publication(tmp_path, tmp_path, "alpha")
    assert result["state"] == "pending"
    reader.assert_called_once_with(tmp_path, "alpha", directory=directory)


def test_native_runtime_reads_trusted_store_independently_of_task_history(tmp_path, mocker):
    mocker.patch.object(service, "current_source_root", return_value=None)
    directory = tmp_path / "native"
    directory.mkdir()
    receipt_id = "b" * 32
    (directory / (receipt_id + ".json")).write_text("unused")
    mocker.patch("app.services.native_deployment._store_root", return_value=directory)
    reader = mocker.patch("app.services.native_deployment.read_native_evidence", return_value={
        "receipt_id": receipt_id, "project": "alpha", "completed_at": 100, "state": "succeeded",
        "observation": {"deployed_source_commit": "a" * 40},
    })
    result = service._running("alpha", tmp_path, {"source_commit": None})
    assert result["source_commit"] == "a" * 40
    assert result["runtime_health"] == "recorded_success"
    assert result["drift"] is False
    assert result["evidence"] == str(directory / (receipt_id + ".json"))
    reader.assert_called_once_with(receipt_id)


def test_blockers_read_only_relevant_task_states(tmp_path, mocker):
    _stores(mocker, tmp_path)
    mocker.patch.object(service, "_git", side_effect=ValueError("Git unavailable"))
    dependencies = mocker.patch.object(service.tasks, "list_blocked_tasks", return_value=[
        {"id": "task-1", "title": "Dependency", "status": "pending"},
    ])
    reader = mocker.patch.object(service.tasks, "list_tasks", side_effect=[
        [{"id": "task-2", "title": "Retry", "status": "failed"}],
        [{"id": "task-3", "title": "Recover local completion", "status": "pending", "verification_result": {
            "closeout": {"kind": "local_closeout.v1", "state": "blocked", "reason": "Required runtime evidence missing"}}},
         {"id": "task-4", "title": "Ordinary unfinished work", "status": "pending"}],
        [],
    ])
    result = service.build_development_projection("alpha", tmp_path)
    assert result["blockers"]["state"] == "available"
    assert [row["task_id"] for row in result["blockers"]["items"]] == ["task-1", "task-3", "task-2"]
    dependencies.assert_called_once_with("alpha", limit=500)
    assert reader.call_args_list == [mocker.call("alpha", status_filter=state, limit=500) for state in ("failed", "pending", "running")]


def test_retired_administration_is_not_an_actionable_development_blocker(tmp_path, mocker):
    _stores(mocker, tmp_path)
    mocker.patch.object(service, "_git", side_effect=ValueError("Git unavailable"))
    prior = {"state": "unresolved", "reason": "cloud_ci_missing"}
    mocker.patch.object(service.tasks, "list_tasks", side_effect=[[], [
        {"id": "task-admin", "status": "pending", "labels": ["publication-repair"], "verification_result": {
            "publication_repair": {"cloud_ci": {**prior,
                "disposition": {"kind": "publication_disposition.v1", "state": "no_longer_required",
                    "classification": "administrative", "prior_finding": prior}}}}},
        {"id": "task-security", "status": "pending", "labels": ["publication-repair"], "verification_result": {
            "publication_repair": {"outgoing_security": {"state": "unresolved", "reason": "secret_path"}}}},
    ], []])
    result = service.build_development_projection("alpha", tmp_path)
    assert [row["task_id"] for row in result["blockers"]["items"]] == ["task-security"]


def test_projection_counts_each_file_in_untracked_directory(tmp_path, mocker):
    _stores(mocker, tmp_path)
    subprocess.run(["git", "init", "--quiet", str(tmp_path)], check=True)
    directory = tmp_path / "new-work"
    directory.mkdir()
    for name in ("one.py", "two.py", "three.py"):
        (directory / name).write_text("# uncommitted task work\n")
    original_git = service._git

    def local_git(root, *args):
        if args[0] == "status":
            return original_git(root, *args)
        return "a" * 40

    mocker.patch.object(service, "_git", side_effect=local_git)
    mocker.patch.object(service, "_git_common_dir", return_value=tmp_path / ".git")
    mocker.patch.object(service, "_has_upstream", return_value=False)
    result = service.build_development_projection("alpha", tmp_path)
    assert result["working_tree"]["state"] == "uncommitted"
    assert result["working_tree"]["uncommitted"] == 3
    assert result["working_tree"]["unpublished"] is None


@pytest.fixture
def native_store(tmp_path, mocker):
    directory = tmp_path / "native"
    directory.mkdir(mode=0o700)
    mocker.patch.object(service, "current_source_root", return_value=None)
    mocker.patch("app.services.native_deployment._store_root", return_value=directory)
    return directory


def native_record(directory, receipt_id, project, *, valid=True, state="succeeded", completed_at=100):
    from app.services.native_deployment import KIND

    path = directory / f"{receipt_id}.json"
    path.write_text(json.dumps({"kind": KIND if valid else "invalid", "receipt_id": receipt_id,
        "project": project, "completed_at": completed_at, "state": state,
        "observation": {"deployed_source_commit": "a" * 40}}))
    path.chmod(0o600)
    return path


@pytest.mark.parametrize("matching", [False, True])
def test_shared_invalid_records_do_not_poison_unrelated_runtime(native_store, matching):
    native_record(native_store, "a" * 32, "foreign")
    native_record(native_store, "b" * 32, "foreign", valid=False)
    unknown = native_store / (("c" * 32) + ".json")
    unknown.write_text("unreadable JSON")
    unknown.chmod(0o600)
    if matching:
        native_record(native_store, "d" * 32, "alpha", completed_at=200)
    result = service._running("alpha", native_store.parent, {"source_commit": "a" * 40})
    assert result["state"] == ("succeeded" if matching else "unavailable")
    assert result["runtime_health"] == ("recorded_success" if matching else "unknown")
    assert result["source_commit"] == ("a" * 40 if matching else None)
    integrity = result["shared_store_integrity"]
    assert integrity["state"] == "uncertain"
    assert integrity["invalid_records"] == 2
    assert integrity["matching_records"] == 0
    assert integrity["foreign_records"] == 1
    assert integrity["unassignable_records"] == 1
    assert "Shared deployment evidence includes 2 receipts that could not be validated" in result["reason"]
    if matching:
        assert result["drift"] is False
        assert "current live health not polled" in result["reason"]


@pytest.mark.parametrize("valid_matching", [False, True])
def test_matching_invalid_record_remains_visible_alongside_valid_history(native_store, valid_matching):
    bad = native_record(native_store, "a" * 32, "alpha", valid=False, completed_at=300)
    native_record(native_store, "b" * 32, "foreign")
    if valid_matching:
        native_record(native_store, "c" * 32, "alpha", completed_at=200)
    result = service._running("alpha", native_store.parent, {"source_commit": None})
    assert result["state"] == "error" and result["runtime_health"] == "unknown"
    assert result["source_commit"] is None
    assert result["invalid_evidence"] == [str(bad)]
    assert result["shared_store_integrity"]["matching_records"] == 1
    assert "for this project could not be validated" in result["reason"]
    if valid_matching:
        retained = result["validated_observation"]
        assert retained["state"] == "succeeded" and retained["source_commit"] == "a" * 40
        assert retained["runtime_health"] == "recorded_success"
    else:
        assert "validated_observation" not in result


@pytest.mark.parametrize("problem", ["symlink", "public_file", "public_root", "foreign_owner", "unreadable", "missing_project"])
def test_unassignable_private_metadata_never_claims_runtime_success(native_store, mocker, problem):
    path = native_record(native_store, "a" * 32, "alpha", valid=False)
    if problem == "symlink":
        original = path.read_text()
        path.unlink()
        target = native_store.parent / "other-file"
        target.write_text(original)
        path.symlink_to(target)
    elif problem == "public_file":
        path.chmod(0o644)
    elif problem == "public_root":
        native_store.chmod(0o755)
    elif problem == "foreign_owner":
        import os
        mocker.patch.object(os, "getuid", return_value=path.stat().st_uid + 1)
    elif problem == "unreadable":
        mocker.patch.object(service, "_read", side_effect=OSError("metadata unavailable"))
    else:
        path.write_text('{"kind":"invalid","state":"succeeded"}')
    result = service._running("alpha", native_store.parent, {"source_commit": None})
    assert result["state"] == "unavailable" and result["runtime_health"] == "unknown"
    assert result["source_commit"] is None
    integrity = result["shared_store_integrity"]
    assert integrity["unassignable_records"] == 1 and integrity["matching_records"] == 0
    assert "Shared deployment evidence" in result["reason"]


@pytest.mark.parametrize("state", ["succeeded", "failed"])
def test_matching_valid_observation_retains_state_and_latest_source(native_store, state):
    native_record(native_store, "a" * 32, "alpha", completed_at=100)
    latest = native_record(native_store, "b" * 32, "alpha", state=state, completed_at=200)
    native_record(native_store, "c" * 32, "foreign", completed_at=300)
    result = service._running("alpha", native_store.parent, {"source_commit": "b" * 40})
    assert result["state"] == state
    assert result["runtime_health"] == ("recorded_success" if state == "succeeded" else "recorded_failure")
    assert result["source_commit"] == "a" * 40 and result["drift"] is True
    assert result["evidence"] == str(latest) and result["observed_at"] == 200
    assert "shared_store_integrity" not in result


def test_owner_authenticated_but_malformed_matching_observation_stays_error(native_store):
    path = native_record(native_store, "a" * 32, "alpha")
    record = json.loads(path.read_text())
    del record["observation"]
    path.write_text(json.dumps(record))
    result = service._running("alpha", native_store.parent, {})
    assert result["state"] == "error" and result["runtime_health"] == "unknown"
    assert result["source_commit"] is None
    assert result["invalid_evidence"] == [str(path)]
    assert result["shared_store_integrity"]["matching_records"] == 1
