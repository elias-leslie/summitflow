"""The public, source-bound acceptance seam for task and release adapters."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Literal

from cli.lib import acceptance

Materialization = Literal["actual", "isolated"]
Coverage = Literal["task", "full"]


@dataclass(frozen=True)
class AcceptanceReference:
    """Compact identity only; validation always reads the immutable artifact."""

    acceptance_id: str
    source_commit: str
    source_tree: str
    input_fingerprint: str
    acceptance_plan_fingerprint: str
    acceptance_artifact: str
    coverage: Coverage
    schema_version: int
    kind: str
    task_id: str
    scope: tuple[str, ...]
    scope_digest: str
    required_stages: tuple[dict[str, Any], ...]
    state: str = "success"
    outcome: str = "pass"

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["scope"] = list(self.scope)
        value["required_stages"] = list(self.required_stages)
        return value


@dataclass(frozen=True)
class AcceptanceResult:
    reference: AcceptanceReference
    receipt: dict[str, Any]
    materialization: Materialization
    reused: bool
    task_id: str
    scope: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {**self.receipt, "receipt_reference": self.reference.to_dict(),
                "reused": self.reused, "task_id": self.task_id, "scope": list(self.scope)}


def _result(receipt: dict[str, Any]) -> AcceptanceResult:
    summaries: list[dict[str, Any]] = []
    for check in receipt["checks"]:
        evidence = check["evidence"]
        stages: list[dict[str, Any]] = evidence.get("stages", [])
        if not stages:
            stages = [{"id": "scoped-quality" if receipt["coverage"] == "task" else "full-quality",
                       "state": evidence["state"], "coverage": evidence["coverage"], "required": True,
                       "command": check["command"]}]
        for stage in stages:
            summaries.append({"id": stage["id"], "state": stage["state"],
                              "coverage": stage.get("coverage", evidence["coverage"]),
                              "required": stage.get("required", True),
                              "covered_by": stage.get("covered_by"),
                              "command_sha256": hashlib.sha256(json.dumps(stage.get("command", []), separators=(",", ":")).encode()).hexdigest(),
                              "counts": stage.get("counts", {}),
                              "artifact_sha256": [item["sha256"] for item in stage.get("artifacts", [])]})
    reference = AcceptanceReference(
        acceptance_id=receipt["acceptance_id"], source_commit=receipt["source_commit"],
        source_tree=receipt["source_tree"], input_fingerprint=receipt["input_fingerprint"],
        acceptance_plan_fingerprint=receipt["acceptance_plan_fingerprint"],
        acceptance_artifact=receipt["acceptance_artifact"], coverage=receipt["coverage"],
        schema_version=receipt["schema_version"], kind=receipt["kind"],
        task_id=receipt.get("task_id", ""), scope=tuple(receipt.get("scope", ())),
        scope_digest=receipt["scope_digest"],
        required_stages=tuple(summaries),
    )
    return AcceptanceResult(reference, receipt, receipt["inputs"]["execution"]["basis"],
                            bool(receipt.get("reused")), reference.task_id, reference.scope)


def validate_source_receipt(repo: Path, receipt: Mapping[str, Any] | Path, *, sha: str | None = None,
                            evidence_directory: Path | None = None) -> AcceptanceResult:
    """Validate the source, consumed inputs, coverage and artifacts once."""
    return _result(acceptance.validate_acceptance_receipt(repo, receipt, sha=sha,
                                                        evidence_directory=evidence_directory))


def accept_source(repo: Path, *, sha: str, materialization: Materialization,
                  scope: Sequence[str] = (), task_id: str = "", reuse: bool = True,
                  coverage: Coverage = "full", required_stages: Sequence[str] = (),
                  runner: acceptance.AcceptanceRunner | None = None) -> AcceptanceResult:
    """Choose execution explicitly; failures never select another source mode."""
    scope = tuple(sorted({path.strip() for path in scope if path.strip()}))
    if materialization == "actual":
        receipt = acceptance.accept_revision(repo, sha=sha, scope=scope, task_id=task_id,
                                             reuse=reuse, runner=runner, coverage=coverage,
                                             required_stages=required_stages)
    elif materialization == "isolated":
        if runner is not None:
            raise acceptance.AcceptanceError("Isolated acceptance does not accept an ambient runner")
        from cli.commands.done_task_acceptance import accept_isolated_revision

        receipt = accept_isolated_revision(repo, sha=sha, scope=tuple(scope), task_id=task_id, reuse=reuse,
                                           coverage=coverage, required_stages=required_stages)
    else:
        raise acceptance.AcceptanceError("Acceptance materialization must be actual or isolated")
    return _result(receipt)


def require_scope_matches_revision(repo: Path, sha: str, scope: tuple[str, ...]) -> None:
    from cli.commands.done_task_acceptance import require_scope_matches_revision as require_scope

    require_scope(repo, sha, scope)


def require_task_created_paths(repo: Path, sha: str, task: dict[str, Any]) -> None:
    from cli.commands.done_task_acceptance import require_task_created_paths as require_paths

    require_paths(repo, sha, task)
