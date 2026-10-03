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
                                   "remote_api_unavailable", "remote_ci_unavailable"])
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
    assert {call.args[1] for call in recorder.call_args_list} == {"publication", "outgoing_security"}


@pytest.mark.parametrize("state", ["pending", "unknown", "verified"])
def test_normal_publication_states_allow_local_completion(state, monkeypatch):
    monkeypatch.setattr(health, "get_project_publication_health", lambda _pid: {
        "state": state, "repair_task_id": None, "unresolved_categories": [],
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
