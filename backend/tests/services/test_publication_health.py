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
        tmp_path / "manual.json", {"observed_at": "2026-10-03T08:00:00+00:00", "observation": verified()}))

    result = health.get_project_publication_health("project")

    assert result["state"] == "verified"
    assert result["backup_id"] is None
    assert result["evidence"] == str(tmp_path / "manual.json")


def verified(**overrides):
    return {"status": "success", "head": SHA, "publication_complete": True,
            "observed_at": "2026-10-02T08:00:00+00:00", "reason": "published",
            "ci": {"state": "success", "sha": SHA},
            "security": {"state": "success", "sha": SHA},
            "acceptance": {"state": "reused", "source_commit": SHA, "acceptance_id": "receipt"}, **overrides}


@pytest.mark.parametrize("override", [
    {"observed_at": None}, {"observed_at": "2026-10-02T08:00:00"},
    {"acceptance": {}}, {"security": {"state": "not_run"}},
    {"ci": {"state": "success", "sha": MERGE}},
    {"ci": {"state": "success"}},
    {"acceptance": {"state": "reused", "source_commit": MERGE, "acceptance_id": "receipt"}},
])
def test_incomplete_success_is_never_verified(override):
    assert health.classify_observation(verified(**override))["state"] != "verified"


def test_merge_requires_successful_checks_bound_to_source():
    assert health.classify_observation(verified(merge_sha=MERGE, ci={
        "state": "success", "sha": MERGE, "pr_checks": {"state": "success", "sha": SHA},
    }))["state"] == "verified"
    assert health.classify_observation(verified(merge_sha=MERGE, ci={
        "state": "success", "sha": MERGE, "pr_checks": {"state": "success", "sha": MERGE},
    }))["state"] == "unknown"


def test_accepted_uploaded_source_without_ci_is_published_not_verified():
    observation = health.classify_observation(verified(ci={"state": "not_applicable", "sha": SHA}))
    assert observation["state"] == "published"
    assert observation["reason"] == "published_without_ci"
    text = health.format_publication_health(observation)
    assert "Manual publication: published;" in text and "CI=not_applicable;" in text
    assert "verified" not in text


@pytest.mark.parametrize("pr_state", ["success", "not_applicable"])
def test_no_ci_merge_keeps_actual_ci_source_and_requires_exact_head_relation(pr_state):
    result = verified(merge_sha=MERGE, ci={"state": "not_applicable", "sha": MERGE,
                      "pr_checks": {"state": pr_state, "sha": SHA}})
    assert health.classify_observation(result)["state"] == "published"
    result["ci"]["pr_checks"]["sha"] = MERGE
    assert health.classify_observation(result)["state"] == "unknown"


@pytest.mark.parametrize("override", [
    {"publication_complete": False}, {"observed_at": None}, {"acceptance": {}},
    {"security": {"state": "not_run"}}, {"security": {"state": "success", "sha": MERGE}},
    {"ci": {"state": "not_applicable"}}, {"ci": {"state": "not_applicable", "sha": MERGE}},
])
def test_no_ci_upload_still_requires_exact_acceptance_security_and_source(override):
    result = verified(ci={"state": "not_applicable", "sha": SHA})
    result.update(override)
    assert health.classify_observation(result)["state"] not in {"published", "verified"}




@pytest.mark.parametrize("category", ["publication", "outgoing_security", "codeql"])
def test_no_ci_uploaded_source_cannot_hide_retained_findings(monkeypatch, category):
    result = verified(ci={"state": "not_applicable", "sha": SHA})
    monkeypatch.setattr(health, "get_latest_backup", lambda **_kwargs: {
        "id": "backup", "verification_json": {"publish_before_backup": result}})
    monkeypatch.setattr(health, "get_repair_task", lambda *_args, **_kwargs: {
        "id": "repair", "verification_result": {"publication_repair": {category: {"state": "unresolved"}}}})
    observed = health.get_project_publication_health("project", now=datetime.fromisoformat("2026-10-02T10:00:00+00:00"))
    assert observed["state"] == "blocked" and observed["reason"] == "actionable_repair_findings"
    assert observed["ci_state"] == "not_applicable" and observed["unresolved_categories"] == [category]


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


def test_success_does_not_resolve_independent_codeql_findings(monkeypatch):
    recorder = Mock()
    monkeypatch.setattr(health, "record_finding", recorder)
    health.record_publication_observation("project", verified())
    assert "codeql" not in {call.args[1] for call in recorder.call_args_list}


def test_verified_publication_resolves_only_known_missing_ci_cause(monkeypatch):
    recorder = Mock()
    monkeypatch.setattr(health, "record_finding", recorder)
    health.record_publication_observation("project", verified())
    recorder.assert_any_call(
        "project", "cloud_ci", health.classify_observation(verified()),
        resolved=True, resolution_reasons=frozenset({"cloud_ci_missing"}),
    )


