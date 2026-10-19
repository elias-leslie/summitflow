"""Canonical acceptance operations, evaluated with the source account's identity."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

from app.utils.agent_jobs import run_installed_agent_job


def source_acceptance_job(repo: Path, operation: str, **parameters: Any) -> dict[str, Any]:
    from .acceptance import AcceptanceError

    repo = repo.absolute()
    try:
        return run_installed_agent_job(
            __name__, {"project": str(repo), "operation": operation, "parameters": parameters}, project=repo,
        )
    except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
        raise AcceptanceError("Agent acceptance is unavailable") from exc


def run_job(payload: dict[str, Any]) -> dict[str, Any]:
    from cli.commands.done_task_acceptance import accept_isolated_revision
    from cli.lib import acceptance

    repo = Path(payload["project"])
    operation = payload["operation"]
    parameters = dict(payload["parameters"])
    for name in ("scope", "required_stages"):
        if name in parameters:
            parameters[name] = tuple(parameters[name])
    for name in ("evidence_directory",):
        if parameters.get(name) is not None:
            parameters[name] = Path(parameters[name])
    if operation == "lookup":
        return {"receipt": acceptance.receipt_for_commit(repo, **parameters)}
    if operation in {"validate", "persist"}:
        receipt = parameters["receipt"]
        if isinstance(receipt, str):
            parameters["receipt"] = Path(receipt)
        function = acceptance.validate_acceptance_receipt if operation == "validate" else acceptance.persist_validated_receipt
        return function(repo, **parameters)
    if operation == "isolated":
        return accept_isolated_revision(repo, **parameters)
    if operation == "accept":
        return acceptance.accept_revision(repo, **parameters)
    raise ValueError("Unknown acceptance operation")
