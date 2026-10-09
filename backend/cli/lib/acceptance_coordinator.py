"""The public, source-bound acceptance seam for task and release adapters."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Literal, cast

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
    declared_stages: tuple[str, ...]
    required_stages: tuple[dict[str, Any], ...]
    state: str = "success"
    outcome: str = "pass"

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["scope"] = list(self.scope)
        value["declared_stages"] = list(self.declared_stages)
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


def _result(receipt: dict[str, Any], proof: dict[str, Any]) -> AcceptanceResult:
    summaries: list[dict[str, Any]] = []
    for check in proof["checks"]:
        evidence = check["evidence"]
        stages: list[dict[str, Any]] = evidence.get("stages", [])
        if not stages:
            stages = [{"id": "scoped-quality" if proof["coverage"] == "task" else "full-quality",
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
        acceptance_id=proof["acceptance_id"], source_commit=proof["source_commit"],
        source_tree=proof["source_tree"], input_fingerprint=proof["input_fingerprint"],
        acceptance_plan_fingerprint=proof["acceptance_plan_fingerprint"],
        acceptance_artifact=proof["acceptance_artifact"], coverage=proof["coverage"],
        schema_version=proof["schema_version"], kind=proof["kind"],
        task_id=proof.get("task_id", ""), scope=tuple(proof.get("scope", ())),
        scope_digest=proof["scope_digest"], declared_stages=tuple(proof["plan"].get("required_stages", ())),
        required_stages=tuple(summaries),
    )
    return AcceptanceResult(reference, receipt, receipt["inputs"]["execution"]["basis"],
                            bool(receipt.get("reused")), receipt.get("task_id", ""), tuple(receipt.get("scope", ())))


def _reference_artifact(repo: Path, reference: Mapping[str, Any]) -> Path:
    try:
        path = Path(str(reference.get("acceptance_artifact") or ""))
        directory = acceptance.acceptance_artifact_directory(repo)
        root = directory.resolve(strict=True)
        resolved = path.resolve(strict=True)
        if (root != directory.absolute() or not path.is_absolute() or path.is_symlink() or not resolved.is_file()
                or resolved.parent != root or resolved.name != f"{reference.get('acceptance_id')}.json"):
            raise acceptance.AcceptanceError("Acceptance reference is outside its immutable evidence root; explicit retention is required")
        return resolved
    except OSError as exc:
        raise acceptance.AcceptanceError("Acceptance reference artifact is unavailable; explicit retention is required") from exc


def validate_source_receipt(repo: Path, receipt: Mapping[str, Any] | Path, *, sha: str | None = None,
                            evidence_directory: Path | None = None) -> AcceptanceResult:
    """Validate source proof without creating evidence or importing raw material."""
    reference = cast(Mapping[str, Any], receipt) if isinstance(receipt, Mapping) and "source" not in receipt else None
    artifact = _reference_artifact(repo, reference) if reference is not None else receipt
    selected = acceptance.validate_acceptance_receipt(repo, artifact, sha=sha,
        evidence_directory=evidence_directory if reference is None else None)
    proof = selected if reference is not None else acceptance.validate_acceptance_receipt(
        repo, _reference_artifact(repo, selected), sha=sha)
    result = _result(selected, proof)
    if reference is not None and json.dumps(dict(reference), sort_keys=True) != json.dumps(result.reference.to_dict(), sort_keys=True):
        raise acceptance.AcceptanceError("Compact acceptance reference differs from its validated immutable proof")
    return result


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
    proof = acceptance.validate_acceptance_receipt(repo, _reference_artifact(repo, receipt), sha=sha)
    result = _result(receipt, proof)
    if result.reused and coverage == "task" and (result.reference.scope != scope
            or result.reference.declared_stages != tuple(sorted(set(required_stages)))):
        raise acceptance.AcceptanceError("Task acceptance reuse requires the exact owned scope and declared stages")
    return result


def require_scope_matches_revision(repo: Path, sha: str, scope: tuple[str, ...]) -> None:
    from cli.commands.done_task_acceptance import require_scope_matches_revision as require_scope

    require_scope(repo, sha, scope)


def require_task_created_paths(repo: Path, sha: str, task: dict[str, Any]) -> None:
    from cli.commands.done_task_acceptance import require_task_created_paths as require_paths

    require_paths(repo, sha, task)
