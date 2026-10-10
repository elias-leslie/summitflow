"""Task-specific deployment and live evidence, independent of publication.

Requirements are owner-specified plan context. A code-only task does not acquire
a deployment requirement simply because it belongs to a managed project.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Literal

import psycopg

_AMENDMENT_KINDS = {"waived", "replaced"}


def completion_amendments(declared: Any) -> list[dict[str, Any]]:
    """Owner-recorded waivers and replacements; each carries a reason and actor."""
    raw = declared.get("waivers") if isinstance(declared, dict) else None
    return [item for item in raw or [] if isinstance(item, dict) and item.get("kind") in _AMENDMENT_KINDS
            and isinstance(item.get("check"), str) and str(item.get("reason") or "").strip()]


def waived_checks(declared: Any) -> set[str]:
    return {item["check"] for item in completion_amendments(declared) if item["kind"] == "waived"}


def active_live_checks(declared: Any) -> list[str]:
    """Declared live checks still owed evidence; a waived check is satisfied by its waiver."""
    checks = declared.get("live_checks") if isinstance(declared, dict) else None
    waived = waived_checks(declared)
    return [check for check in checks or [] if check not in waived]


def amend_completion_requirement(task_id: str, check: str, *, reason: str, actor: str,
                                 replacement: str | None = None) -> dict[str, Any]:
    """Waive or replace one live check or done_when entry, keeping the approved plan."""
    from datetime import UTC, datetime

    from app.storage.events import log_task_event
    from app.storage.task_spirit import get_task_spirit, update_task_spirit
    from app.storage.tasks import get_task

    check, reason = check.strip(), reason.strip()
    if not reason:
        raise ValueError("Record the owner decision with --reason")
    task = get_task(task_id)
    if not task:
        raise ValueError(f"Task not found: {task_id}")
    if task.get("status") in {"completed", "cancelled"}:
        raise ValueError(f"Task {task_id} is {task.get('status')}; its requirements are historical")
    spirit = get_task_spirit(str(task["id"]))
    if spirit is None:
        raise ValueError(f"Task {task_id} has no plan to amend")
    context = dict(spirit.get("context") or {})
    declared = dict(context.get("completion_requirements") or {})
    live = list(declared.get("live_checks") or [])
    done_when = list(spirit.get("done_when") or [])
    field = "live_checks" if check in live else "done_when" if check in done_when else None
    if field is None:
        raise ValueError(f"No live check or done_when entry matches exactly: {check}")
    if check in waived_checks(declared):
        raise ValueError(f"Already waived: {check}")
    record: dict[str, Any] = {"check": check, "field": field, "kind": "replaced" if replacement is not None else "waived",
                              "reason": reason, "actor": actor, "at": datetime.now(UTC).isoformat()}
    target = live if field == "live_checks" else done_when
    if replacement is not None:
        replacement = replacement.strip()
        if not replacement or replacement in target:
            raise ValueError("A replacement must be a new nonempty entry")
        record["replacement"] = replacement
        target[target.index(check)] = replacement
    declared["live_checks"] = live
    declared["waivers"] = [*completion_amendments(declared), record]
    context["completion_requirements"] = declared
    update_task_spirit(str(task["id"]), context=context, **({"done_when": done_when} if field == "done_when" else {}))
    action = f"replaced with '{replacement}'" if replacement is not None else "waived"
    log_task_event(str(task["id"]), f"Completion requirement '{check}' {action} by {actor}: {reason}",
                   source="st-update", event_type="completion_requirement_amended", attributes=record)
    return record


def format_amendment(item: dict[str, Any]) -> str:
    action = f"replaced by '{item['replacement']}'" if item.get("kind") == "replaced" else "waived"
    return f"'{item['check']}' {action} ({item.get('actor') or 'unknown'}, {item.get('at') or '?'}): {item['reason']}"


@dataclass(frozen=True)
class CompletionRequirements:
    """The evidence the owner declared for this task, independent of release."""

    acceptance: bool
    coverage: Literal["task", "full"] = "task"
    stages: tuple[str, ...] = ()
    deployment: bool = False
    live_checks: tuple[str, ...] = ()

    @classmethod
    def from_task(cls, task: dict[str, Any]) -> CompletionRequirements:
        context = task.get("context") or {}
        declared = task.get("completion_requirements") or context.get("completion_requirements") or {}
        if not isinstance(declared, dict):
            raise ValueError("Completion requirements must be an object")
        acceptance = declared.get("acceptance", "task")
        if not (type(acceptance) is bool or (isinstance(acceptance, str) and acceptance in {"task", "full"})):
            raise ValueError("Acceptance coverage must be task or full")
        stages = declared.get("acceptance_stages") or []
        live_checks = declared.get("live_checks") or []
        for label, values in (("acceptance stages", stages), ("live checks", live_checks)):
            if (not isinstance(values, list | tuple) or any(not isinstance(value, str) or not value.strip() for value in values)
                    or len(set(values)) != len(values)):
                raise ValueError(f"Required {label} must be unique nonempty IDs")
        live_checks = [check for check in live_checks if check not in waived_checks(declared)]
        # An implementation still requires evidence when deployment is waived.
        # False retains the historical administrative-task declaration; it is
        # never permission to complete unverified code changes.
        required = bool(
            task.get("commits") or task.get("files_to_modify") or context.get("files_to_modify")
            or task.get("files_to_create") or context.get("files_to_create")
            or declared.get("acceptance") or stages or declared.get("deployment") or live_checks
        )
        return cls(required, "full" if acceptance == "full" else "task", tuple(stages),
                   bool(declared.get("deployment")), tuple(live_checks))

    def satisfied_by(self, acceptance: dict[str, Any]) -> bool:
        """A validated source reference must cover the declared task evidence."""
        source, coverage = _accepted_source(acceptance)
        return _acceptance_satisfies(acceptance, self, source, coverage)


@dataclass(frozen=True)
class CompletionAssessment:
    """Task evidence outcome, with project release coverage stated separately."""

    requirements: CompletionRequirements
    source_commit: str | None
    coverage: Literal["task", "full"] | None
    gates: tuple[dict[str, Any], ...]

    @property
    def complete(self) -> bool:
        return not self.gates

    @property
    def release_ready(self) -> bool:
        """Only a successful full acceptance establishes local release coverage."""
        return bool(self.source_commit) and self.coverage == "full"


def _accepted_source(acceptance: dict[str, Any]) -> tuple[str | None, Literal["task", "full"] | None]:
    source = acceptance.get("source_commit") if acceptance.get("state") == "success" else None
    # Historical success descriptors were emitted exclusively by the full
    # validator. Preserve their meaning; a new task receipt always has coverage.
    coverage = acceptance.get("coverage", "full")
    if (not isinstance(source, str) or not re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", source)
            or coverage not in {"task", "full"} or acceptance.get("outcome", "pass") != "pass"):
        return None, None
    return source, coverage


def _acceptance_satisfies(acceptance: dict[str, Any], requirements: CompletionRequirements,
                          source: str | None, coverage: str | None) -> bool:
    if not source or (requirements.coverage == "full" and coverage != "full"):
        return False
    if requirements.stages:
        stages = acceptance.get("required_stages") or []
        indexed = {stage.get("id"): stage for stage in stages if isinstance(stage, dict)}
        stage_coverage = {"task", "full", "focused"} if coverage == "task" else {"task", "full"}
        passed = {name for name, stage in indexed.items() if stage.get("state") in {"success", "pass"}
                  and stage.get("outcome", "pass") == "pass" and stage.get("coverage") in stage_coverage}
        # The canonical validator may record that a required full suite already
        # covers another declared stage. Preserve the elided stage's truthful
        # not-applicable outcome; only the actual successful full suite proves it.
        for name, stage in indexed.items():
            covering = indexed.get(stage.get("covered_by")) or {}
            if (stage.get("state") == "not-applicable" and stage.get("covered_by") in passed
                    and covering.get("state") in {"pass", "success"} and covering.get("outcome", "pass") == "pass"
                    and covering.get("coverage") == "full" and covering.get("required") is True):
                passed.add(name)
        if not set(requirements.stages).issubset(passed):
            return False
    return True


def assess_completion(task: dict[str, Any], *, connection: psycopg.Connection | None = None) -> CompletionAssessment:
    """Assess declared task evidence without acquiring project release gates."""
    context = task.get("context") or {}
    try:
        required_evidence = CompletionRequirements.from_task(task)
    except ValueError as exc:
        return CompletionAssessment(CompletionRequirements(True), None, None,
            ({"gate": "completion_requirements", "pass": False, "detail": str(exc)},))
    requirements = task.get("completion_requirements") or context.get("completion_requirements") or {}
    verification = task.get("verification_result") or {}
    acceptance = verification.get("acceptance") or {}
    source, coverage = _accepted_source(acceptance)
    gates: list[dict[str, Any]] = []
    deployment = verification.get("deployment") or {}
    live_validation = verification.get("live_validation") or {}
    family = "legacy"
    if task.get("project_id") and (requirements.get("deployment") or active_live_checks(requirements)):
        from .native_deployment import deployment_evidence_family

        family = deployment_evidence_family(str(task["project_id"]))
    native_fields = {"receipt_id", "accepted_source_commit", "source_binding"}
    # Native ownership authenticates deployments, not every owner-declared
    # source-bound check with deployment explicitly waived. Supplied deployment
    # evidence or native descriptors still require the exact server receipt.
    native = (
        (
            family != "legacy" and (
                requirements.get("deployment") is not False or bool(deployment) or "kind" in live_validation
            )
        )
        or bool(native_fields & (set(deployment) | set(live_validation)))
        or deployment.get("kind") == "native_deployment_observation.v1"
        or live_validation.get("kind") == "native_deployment_observation.v1"
    )
    native_valid = False
    if native:
        from .native_deployment import NativeDeploymentError, validate_native_evidence

        try:
            validate_native_evidence(deployment, live_validation, task_id=str(task.get("id") or ""),
                                     project=str(task.get("project_id") or ""), acceptance=acceptance)
            native_valid = bool(source) and family != "unknown"
        except (NativeDeploymentError, ValueError, OSError, KeyError, TypeError):
            # Native provenance is reloaded even when task verification JSON was
            # supplied through another API. A forged flag never changes a gate.
            native_valid = False
    # Administrative/research tasks may complete without inventing code changes.
    # A declared implementation, recorded commit or source-bound live/deploy
    # requirement cannot use that exception to bypass local acceptance.
    if required_evidence.acceptance and not required_evidence.satisfied_by(acceptance):
        gates.append({"gate": "acceptance", "pass": False,
                      "detail": f"Required {required_evidence.coverage} acceptance has not succeeded for the implementation source."})
    if requirements.get("deployment"):
        deployed = deployment
        valid = native_valid if native else source and deployed.get("state") == "succeeded" and deployed.get("source_commit") == source
        if not valid:
            gates.append({"gate": "deployment", "pass": False,
                          "detail": "Required deployment has not succeeded for the accepted source."})
    required = active_live_checks(requirements)
    if required:
        live = live_validation
        passed = {
            check.get("id") for check in live.get("checks", [])
            if isinstance(check, dict) and check.get("state") == "success"
            and check.get("artifact") and re.fullmatch(r"[0-9a-f]{64}", str(check.get("sha256") or ""))
        } if native_valid or (not native and source and live.get("source_commit") == source) else set()
        missing = [name for name in required if name not in passed]
        if missing:
            gates.append({"gate": "live_validation", "pass": False, "detail": missing})
    return CompletionAssessment(required_evidence, source, coverage, tuple(gates))


def completion_gates(task: dict[str, Any], *, connection: psycopg.Connection | None = None) -> list[dict[str, Any]]:
    """Compatibility adapter for task readiness and atomic status transitions."""
    return list(assess_completion(task, connection=connection).gates)


def hydrate_completion_task(task: dict[str, Any]) -> dict[str, Any]:
    """Read the canonical task plan without replacing its owned claim revision."""
    from app.services.task_plan_context import hydrate_task_plan_fields
    from app.storage.task_spirit import get_task_spirit

    spirit = get_task_spirit(str(task["id"]))
    if spirit is not None:
        task = {**task, "context": spirit.get("context") or {}}
        for field in ("completion_requirements", "files_to_modify", "files_to_create"):
            task.pop(field, None)
    return hydrate_task_plan_fields(task)


def load_completion_assessment(task_id: str) -> CompletionAssessment:
    """Read the canonical plan and subtask state for CLI and backend readiness."""
    from app.storage.subtasks import get_subtasks_for_task
    from app.storage.tasks import get_task

    task = get_task(task_id)
    if not task:
        raise ValueError("Completion task no longer exists")
    task = hydrate_completion_task(task)
    assessment = assess_completion(task)
    synthetic_skips = {str(item).split(":", 1)[0] for item in task.get("syncable_subtasks_skipped") or []
                       if isinstance(item, str) and item.endswith(":no-steps")}
    incomplete = []
    for subtask in get_subtasks_for_task(str(task["id"]), True):
        if subtask.get("passes"):
            continue
        subtask_id = str(subtask.get("subtask_id") or "")
        if (subtask_id in synthetic_skips and not (subtask.get("steps") or subtask.get("steps_from_table"))
                and not (subtask.get("step_summary") or {}).get("total")):
            continue
        incomplete.append(subtask_id)
    gates = (({"gate": "subtasks", "pass": False, "detail": incomplete[:5]},) if incomplete else ()) + assessment.gates
    return CompletionAssessment(assessment.requirements, assessment.source_commit, assessment.coverage, gates)
