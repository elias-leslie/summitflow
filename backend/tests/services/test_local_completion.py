"""Local completion requirements stay independent from optional publication."""
from app.services.task_acceptance import completion_gates
from app.services.task_closeout import checkpoint_state

SHA = "a" * 40


def test_completed_local_task_is_not_shown_as_waiting_for_publication():
    state, message = checkpoint_state("completed", {
        "acceptance": {"state": "success", "source_commit": SHA},
        "closeout": {"state": "pending"},
    })
    assert state == "complete"
    assert "publication is independent" in message


def task(**verification):
    return {"context": {"completion_requirements": {
        "deployment": True, "live_checks": ["login-isolation"],
    }}, "verification_result": {"acceptance": {"state": "success", "source_commit": SHA}, **verification}}


def test_missing_required_live_work_blocks_even_after_publication():
    gates = completion_gates(task(publication={"publication_complete": True}))
    assert {gate["gate"] for gate in gates} == {"deployment", "live_validation"}


def test_required_evidence_must_match_accepted_source():
    gates = completion_gates(task(
        deployment={"state": "succeeded", "source_commit": "b" * 40},
        live_validation={"source_commit": SHA, "checks": [
            {"id": "login-isolation", "state": "failed", "artifact": "/evidence/result.json"},
        ]},
    ))
    assert len(gates) == 2


def test_verified_local_work_finishes_without_publication():
    assert completion_gates(task(
        deployment={"state": "succeeded", "source_commit": SHA},
        live_validation={"source_commit": SHA, "checks": [
            {"id": "login-isolation", "state": "success", "artifact": "/evidence/result.json", "sha256": "c" * 64},
        ]},
    )) == []


def test_code_only_work_does_not_invent_deployment_requirement():
    assert completion_gates({"context": {"files_to_modify": ["app.py"]}, "verification_result": {
        "acceptance": {"state": "success", "source_commit": SHA},
        "publication": {"ci": {"state": "failed"}},
    }}) == []


def test_recorded_commit_requires_acceptance_even_without_file_plan():
    gates = completion_gates({"commits": [SHA], "verification_result": {}})
    assert [gate["gate"] for gate in gates] == ["acceptance"]


def test_declared_new_file_requires_implementation_acceptance():
    gates = completion_gates({"context": {"files_to_create": ["new.py"]}, "verification_result": {}})
    assert [gate["gate"] for gate in gates] == ["acceptance"]


def test_administrative_task_does_not_invent_implementation_acceptance():
    assert completion_gates({"context": {}, "verification_result": {}}) == []


def test_live_pass_without_durable_evidence_is_not_enough():
    gates = completion_gates(task(
        deployment={"state": "succeeded", "source_commit": SHA},
        live_validation={"source_commit": SHA, "checks": [{"id": "login-isolation", "state": "success"}]},
    ))
    assert [gate["gate"] for gate in gates] == ["live_validation"]


def test_project_publication_failure_is_not_a_completion_gate(monkeypatch):
    monkeypatch.setattr("app.services.publication_health.publication_completion_gates",
                        lambda *a, **kw: (_ for _ in ()).throw(AssertionError("No project publication gate")), raising=False)
    assert completion_gates({"id": "task-local", "project_id": "example", "commits": [SHA],
                             "verification_result": {"acceptance": {"state": "success", "source_commit": SHA}}}) == []


def test_retained_remote_wait_is_not_shown_as_active_local_work():
    state, message = checkpoint_state("pending", {"closeout": {"state": "pending", "require_remote_confirmation": True},
                                                  "publication": {"ci": {"state": "failed"}}})
    assert state == "open"
    assert "does not establish a live agent" in message
