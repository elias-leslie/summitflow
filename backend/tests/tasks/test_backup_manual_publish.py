from __future__ import annotations

from contextlib import nullcontext
from unittest.mock import MagicMock

import pytest

from app.tasks import backup_manual_publish as manual

HEAD = "a" * 40
OLD = "b" * 40


@pytest.fixture
def dependencies(monkeypatch):
    mocks = {
        "source": MagicMock(return_value={"id": "source", "project_id": "project", "enabled": True, "source_type": "project"}),
        "latest": MagicMock(return_value={"id": "real-backup", "verification_json": {"publication": {"head": OLD}}}),
        "merge": MagicMock(return_value={"id": "real-backup"}),
        "acquire": MagicMock(return_value="owner-token"),
        "maintain": MagicMock(side_effect=lambda *_: nullcontext()),
        "owns": MagicMock(return_value=True),
        "publish": MagicMock(return_value={"status": "published", "head": HEAD, "publication_complete": True}),
        "record": MagicMock(),
        "health": MagicMock(return_value={"state": "verified"}),
    }
    for name, target in {"source": "get_source", "latest": "get_latest_backup", "merge": "merge_backup_verification_json"}.items():
        monkeypatch.setattr(manual.backup_store, target, mocks[name])
    for name, target in {"acquire": "acquire_backup_lock", "maintain": "maintain_backup_lock", "owns": "owns_backup_lease",
                         "publish": "publish_source_before_backup", "record": "record_publication_observation",
                         "health": "get_project_publication_health"}.items():
        monkeypatch.setattr(manual, target, mocks[name])
    return mocks


def test_manual_pins_source_and_persists_existing_receipt_and_health(dependencies):
    result = manual.publish_project_now("source", HEAD)
    kwargs = dependencies["publish"].call_args.kwargs
    assert kwargs["manual_source_commit"] == HEAD
    assert kwargs["retained"] is None
    assert kwargs["activity_allowed"]()
    dependencies["owns"].assert_called_with("source", "owner-token")
    publication = dependencies["publish"].return_value
    dependencies["merge"].assert_called_once_with("real-backup", {
        "publication": publication, "publish_before_backup": publication,
    })
    dependencies["record"].assert_called_once_with("project", publication)
    assert result["evidence_recorded"] is True
    assert result["health"]["state"] == "verified"


def test_manual_resumes_only_matching_requested_source(dependencies):
    prior = {"head": HEAD, "publication_branch": "st/previous"}
    dependencies["latest"].return_value["verification_json"] = {"publish_before_backup": prior}
    manual.publish_project_now("source", HEAD)
    assert dependencies["publish"].call_args.kwargs["retained"] == prior


@pytest.mark.parametrize("source_commit", ["HEAD", "a" * 39, "A" * 40, "a" * 65, "HEAD:refs/heads/main"])
def test_invalid_source_never_inspects_or_admits(dependencies, source_commit):
    with pytest.raises(ValueError):
        manual.publish_project_now("source", source_commit)
    dependencies["source"].assert_not_called()
    dependencies["acquire"].assert_not_called()


@pytest.mark.parametrize("source", [None, {"enabled": False}, {"enabled": True, "source_type": "config"}])
def test_disabled_or_nonproject_source_cannot_publish(dependencies, source):
    dependencies["source"].return_value = source
    result = manual.publish_project_now("source", HEAD)
    assert result["reason"] == "enabled_project_source_required"
    dependencies["acquire"].assert_not_called()


def test_busy_source_does_not_publish_or_create_backup(dependencies):
    dependencies["acquire"].return_value = None
    assert manual.publish_project_now("source", HEAD)["reason"] == "source_busy"
    dependencies["publish"].assert_not_called()
    dependencies["latest"].assert_not_called()


def test_no_real_backup_receipt_does_not_publish(dependencies):
    dependencies["latest"].return_value = None
    result = manual.publish_project_now("source", HEAD)
    assert result["reason"] == "publication_receipt_unavailable"
    dependencies["publish"].assert_not_called()
    dependencies["merge"].assert_not_called()


def test_lost_lease_never_records_success(dependencies):
    dependencies["owns"].return_value = False
    result = manual.publish_project_now("source", HEAD)
    assert result["publication_complete"] is False
    assert result["evidence_recorded"] is False
    dependencies["merge"].assert_not_called()
    dependencies["record"].assert_not_called()


def test_failed_publication_retains_complete_evidence(dependencies):
    dependencies["publish"].return_value = {"status": "failed", "head": HEAD, "publication_complete": False,
                                           "ci": {"state": "failed", "sha": HEAD}}
    result = manual.publish_project_now("source", HEAD)
    assert result["evidence_recorded"] is True
    assert result["ci"] == {"state": "failed", "sha": HEAD}
    assert result["publication_complete"] is False


def test_unrecordable_result_never_reports_completion(dependencies):
    dependencies["merge"].return_value = None
    result = manual.publish_project_now("source", HEAD)
    assert result["publication_complete"] is False
    assert result["evidence_recorded"] is False
    dependencies["record"].assert_not_called()
