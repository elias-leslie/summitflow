"""Development status is a read-only projection, not a gate or recovery action."""
import subprocess

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
