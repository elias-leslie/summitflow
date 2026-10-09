"""Local completion requirements stay independent from optional publication."""
import pytest

from app.services.task_acceptance import assess_completion, completion_gates
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


def test_task_coverage_completes_owned_work_without_claiming_release_readiness():
    assessment = assess_completion({"commits": [SHA], "verification_result": {
        "acceptance": {"state": "success", "outcome": "pass", "source_commit": SHA, "coverage": "task"},
    }})
    assert assessment.complete
    assert assessment.source_commit == SHA
    assert not assessment.release_ready


def test_full_coverage_satisfies_task_evidence_and_records_release_coverage():
    assessment = assess_completion({"commits": [SHA], "verification_result": {
        "acceptance": {"state": "success", "source_commit": SHA, "coverage": "full"},
    }})
    assert assessment.complete and assessment.release_ready


def test_owner_can_require_full_acceptance_for_a_task():
    required = {"commits": [SHA], "completion_requirements": {"acceptance": "full"},
                "verification_result": {"acceptance": {"state": "success", "source_commit": SHA, "coverage": "task"}}}
    assert [gate["gate"] for gate in completion_gates(required)] == ["acceptance"]


@pytest.mark.parametrize("stage", [None, {"id": "api-contract", "state": "failed", "coverage": "task"},
                                  {"id": "api-contract", "state": "pass", "coverage": "unknown"}])
def test_declared_acceptance_stage_requires_successful_declared_coverage(stage):
    required = {"completion_requirements": {"acceptance_stages": ["api-contract"]},
                "verification_result": {"acceptance": {"state": "success", "source_commit": SHA, "coverage": "task",
                                                       "required_stages": [stage] if stage else []}}}
    assert [gate["gate"] for gate in completion_gates(required)] == ["acceptance"]


def test_declared_task_stage_is_satisfied_by_validated_stage_summary():
    assert completion_gates({"completion_requirements": {"acceptance_stages": ["api-contract"]},
        "verification_result": {"acceptance": {"state": "success", "outcome": "pass", "source_commit": SHA,
            "coverage": "task", "required_stages": [{"id": "api-contract", "state": "pass", "coverage": "task"}]}}}) == []


def test_declared_focused_stage_can_satisfy_exact_task_evidence_without_full_coverage():
    assessment = assess_completion({"completion_requirements": {"acceptance_stages": ["fleet"]},
        "verification_result": {"acceptance": {"state": "success", "source_commit": SHA, "coverage": "task",
            "required_stages": [{"id": "fleet", "state": "pass", "coverage": "focused"}]}}})
    assert assessment.complete
    assert not assessment.release_ready


def test_full_coverage_does_not_substitute_for_missing_explicit_stage_evidence():
    required = {"completion_requirements": {"acceptance_stages": ["fleet-proof"]},
                "verification_result": {"acceptance": {"state": "success", "source_commit": SHA, "coverage": "full",
                                                       "required_stages": [{"id": "other-suite", "state": "pass", "coverage": "full"}]}}}
    assessment = assess_completion(required)
    assert [gate["gate"] for gate in assessment.gates] == ["acceptance"]
    assert assessment.source_commit == SHA
    assert assessment.release_ready


@pytest.mark.parametrize("covering", [
    {"id": "python", "state": "pass", "coverage": "full", "required": True},
    {"id": "python", "state": "fail", "coverage": "full", "required": True},
    {"id": "python", "state": "pass", "coverage": "focused", "required": True},
    {"id": "python", "state": "pass", "coverage": "full", "required": False},
])
def test_elided_stage_requires_actual_successful_required_full_covering_suite(covering):
    assessment = assess_completion({"completion_requirements": {"acceptance_stages": ["fleet"]},
        "verification_result": {"acceptance": {"state": "success", "source_commit": SHA, "coverage": "full",
            "required_stages": [{"id": "fleet", "state": "not-applicable", "coverage": "full", "covered_by": "python"}, covering]}}})
    assert assessment.complete is (covering["state"] == "pass" and covering["coverage"] == "full" and covering["required"])


def test_plan_normalization_preserves_acceptance_coverage_and_stage_requirements():
    from app.services.task_plan_context import build_task_plan_context

    requirements = {"acceptance": "full", "acceptance_stages": ["fleet-proof"], "deployment": False, "live_checks": []}
    assert build_task_plan_context({"completion_requirements": requirements})["completion_requirements"] == requirements


@pytest.mark.parametrize("receipt", [
    {"state": "success", "source_commit": SHA, "coverage": "focused"},
    {"state": "success", "outcome": "unavailable", "source_commit": SHA, "coverage": "task"},
    {"state": "blocked", "source_commit": SHA, "coverage": "full"},
])
def test_incomplete_acceptance_never_satisfies_task_evidence(receipt):
    assert [gate["gate"] for gate in completion_gates({"commits": [SHA], "verification_result": {"acceptance": receipt}})] == ["acceptance"]


@pytest.mark.parametrize("requirements", [{"acceptance": "focused"}, {"acceptance": 0},
                                         {"acceptance_stages": ["same", "same"]}, {"live_checks": "check"}])
def test_invalid_owner_requirements_fail_closed(requirements):
    assert [gate["gate"] for gate in completion_gates({"completion_requirements": requirements})] == ["completion_requirements"]
