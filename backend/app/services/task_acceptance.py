"""Task-specific deployment and live evidence, independent of publication.

Requirements are owner-specified plan context. A code-only task does not acquire
a deployment requirement simply because it belongs to a managed project.
"""
from __future__ import annotations

import re
from typing import Any


def completion_gates(task: dict[str, Any]) -> list[dict[str, Any]]:
    context = task.get("context") or {}
    requirements = task.get("completion_requirements") or context.get("completion_requirements") or {}
    verification = task.get("verification_result") or {}
    acceptance = verification.get("acceptance") or {}
    source = acceptance.get("source_commit") if acceptance.get("state") == "success" else None
    if not isinstance(source, str) or not re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", source):
        source = None
    gates: list[dict[str, Any]] = []
    # Administrative/research tasks may complete without inventing code changes.
    # A declared implementation, recorded commit or source-bound live/deploy
    # requirement cannot use that exception to bypass local acceptance.
    requires_acceptance = bool(
        task.get("commits") or task.get("files_to_modify") or context.get("files_to_modify")
        or requirements.get("acceptance") or requirements.get("deployment") or requirements.get("live_checks")
    )
    if requires_acceptance and not source:
        gates.append({"gate": "acceptance", "pass": False,
                      "detail": "Local acceptance has not succeeded for the implementation source."})
    if requirements.get("deployment"):
        deployed = verification.get("deployment") or {}
        if not source or deployed.get("state") != "succeeded" or deployed.get("source_commit") != source:
            gates.append({"gate": "deployment", "pass": False,
                          "detail": "Required deployment has not succeeded for the accepted source."})
    required = requirements.get("live_checks") or []
    if required:
        live = verification.get("live_validation") or {}
        passed = {
            check.get("id") for check in live.get("checks", [])
            if isinstance(check, dict) and check.get("state") == "success"
            and check.get("artifact") and re.fullmatch(r"[0-9a-f]{64}", str(check.get("sha256") or ""))
        } if source and live.get("source_commit") == source else set()
        missing = [name for name in required if name not in passed]
        if missing:
            gates.append({"gate": "live_validation", "pass": False, "detail": missing})
    return gates
