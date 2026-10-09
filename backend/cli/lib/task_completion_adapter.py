"""Owned task acceptance through the public source coordinator and task policy."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any

from app.services.task_acceptance import CompletionRequirements, hydrate_completion_task

from .acceptance import AcceptanceError
from .acceptance_coordinator import AcceptanceResult, Materialization


class AcceptedTaskWork(dict[str, Any]):
    """Compact durable proof with its exact pre-gate claim carried in-process."""

    def __init__(self, result: AcceptanceResult, claim: dict[str, Any]):
        super().__init__(result.reference.to_dict())
        self.reused = result.reused
        self.completion_claim = {**claim, "verification_result": {
            **(claim.get("verification_result") or {}), "acceptance": dict(self)}}


def accept_owned_task_work(repo: Path, task_id: str, project_id: str, *, claim: dict[str, Any],
                           paths: tuple[str, ...] = (),
                           acceptance_receipt: dict[str, Any] | None = None) -> AcceptedTaskWork:
    """Accept declared evidence, preserve foreign work, and attach by claim CAS."""
    from app.storage.tasks.closeout import store_owned_acceptance

    from .acceptance import repo_lock
    from .acceptance_coordinator import accept_source, validate_source_receipt
    from .commit_workflow import run_git
    from .task_closeout_adapter import LocalCloseoutOperations

    task = hydrate_completion_task({**claim, "id": claim.get("id") or task_id})
    requirements = CompletionRequirements.from_task(task)
    paths = tuple(sorted(set(paths)))
    if acceptance_receipt is not None and not paths:
        raise ValueError("Imported acceptance requires explicit --paths for task closeout")
    if requirements.coverage == "task" and not paths:
        raise ValueError("Task acceptance requires explicit literal owned paths; select them with --paths")
    prior_acceptance = (claim.get("verification_result") or {}).get("acceptance") or {}
    local = LocalCloseoutOperations()

    def covers(result: AcceptanceResult) -> bool:
        return (requirements.satisfied_by(result.reference.to_dict())
                and (result.reference.coverage != "task" or (result.reference.scope == paths
                    and result.reference.declared_stages == tuple(sorted(requirements.stages)))))

    def validate(receipt: dict[str, Any]) -> AcceptanceResult:
        source = str(receipt.get("source_commit") or "")
        local.require_owned_source(repo, source, paths, task)
        return validate_source_receipt(repo, receipt, sha=source)

    with repo_lock(repo, purpose="capture task completion evidence"):
        head = run_git(repo, ["rev-parse", "--verify", "HEAD^{commit}"])
        if head.returncode or not head.stdout.strip():
            raise ValueError("Task source commit is unavailable")
        sha = head.stdout.strip()
        local.require_owned_source(repo, sha, paths, task)
        result: AcceptanceResult | None = None
        if acceptance_receipt is not None:
            result = replace(validate(acceptance_receipt), reused=True)
            if not covers(result):
                raise ValueError("Imported acceptance does not cover the declared task requirements and owned scope")
        elif prior_acceptance.get("state") == "success":
            try:
                retained = validate(prior_acceptance)
            except (AcceptanceError, ValueError):
                pass
            else:
                if covers(retained):
                    result = replace(retained, reused=True)
        status = run_git(repo, ["--no-optional-locks", "status", "--porcelain=v1", "--untracked-files=all"])
        if status.returncode:
            raise ValueError("Cannot inspect task checkout")
        materialization: Materialization = "isolated" if status.stdout else "actual"
    if result is None:
        result = accept_source(repo, sha=sha, materialization=materialization, scope=paths, task_id=task_id,
                               coverage=requirements.coverage, required_stages=requirements.stages)
    with repo_lock(repo, purpose="attach task completion evidence"):
        current_task = hydrate_completion_task({**claim, "id": task["id"]})
        if CompletionRequirements.from_task(current_task) != requirements:
            raise ValueError("Task completion requirements changed during acceptance; checkpoint preserved")
        local.require_owned_source(repo, result.reference.source_commit, paths, current_task)
        if not covers(result):
            raise ValueError("Acceptance does not cover the declared task requirements and owned scope")
        reference = result.reference.to_dict()
        if not store_owned_acceptance(task_id, project_id, reference,
                expected_worker=str(claim["claimed_by"]), expected_claimed_at=claim["claimed_at"],
                expected_acceptance=prior_acceptance):
            raise ValueError("Task claim or acceptance changed while validating completion; checkpoint preserved")
    return AcceptedTaskWork(result, claim)
