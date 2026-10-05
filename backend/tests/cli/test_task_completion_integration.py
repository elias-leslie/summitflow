"""Normal task completion preserves declared coverage and compact claim evidence."""

from __future__ import annotations

import subprocess
import sys
from copy import deepcopy
from pathlib import Path
from typing import Any
from unittest.mock import Mock

import pytest
from typer import Exit

from cli.commands.done_task import complete_task
from cli.lib.acceptance import accept_revision
from cli.lib.acceptance_coordinator import accept_source, validate_source_receipt


@pytest.fixture
def completion_source(tmp_path: Path, monkeypatch):
    for args in (("init", "-q", "--initial-branch=main"), ("config", "user.name", "Fixture"),
                 ("config", "user.email", "fixture@example.invalid"), ("config", "core.hooksPath", "/dev/null")):
        subprocess.run(["git", *args], cwd=tmp_path, check=True)
    (tmp_path / "owned.py").write_text("value = 1\n")
    (tmp_path / "foreign.txt").write_text("original\n")
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-qm", "task source"], cwd=tmp_path, check=True)
    sha = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=tmp_path, text=True).strip()
    claim: dict[str, Any] = {"id": "owned-task", "project_id": "fixture", "title": "Owned task", "status": "running",
             "claimed_by": "fixture-worker", "claimed_at": "2026-10-05T03:00:00+00:00",
             "verification_result": {"deployment": {"prior": "retained"}}}
    spirit = {"context": {"files_to_modify": ["owned.py"], "completion_requirements": {"acceptance": "task"}}}
    client = Mock()
    client.get_task.side_effect = lambda _: deepcopy(claim)
    client.export_task_data.side_effect = lambda _: {"task": deepcopy(claim)}
    client.get_task_completion_readiness.return_value = {"ready": True}
    monkeypatch.setattr("cli.commands.done_task.get_project_root_path", lambda _: str(tmp_path))
    monkeypatch.setattr("cli.commands.done_task.get_snapshot_info", lambda _: {"project_id": "fixture", "base_branch": "main", "base_commit": sha})
    monkeypatch.setattr("cli.lib.task_claims.current_worker_id", lambda: "fixture-worker")
    monkeypatch.setattr("cli.lib.task_claims.renew_local_owned_claim", lambda *a: deepcopy(claim))
    monkeypatch.setattr("app.storage.task_spirit.get_task_spirit", lambda _: deepcopy(spirit))
    attached = []

    def store(_task, _project, reference, **expected):
        attached.append((deepcopy(reference), expected))
        claim["verification_result"]["acceptance"] = deepcopy(reference)
        return True

    monkeypatch.setattr("app.storage.tasks.closeout.store_owned_acceptance", store)
    monkeypatch.setattr("app.services.task_closeout.get_closeout", lambda _: None)
    requested = Mock(return_value={"request_id": "retained-closeout"})
    monkeypatch.setattr("app.services.task_closeout.request_closeout", requested)
    monkeypatch.setattr("app.services.task_closeout.resume_closeout", lambda *a, **kw: {"action": "completed"})
    monkeypatch.setattr("cli.lib.publish_workflow.publish_git", Mock(side_effect=AssertionError("Local completion must not publish")))
    return tmp_path, sha, claim, spirit, client, attached, requested


def finish(source, **options):
    return complete_task(source[4], "owned-task", strict=True, skip_diff_gate=True,
                         paths=("owned.py",), **options)


def test_normal_completion_attaches_compact_proof_and_carries_exact_claim(completion_source):
    repo, sha, claim, _spirit, _client, attached, requested = completion_source
    proof = validate_source_receipt(repo, accept_revision(repo, sha=sha, execution_basis="isolated", coverage="task", scope=("owned.py",),
                          task_id="proof-task", runner=lambda command, cwd: subprocess.CompletedProcess(command, 0, "RUFF:OK:0", "")))
    (repo / "foreign.txt").write_text("foreign staged work\n")
    subprocess.run(["git", "add", "foreign.txt"], cwd=repo, check=True)
    index = (repo / ".git" / "index").read_bytes()

    assert finish(completion_source, acceptance_receipt=proof.to_dict())["action"] == "completed"

    reference, expected = attached[0]
    assert reference == proof.reference.to_dict()
    assert reference["task_id"] == "proof-task"
    assert not {"checks", "inputs", "plan", "source"}.intersection(reference)
    assert expected == {"expected_worker": "fixture-worker", "expected_claimed_at": claim["claimed_at"], "expected_acceptance": {}}
    assert requested.call_args.kwargs["expected_acceptance"] == reference
    assert requested.call_args.kwargs["expected_verification"] == {"acceptance": reference, "deployment": {"prior": "retained"}, "live_validation": {}}
    assert validate_source_receipt(repo, reference, sha=sha).reference == proof.reference
    assert (repo / ".git" / "index").read_bytes() == index
    assert (repo / "foreign.txt").read_text() == "foreign staged work\n"
    assert finish(completion_source)["action"] == "completed"
    assert attached[1][0] == reference
    assert attached[1][1]["expected_acceptance"] == reference


