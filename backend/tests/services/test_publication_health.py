"""Nightly evidence is source-bound; ordinary local completion stays independent."""
from datetime import UTC, datetime
from unittest.mock import Mock

import pytest

from app.services import publication_health as health
from app.services.task_acceptance import completion_gates
from app.services.task_closeout import checkpoint_state

SHA = "a" * 40
MERGE = "b" * 40


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
    assert "Nightly publication: published;" in text and "CI=not_applicable;" in text
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


def test_no_ci_publication_never_resolves_findings_or_confirms_repair(monkeypatch):
    recorder = Mock()
    monkeypatch.setattr(health, "record_finding", recorder)
    result = verified(ci={"state": "not_applicable", "sha": SHA})
    assert health.record_publication_observation("project", result) is None
    recorder.assert_not_called()
    observation = health.classify_observation(result)
    assert health.confirmation_for_source("project", SHA, health=observation) is None
    monkeypatch.setattr(health, "get_project_publication_health", lambda _pid: {
        **observation, "repair_task_id": "repair", "unresolved_categories": [],
    })
    assert health.publication_completion_gates({"id": "repair", "project_id": "project"}, SHA)[0]["gate"] == "remote_confirmation"


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


def test_actionable_project_defect_blocks_shared_completion(monkeypatch):
    monkeypatch.setattr(health, "get_project_publication_health", lambda _pid: {
        "state": "blocked", "repair_task_id": "repair", "unresolved_categories": ["codeql"],
    })
    gates = completion_gates({"id": "normal", "project_id": "project", "verification_result": {}})
    assert [gate["gate"] for gate in gates] == ["project_repair"]


def test_repair_needs_confirmed_accepted_source(monkeypatch):
    monkeypatch.setattr(health, "get_project_publication_health", lambda _pid: {
        "state": "verified", "repair_task_id": "repair", "unresolved_categories": [],
    })
    monkeypatch.setattr(health, "confirmation_for_source", lambda _pid, _source: None)
    assert health.publication_completion_gates({"id": "repair", "project_id": "project"}, SHA)[0]["gate"] == "remote_confirmation"


def test_remote_wait_not_shown_complete_even_if_status_drifted():
    assert checkpoint_state("completed", {"acceptance": {"state": "success"},
        "closeout": {"state": "pending", "require_remote_confirmation": True}})[0] == "waiting_checks"


@pytest.mark.parametrize(("observed", "source", "failed"), [
    ("2026-10-01T08:00:00+00:00", SHA, False),
    ("2026-10-03T08:00:00+00:00", SHA, True),
    ("2026-10-03T08:00:00+00:00", None, False),
])
def test_only_new_candidate_bound_failure_ends_wait(observed, source, failed, monkeypatch):
    monkeypatch.setattr(health, "get_project_publication_health", lambda _pid: {
        "state": "blocked", "observed_at": observed, "source_commit": source, "findings": {},
    })
    assert health.repair_attempt_failed("project", SHA, "2026-10-02T08:00:00+00:00") is failed


@pytest.mark.parametrize(("now", "start"), [
    ("2026-10-02T09:59:00+00:00", "2026-10-01T06:00:00+00:00"),
    ("2026-10-02T10:00:00+00:00", "2026-10-02T06:00:00+00:00"),
    ("2026-11-02T11:00:00+00:00", "2026-11-02T07:00:00+00:00"),
])
def test_last_due_window_obeys_owner_timezone_and_dst(now, start):
    assert health._last_due_window(datetime.fromisoformat(now)) == datetime.fromisoformat(start).astimezone(UTC)
