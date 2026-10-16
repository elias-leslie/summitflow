"""Retained publication evidence is source-bound; ordinary local completion stays independent."""
from datetime import datetime
from unittest.mock import Mock

import pytest

from app.services import publication_health as health
from app.services.task_acceptance import completion_gates

SHA = "a" * 40
MERGE = "b" * 40


@pytest.fixture(autouse=True)
def no_registered_root(monkeypatch):
    monkeypatch.setattr(health, "get_project_root_path", lambda _: None)


def test_manual_receipt_is_read_without_backup_publication_dependency(monkeypatch, tmp_path):
    monkeypatch.setattr(health, "get_project_root_path", lambda _: str(tmp_path))
    monkeypatch.setattr(health, "get_repair_task", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(health, "get_latest_backup", lambda **_kwargs: {
        "id": "old", "verification_json": {"publish_before_backup": {"status": "failed"}}})
    monkeypatch.setattr("app.tasks.backup_manual_publish.latest_publication_receipt", lambda *_args: (
        tmp_path / "manual.json", {"observed_at": "2026-10-03T08:00:00+00:00", "observation": pushed()}))

    result = health.get_project_publication_health("project")

    assert result["state"] == "published"
    assert result["backup_id"] is None
    assert result["evidence"] == str(tmp_path / "manual.json")


def pushed(**overrides):
    return {"status": "published", "head": SHA, "publication_complete": True,
            "observed_at": "2026-10-02T08:00:00+00:00", "reason": "source_published",
            "security": {"state": "success", "sha": SHA},
            "acceptance": {"state": "reused", "source_commit": SHA, "acceptance_id": "receipt"}, **overrides}


PRIVATE = {"state": "not_required", "reason": "private_repository", "source_commit": SHA}


@pytest.mark.parametrize("override", [
    {"publication_complete": False}, {"observed_at": None}, {"observed_at": "2026-10-02T08:00:00"},
    {"acceptance": {}}, {"security": {"state": "not_run"}}, {"security": {"state": "success", "sha": MERGE}},
    {"acceptance": {"state": "reused", "source_commit": MERGE, "acceptance_id": "receipt"}},
    {"acceptance": {**PRIVATE, "source_commit": MERGE}},
])
def test_incomplete_push_is_never_published(override):
    assert health.classify_observation(pushed(**override))["state"] != "published"


def test_private_push_needs_no_receipt_and_ci_never_decides_the_verdict():
    assert health.classify_observation(pushed(acceptance=PRIVATE))["state"] == "published"
    # Receipts retained from the retired PR path keep their CI state for display only.
    legacy = health.classify_observation(pushed(ci={"state": "failed", "sha": SHA}))
    assert (legacy["state"], legacy["ci_state"]) == ("published", "failed")
    assert health.classify_observation(pushed())["ci_state"] == "unknown"
    assert "Manual publication: published;" in health.format_publication_health(health.classify_observation(pushed()))


@pytest.mark.parametrize("category", ["publication", "outgoing_security", "codeql"])
def test_published_source_cannot_hide_retained_findings(monkeypatch, category):
    monkeypatch.setattr(health, "get_latest_backup", lambda **_kwargs: {
        "id": "backup", "verification_json": {"publish_before_backup": pushed()}})
    monkeypatch.setattr(health, "get_repair_task", lambda *_args, **_kwargs: {
        "id": "repair", "verification_result": {"publication_repair": {category: {"state": "unresolved"}}}})
    observed = health.get_project_publication_health("project", now=datetime.fromisoformat("2026-10-02T10:00:00+00:00"))
    assert observed["state"] == "blocked" and observed["reason"] == "actionable_repair_findings"
    assert observed["unresolved_categories"] == [category]


@pytest.mark.parametrize("reason", sorted(health._SETUP_FAILURES))
def test_known_setup_failure_is_actionable(reason):
    assert health.classify_observation({"status": "skipped", "reason": reason})["state"] == "blocked"


@pytest.mark.parametrize("reason", sorted(health._DEFERRED))
def test_transient_deferral_does_not_create_repair(reason, monkeypatch):
    recorder = Mock()
    monkeypatch.setattr(health, "record_finding", recorder)
    assert health.record_publication_observation("project", {"status": "pending", "reason": reason}) is None
    recorder.assert_not_called()


@pytest.mark.parametrize("reason", ["remote_authentication_unavailable", "remote_transport_unavailable",
                                   "remote_api_unavailable", "remote_ci_unavailable", "heavy_work_admission_unavailable"])
def test_shared_outage_is_not_a_project_repair_even_with_failed_transport_status(reason, monkeypatch):
    recorder = Mock()
    monkeypatch.setattr(health, "record_finding", recorder)
    assert health.classify_observation({"status": "failed", "reason": reason})["state"] == "pending"
    assert health.record_publication_observation("project", {"status": "failed", "reason": reason}) is None
    recorder.assert_not_called()


@pytest.mark.parametrize("acceptance", [pushed()["acceptance"], PRIVATE])
def test_completed_push_resolves_publication_findings_but_never_codeql(monkeypatch, acceptance):
    """A later clean push (private ones carry no receipt) must clear an earlier
    push failure such as remote_push_rejected; storage still proves the failed
    source is included and the observation is newer."""
    recorder = Mock(return_value="repair")
    monkeypatch.setattr(health, "record_finding", recorder)
    result = pushed(acceptance=acceptance)
    observation = health.classify_observation(result)
    assert health.record_publication_observation("project", result) == "repair"
    recorder.assert_any_call("project", "publication", observation, resolved=True)
    recorder.assert_any_call("project", "outgoing_security", observation, resolved=True, outgoing_scan_verified=True)
    recorder.assert_any_call("project", "cloud_ci", observation, resolved=True,
                             resolution_reasons=frozenset({"cloud_ci_missing"}))
    recorder.assert_any_call("project", "nightly_repair_attempt_failed", observation, resolved=True,
                             resolution_reasons=frozenset({"nightly_repair_attempt_failed"}))
    assert "codeql" not in {call.args[1] for call in recorder.call_args_list}


@pytest.mark.parametrize("reason", ["remote_push_rejected", "pre_push_hook_rejected", "remote_base_diverged"])
def test_failed_push_records_an_unresolved_publication_finding(monkeypatch, reason):
    recorder = Mock(return_value="repair")
    monkeypatch.setattr(health, "record_finding", recorder)
    result = {"status": "failed", "reason": reason, "head": SHA, "observed_at": "2026-10-02T08:00:00+00:00"}
    assert health.record_publication_observation("project", result) == "repair"
    recorder.assert_called_once_with("project", "publication", health.classify_observation(result), resolved=False)


def test_incomplete_push_resolves_nothing(monkeypatch):
    recorder = Mock()
    monkeypatch.setattr(health, "record_finding", recorder)
    health.record_publication_observation("project", pushed(publication_complete=False, status="pending",
                                                            reason="workflow_effects_authorization_required"))
    recorder.assert_not_called()


def test_reobserve_replays_the_newest_retained_receipt(monkeypatch, tmp_path):
    recorder = Mock(return_value="repair")
    monkeypatch.setattr(health, "record_finding", recorder)
    monkeypatch.setattr(health, "get_project_root_path", lambda _: str(tmp_path))
    receipt = {k: v for k, v in pushed().items() if k != "observed_at"}
    monkeypatch.setattr("app.tasks.backup_manual_publish.latest_publication_receipt", lambda *_args: (
        tmp_path / "receipt.json", {"observed_at": "2026-10-03T08:00:00+00:00", "observation": receipt}))
    replay = health.reobserve_retained_publication("project")
    assert replay is not None and replay["state"] == "published" and replay["repair_task_id"] == "repair"
    assert replay["observed_at"] == "2026-10-03T08:00:00+00:00"
    assert {call.args[1] for call in recorder.call_args_list} >= {"publication", "outgoing_security"}
    monkeypatch.setattr("app.tasks.backup_manual_publish.latest_publication_receipt", lambda *_args: None)
    assert health.reobserve_retained_publication("project") is None


@pytest.mark.parametrize("state", ["pending", "unknown", "published"])
@pytest.mark.parametrize("repair_id", [None, "repair"])
def test_normal_publication_states_allow_local_completion(state, repair_id, monkeypatch):
    monkeypatch.setattr(health, "get_project_publication_health", lambda _pid: {
        "state": state, "repair_task_id": repair_id, "unresolved_categories": [],
    })
    assert completion_gates({"id": "normal", "project_id": "project", "commits": [SHA],
                             "verification_result": {"acceptance": {"state": "success", "source_commit": SHA}}}) == []


def test_unrelated_publication_defect_does_not_gate_local_completion(monkeypatch):
    monkeypatch.setattr(health, "get_project_publication_health", lambda _pid: {
        "state": "blocked", "repair_task_id": "repair", "unresolved_categories": ["codeql"],
    })
    gates = completion_gates({"id": "normal", "project_id": "project", "verification_result": {}})
    assert gates == []