@pytest.mark.parametrize("coverage", ["task", "full"])
def test_normal_completion_derives_fresh_coverage_from_canonical_plan(completion_source, monkeypatch, coverage):
    _repo, _sha, claim, spirit, _client, attached, _requested = completion_source
    claim["completion_requirements"] = {"acceptance": "full" if coverage == "task" else "task"}
    spirit["context"]["completion_requirements"]["acceptance"] = coverage
    observed = []
    run = subprocess.run

    def gate(command, *args, **kwargs):
        if command[0] == sys.executable and len(command) > 3 and "from cli.main import app; app()" in command[3]:
            observed.append(command[6:])
            return subprocess.CompletedProcess(command, 0, "RUFF:OK:0", "")
        return run(command, *args, **kwargs)

    monkeypatch.setattr(subprocess, "run", gate)
    assert finish(completion_source)["action"] == "completed"
    assert attached[0][0]["coverage"] == coverage
    assert observed == [["--quick", "--changed-only"] if coverage == "task" else ["--check"]]


@pytest.mark.parametrize("requirement", [{"acceptance": "full"}, {"acceptance_stages": ["api-contract"]},
                                        {"acceptance_stages": ["scoped-quality"]}])
def test_imported_task_proof_cannot_omit_declared_evidence(completion_source, requirement):
    repo, sha, _claim, spirit, _client, attached, requested = completion_source
    proof = accept_source(repo, sha=sha, materialization="actual", coverage="task", scope=("owned.py",),
                          runner=lambda command, cwd: subprocess.CompletedProcess(command, 0, "RUFF:OK:0", ""))
    spirit["context"]["completion_requirements"] = requirement
    with pytest.raises(Exit):
        finish(completion_source, acceptance_receipt=proof.reference.to_dict())
    assert attached == []
    requested.assert_not_called()


def test_fresh_task_acceptance_requires_each_declared_stage(completion_source):
    _repo, _sha, _claim, spirit, _client, attached, requested = completion_source
    spirit["context"]["completion_requirements"]["acceptance_stages"] = ["api-contract"]
    with pytest.raises(Exit):
        finish(completion_source)
    assert attached == []
    requested.assert_not_called()


def test_claim_change_cannot_create_a_closeout_request(completion_source, monkeypatch):
    repo, sha, _claim, _spirit, _client, _attached, requested = completion_source
    proof = accept_source(repo, sha=sha, materialization="actual", coverage="task", scope=("owned.py",),
                          runner=lambda command, cwd: subprocess.CompletedProcess(command, 0, "RUFF:OK:0", ""))
    monkeypatch.setattr("app.storage.tasks.closeout.store_owned_acceptance", lambda *a, **kw: False)
    with pytest.raises(Exit):
        finish(completion_source, acceptance_receipt=proof.reference.to_dict())
    requested.assert_not_called()


def test_declared_acceptance_stages_are_evidence_work_even_without_source_paths(completion_source):
    _repo, _sha, _claim, _spirit, client, attached, requested = completion_source
    client.export_task_data.return_value = None
    client.export_task_data.side_effect = lambda _: {"task": {"context": {
        "completion_requirements": {"acceptance": False, "acceptance_stages": ["api-contract"]}}}}
    with pytest.raises(Exit):
        complete_task(client, "owned-task", admin=True)
    assert attached == []
    requested.assert_not_called()


def test_exported_canonical_stage_requirement_cannot_be_waived_by_stale_projection(completion_source, monkeypatch):
    _repo, _sha, claim, _spirit, client, attached, requested = completion_source
    claim["completion_requirements"] = {"acceptance": False}
    client.export_task_data.side_effect = lambda _: {
        "task": {"completion_requirements": {"acceptance": False}},
        "spirit": {"context": {"completion_requirements": {
            "acceptance": False, "acceptance_stages": ["api-contract"]}}}}
    monkeypatch.setattr("cli.commands.done_task._run_smart_prereqs", lambda *a, **kw: None)
    monkeypatch.setattr("cli.commands.done_task._complete_admin", lambda *a, **kw: {"action": "completed"})
    with pytest.raises(Exit):
        complete_task(client, "owned-task", admin=True)
    assert attached == []
    requested.assert_not_called()
