from __future__ import annotations

from contextlib import nullcontext
from unittest.mock import Mock

import pytest

from app.tasks import backup_manual_publish as manual

HEAD = "a" * 40
OLD = "b" * 40


@pytest.fixture
def dependencies(monkeypatch, tmp_path):
    mocks = {
        "source": Mock(return_value={"id": "source", "project_id": "project", "path": str(tmp_path), "enabled": True, "source_type": "project"}),
        "lock": Mock(side_effect=lambda *_args, **_kwargs: nullcontext()),
        "root_path": Mock(side_effect=lambda project: str(tmp_path) if project == "project" else None),
        "publish": Mock(return_value={"status": "published", "head": HEAD, "publication_complete": True}),
        "record": Mock(),
    }
    monkeypatch.setattr(manual.backup_store, "get_source", mocks["source"])
    monkeypatch.setattr(manual.backup_store, "get_latest_backup", Mock(side_effect=AssertionError("Sharing is independent of backups")))
    monkeypatch.setattr(manual.backup_store, "merge_backup_verification_json", Mock(side_effect=AssertionError("Preserve backup history")))
    monkeypatch.setattr(manual, "publication_receipt_directory", lambda _: tmp_path / "publication")
    for name, target in {"lock": "repo_lock", "root_path": "get_project_root_path",
                         "publish": "publish_source_before_backup", "record": "record_publication_observation"}.items():
        monkeypatch.setattr(manual, target, mocks[name])
    mocks["root"] = tmp_path
    return mocks


def test_manual_pins_source_and_retains_evidence_without_backup(dependencies):
    result = manual.publish_project_now("source", HEAD)
    kwargs = dependencies["publish"].call_args.kwargs
    assert kwargs["manual_source_commit"] == HEAD
    assert kwargs["retained"] is None
    assert kwargs["activity_allowed"]()
    dependencies["record"].assert_called_once_with("project", dependencies["publish"].return_value)
    assert result["evidence_recorded"] is True
    receipt = manual.read_publication_receipt(dependencies["root"], HEAD)
    assert receipt is not None
    assert receipt["observation"]["head"] == HEAD


def test_latest_publication_selects_only_authenticated_current_project_pointers(dependencies):
    import json

    manual.publish_project_now("project", HEAD)
    root = dependencies["root"]
    selected = manual.latest_publication_receipt(root, "project")
    assert selected is not None and selected[1]["source_commit"] == HEAD
    assert manual.latest_publication_receipt(root, "foreign") is None
    pointer = selected[0]
    value = json.loads(pointer.read_text())
    value["observation"]["status"] = "forged"
    pointer.write_text(json.dumps(value))
    with pytest.raises(ValueError, match="integrity mismatch"):
        manual.latest_publication_receipt(root, "project")


def test_explicit_reobservation_reuses_only_matching_source_and_preserves_history(dependencies):
    dependencies["publish"].return_value = {"status": "published", "head": OLD, "publication_complete": True}
    first = manual.publish_project_now("source", OLD)
    old = manual.read_publication_receipt(dependencies["root"], OLD)
    assert old is not None
    dependencies["publish"].return_value = {"status": "published", "head": HEAD, "publication_complete": True}
    manual.publish_project_now("source", HEAD)
    assert dependencies["publish"].call_args.kwargs["retained"] is None
    dependencies["publish"].return_value = {"status": "published", "head": OLD, "publication_complete": True}
    manual.publish_project_now("source", OLD)
    assert dependencies["publish"].call_args.kwargs["retained"] == old["observation"]
    from pathlib import Path
    assert Path(first["evidence"]).is_file()


@pytest.mark.parametrize("source_commit", ["HEAD", "a" * 39, "A" * 40, "a" * 65, "HEAD:refs/heads/main"])
def test_invalid_source_never_inspects_or_admits(dependencies, source_commit):
    with pytest.raises(ValueError):
        manual.publish_project_now("source", source_commit)
    dependencies["source"].assert_not_called()
    dependencies["lock"].assert_not_called()


@pytest.mark.parametrize("source", [None, {"enabled": False}, {"enabled": True, "source_type": "config"}])
def test_unregistered_or_nonproject_source_cannot_publish(dependencies, source):
    dependencies["source"].return_value = source
    result = manual.publish_project_now("source", HEAD)
    assert result["reason"] == "registered_project_required"
    dependencies["lock"].assert_not_called()


def test_registered_project_needs_no_backup_source_or_schedule(dependencies):
    dependencies["source"].side_effect = AssertionError("No backup prerequisite")
    result = manual.publish_project_now("project", HEAD)
    assert result["publication_complete"] and result["evidence_recorded"]
    dependencies["source"].assert_not_called()


def test_disabled_backup_schedule_does_not_disable_manual_publication(dependencies):
    dependencies["source"].return_value["enabled"] = False
    assert manual.publish_project_now("source", HEAD)["publication_complete"]


def test_busy_repository_does_not_publish(dependencies):
    dependencies["lock"].side_effect = manual.AcceptanceError("repo_mutation_in_progress")
    assert manual.publish_project_now("source", HEAD)["reason"] == "repository_busy"
    dependencies["publish"].assert_not_called()


def test_observation_of_different_source_cannot_report_publication(dependencies):
    dependencies["publish"].return_value["head"] = OLD
    result = manual.publish_project_now("source", HEAD)
    assert result["publication_complete"] is False
    assert result["evidence_recorded"] is False
    dependencies["record"].assert_not_called()


def test_failed_publication_retains_complete_evidence(dependencies):
    dependencies["publish"].return_value = {"status": "failed", "head": HEAD, "publication_complete": False,
        "ci": {"state": "failed", "sha": HEAD}, "detail": "private-diagnostic"}
    result = manual.publish_project_now("source", HEAD)
    assert result["evidence_recorded"] is True
    receipt = manual.read_publication_receipt(dependencies["root"], HEAD)
    assert receipt is not None
    assert receipt["observation"]["ci"]["state"] == "failed"
    assert "private-diagnostic" not in str(receipt)


def test_unrecordable_result_never_reports_completion(dependencies, monkeypatch):
    monkeypatch.setattr(manual, "_retain_publication", Mock(side_effect=OSError("fixture")))
    result = manual.publish_project_now("source", HEAD)
    assert result["publication_complete"] is False
    assert result["evidence_recorded"] is False
    dependencies["record"].assert_not_called()
