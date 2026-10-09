"""The local closeout adapter preserves source checks and recovery effects."""
from contextlib import nullcontext
from unittest.mock import Mock

import pytest

from cli.lib.task_closeout_adapter import LocalCloseoutOperations

SHA = "a" * 40


def test_validated_acceptance_is_represented_by_its_compact_reference(tmp_path, monkeypatch):
    reference = {"state": "success", "source_commit": SHA, "coverage": "task"}
    result = Mock()
    result.reference.to_dict.return_value = reference
    validator = Mock(return_value=result)
    monkeypatch.setattr("cli.lib.acceptance_coordinator.validate_source_receipt", validator)
    receipt = {"acceptance_id": "b" * 64, "acceptance_artifact": "/immutable/receipt.json"}
    assert LocalCloseoutOperations().validate_source(tmp_path, receipt, SHA) == reference
    validator.assert_called_once_with(tmp_path, receipt, sha=SHA)


def test_owned_source_and_created_paths_are_rechecked_before_cleanup(tmp_path, monkeypatch):
    scope = Mock()
    created = Mock()
    monkeypatch.setattr("cli.lib.acceptance_coordinator.require_scope_matches_revision", scope)
    monkeypatch.setattr("cli.lib.acceptance_coordinator.require_task_created_paths", created)
    status = Mock(return_value=Mock(returncode=0, stdout=""))
    monkeypatch.setattr("cli.lib.task_closeout_adapter.subprocess.run", status)
    task = {"id": "owned-task"}
    LocalCloseoutOperations().require_owned_source(tmp_path, SHA, ("app.py",), task)
    scope.assert_called_once_with(tmp_path, SHA, ("app.py",))
    created.assert_called_once_with(tmp_path, SHA, task)
    assert status.call_args.args[0][-2:] == ["--", ":(literal)app.py"]


@pytest.mark.parametrize("returncode,stdout", [(1, ""), (0, " M owned.py\0")])
def test_changed_or_uninspectable_owned_source_cannot_cleanup(tmp_path, monkeypatch, returncode, stdout):
    monkeypatch.setattr("cli.lib.acceptance_coordinator.require_scope_matches_revision", Mock())
    monkeypatch.setattr("cli.lib.acceptance_coordinator.require_task_created_paths", Mock())
    monkeypatch.setattr("cli.lib.task_closeout_adapter.subprocess.run", Mock(return_value=Mock(returncode=returncode, stdout=stdout)))
    with pytest.raises(ValueError):
        LocalCloseoutOperations().require_owned_source(tmp_path, SHA, ("owned.py",), {})


def test_checkpoint_cleanup_captures_protection_and_releases_only_task_leases(tmp_path, monkeypatch):
    capture, remove, release = Mock(), Mock(), Mock()
    monkeypatch.setattr("cli.lib.autosnapshot.capture_lifecycle_baseline", capture)
    monkeypatch.setattr("cli.lib.checkpoint.remove_snapshot", remove)
    monkeypatch.setattr("cli.lib.leases.release_task", release)
    LocalCloseoutOperations().cleanup("task-owned", "project-owned", tmp_path)
    capture.assert_called_once_with(project_id="project-owned", cwd=tmp_path)
    remove.assert_called_once_with("task-owned", project_id="project-owned")
    release.assert_called_once_with("project-owned", "task-owned")


def test_checkpoint_removal_failure_is_recoverable_before_lease_release(tmp_path, monkeypatch):
    release = Mock()
    monkeypatch.setattr("cli.lib.autosnapshot.capture_lifecycle_baseline", Mock())
    monkeypatch.setattr("cli.lib.checkpoint.remove_snapshot", Mock(side_effect=OSError("checkpoint metadata unavailable")))
    monkeypatch.setattr("cli.lib.leases.release_task", release)
    with pytest.raises(OSError):
        LocalCloseoutOperations().cleanup("task-owned", "project-owned", tmp_path)
    release.assert_not_called()


def test_source_lock_uses_the_shared_repository_mutation_primitive(tmp_path, monkeypatch):
    lock = Mock(return_value=nullcontext())
    monkeypatch.setattr("cli.lib.acceptance.repo_lock", lock)
    with LocalCloseoutOperations().source_lock(tmp_path):
        pass
    lock.assert_called_once_with(tmp_path, purpose="local closeout cleanup")