def test_accepted_no_ci_publication_resolves_only_local_acceptance_and_outgoing_scan(monkeypatch):
    recorder = Mock(return_value="repair")
    monkeypatch.setattr(health, "record_finding", recorder)
    result = verified(ci={"state": "not_applicable", "sha": SHA})
    assert health.record_publication_observation("project", result) == "repair"
    observation = health.classify_observation(result)
    assert recorder.call_count == 2
    recorder.assert_any_call("project", "publication", observation,
                             resolved=True, resolution_reasons=frozenset({"local_acceptance_failed"}))
    recorder.assert_any_call("project", "outgoing_security", observation, resolved=True, outgoing_scan_verified=True)


def test_mirror_upload_without_receipt_never_resolves_local_acceptance(monkeypatch):
    recorder = Mock(return_value="repair")
    monkeypatch.setattr(health, "record_finding", recorder)
    mirrored = {"state": "not_required", "reason": "mirror_publication", "source_commit": SHA}
    result = verified(ci={"state": "not_applicable", "sha": SHA}, acceptance=mirrored, publication_mode="mirror")
    assert health.classify_observation(result)["state"] == "published"
    health.record_publication_observation("project", result)
    assert [call.args[1] for call in recorder.call_args_list] == ["outgoing_security"]


def test_verified_mirror_without_receipt_retains_acceptance_failures(monkeypatch):
    recorder = Mock(return_value="repair")
    monkeypatch.setattr(health, "record_finding", recorder)
    mirrored = {"state": "not_required", "reason": "mirror_publication", "source_commit": SHA}
    result = verified(acceptance=mirrored, publication_mode="mirror")
    health.record_publication_observation("project", result)
    recorder.assert_any_call("project", "publication", health.classify_observation(result), resolved=True,
                             retained_reasons=frozenset({"local_acceptance_failed", "nightly_acceptance_failed"}))
    accepted = Mock(return_value="repair")
    monkeypatch.setattr(health, "record_finding", accepted)
    health.record_publication_observation("project", verified())
    accepted.assert_any_call("project", "publication", health.classify_observation(verified()), resolved=True,
                             retained_reasons=frozenset())


def test_verified_publication_confirms_only_failed_nightly_repair_and_outgoing_scan(monkeypatch):
    recorder = Mock(return_value="repair")
    monkeypatch.setattr(health, "record_finding", recorder)
    health.record_publication_observation("project", verified())
    observation = health.classify_observation(verified())
    recorder.assert_any_call("project", "nightly_repair_attempt_failed", observation, resolved=True,
                             resolution_reasons=frozenset({"nightly_repair_attempt_failed"}))
    recorder.assert_any_call("project", "outgoing_security", observation, resolved=True, outgoing_scan_verified=True)


def test_reobserve_replays_the_newest_retained_receipt(monkeypatch, tmp_path):
    recorder = Mock(return_value="repair")
    monkeypatch.setattr(health, "record_finding", recorder)
    monkeypatch.setattr(health, "get_project_root_path", lambda _: str(tmp_path))
    receipt = {k: v for k, v in verified().items() if k != "observed_at"}
    monkeypatch.setattr("app.tasks.backup_manual_publish.latest_publication_receipt", lambda *_args: (
        tmp_path / "receipt.json", {"observed_at": "2026-10-03T08:00:00+00:00", "observation": receipt}))
    replay = health.reobserve_retained_publication("project")
    assert replay is not None and replay["state"] == "verified" and replay["repair_task_id"] == "repair"
    assert replay["observed_at"] == "2026-10-03T08:00:00+00:00"
    assert {call.args[1] for call in recorder.call_args_list} >= {"publication", "outgoing_security"}
    monkeypatch.setattr("app.tasks.backup_manual_publish.latest_publication_receipt", lambda *_args: None)
    assert health.reobserve_retained_publication("project") is None


@pytest.mark.parametrize("override", [
    {"publication_complete": False},
    {"ci": {"state": "pending", "sha": SHA}},
    {"ci": {"state": "failed", "sha": SHA}},
    {"ci": {"state": "not_applicable", "sha": SHA}},
])
def test_missing_ci_is_not_resolved_by_incomplete_or_failed_publication(monkeypatch, override):
    recorder = Mock()
    monkeypatch.setattr(health, "record_finding", recorder)
    health.record_publication_observation("project", verified(**override))
    assert "cloud_ci" not in {call.args[1] for call in recorder.call_args_list}


@pytest.mark.parametrize("state", ["pending", "unknown", "verified", "published"])
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


def test_mirror_publication_needs_no_receipt_only_in_mirror_mode():
    mirrored = {"state": "not_required", "reason": "mirror_publication", "source_commit": SHA}
    assert health.classify_observation(verified(acceptance=mirrored, publication_mode="mirror"))["state"] == "verified"
    assert health.classify_observation(verified(acceptance=mirrored, publication_mode="nightly"))["state"] != "verified"
    assert health.classify_observation(verified(acceptance={**mirrored, "source_commit": MERGE},
                                                publication_mode="mirror"))["state"] != "verified"


def test_fast_forward_publication_is_verified_on_the_accepted_commit_itself():
    assert health.classify_observation(verified(merge_sha=SHA, ci={
        "state": "success", "sha": SHA, "pr_checks": {"state": "success", "sha": SHA}}))["state"] == "verified"
