"""Task-specific deployment and live evidence, independent of publication.

Requirements are owner-specified plan context. A code-only task does not acquire
a deployment requirement simply because it belongs to a managed project.
"""
from __future__ import annotations

import re
from typing import Any

import psycopg


def completion_gates(task: dict[str, Any], *, connection: psycopg.Connection | None = None) -> list[dict[str, Any]]:
    context = task.get("context") or {}
    requirements = task.get("completion_requirements") or context.get("completion_requirements") or {}
    verification = task.get("verification_result") or {}
    acceptance = verification.get("acceptance") or {}
    source = acceptance.get("source_commit") if acceptance.get("state") == "success" else None
    if not isinstance(source, str) or not re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", source):
        source = None
    gates: list[dict[str, Any]] = []
    deployment = verification.get("deployment") or {}
    live_validation = verification.get("live_validation") or {}
    family = "legacy"
    if task.get("project_id") and (requirements.get("deployment") or requirements.get("live_checks")):
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
    requires_acceptance = bool(
        task.get("commits") or task.get("files_to_modify") or context.get("files_to_modify")
        or task.get("files_to_create") or context.get("files_to_create")
        or requirements.get("acceptance") or requirements.get("deployment") or requirements.get("live_checks")
    )
    if requires_acceptance and not source:
        gates.append({"gate": "acceptance", "pass": False,
                      "detail": "Local acceptance has not succeeded for the implementation source."})
    if requirements.get("deployment"):
        deployed = deployment
        valid = native_valid if native else source and deployed.get("state") == "succeeded" and deployed.get("source_commit") == source
        if not valid:
            gates.append({"gate": "deployment", "pass": False,
                          "detail": "Required deployment has not succeeded for the accepted source."})
    required = requirements.get("live_checks") or []
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
    return gates
