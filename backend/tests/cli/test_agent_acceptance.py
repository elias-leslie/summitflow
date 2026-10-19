from __future__ import annotations

import json
import subprocess
from pathlib import Path
from types import SimpleNamespace
from typing import cast
from unittest.mock import Mock

import pytest
import typer

from app.utils import agent_execution, agent_jobs
from cli.commands import check, check_runner, checkout_job, done_task_acceptance
from cli.lib import acceptance, agent_acceptance


@pytest.mark.parametrize("operation", ["lookup", "validate", "persist", "accept", "isolated"])
def test_acceptance_uses_source_identity_before_inspecting_owner_inputs(tmp_path, monkeypatch, operation):
    monkeypatch.setattr(agent_execution, "source_requires_agent", lambda _repo: True)
    descriptor = {"acceptance_id": "proof", "source_commit": "a" * 40}
    job = Mock(return_value={"receipt": descriptor} if operation == "lookup" else descriptor)
    monkeypatch.setattr(agent_acceptance, "run_installed_agent_job", job)
    repo = tmp_path / "source"
    if operation == "lookup":
        result = acceptance.receipt_for_commit(repo, "a" * 40)
    elif operation == "validate":
        result = acceptance.validate_acceptance_receipt(repo, Path("unreadable-owner-receipt"), sha="a" * 40)
    elif operation == "persist":
        result = acceptance.persist_validated_receipt(repo, {}, sha="a" * 40)
    elif operation == "accept":
        result = acceptance.accept_revision(repo, sha="a" * 40)
    else:
        result = done_task_acceptance.accept_isolated_revision(repo, sha="a" * 40, scope=(), task_id="task")
    assert result == descriptor
    args, kwargs = job.call_args
    assert args[0] == "cli.lib.agent_acceptance"
    assert args[1]["operation"] == operation
    assert kwargs == {"project": repo}


def test_agent_acceptance_transport_error_stays_an_acceptance_failure(tmp_path, monkeypatch):
    monkeypatch.setattr(agent_acceptance, "run_installed_agent_job", Mock(side_effect=OSError("socket closed")))
    with pytest.raises(acceptance.AcceptanceError, match="Agent acceptance is unavailable"):
        agent_acceptance.source_acceptance_job(tmp_path, "lookup", commit="a" * 40)


def test_agent_acceptance_resolves_relative_source_before_changing_cwd(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    job = Mock(return_value={"receipt": None})
    monkeypatch.setattr(agent_acceptance, "run_installed_agent_job", job)
    agent_acceptance.source_acceptance_job(Path("checkout"), "lookup", commit="a" * 40)
    assert job.call_args.args[1]["project"] == str(tmp_path / "checkout")
    assert job.call_args.kwargs["project"] == tmp_path / "checkout"


@pytest.mark.parametrize("args", [["--deep", "--json"], ["pytest", "--", "--help"], ["--quick", "--help"]])
def test_source_check_delegates_before_loading_project_tools(tmp_path, monkeypatch, capsys, args):
    monkeypatch.setattr(check, "_resolve_repo_root", lambda: tmp_path)
    monkeypatch.setattr(agent_execution, "source_requires_agent", lambda _repo: True)
    run = Mock(return_value=subprocess.CompletedProcess([], 7, "check output\n", "check diagnostic\n"))
    monkeypatch.setattr(agent_execution, "run_as_agent", run)
    monkeypatch.setattr(check, "_tool_configs", Mock(side_effect=AssertionError("owner loaded project checks")))
    with pytest.raises(typer.Exit) as result:
        check.check(SimpleNamespace(invoked_subcommand=None, args=args))
    assert result.value.exit_code == 7
    assert run.call_args.args[0] == ["st", "check", *args]
    assert capsys.readouterr() == ("check output\n", "check diagnostic\n")


def test_installed_job_does_not_forward_owner_environment(tmp_path, monkeypatch):
    monkeypatch.setenv("SSH_AUTH_SOCK", "/private/owner-agent")
    run = Mock(return_value=subprocess.CompletedProcess([], 0, '{"ready": true}', ""))
    monkeypatch.setattr(agent_jobs, "run_as_agent", run)
    assert agent_jobs.run_installed_agent_job("job.module", {"x": 1}, project=tmp_path) == {"ready": True}
    assert run.call_args.args[0] == ["st", "checkout-job", "job.module"]
    assert "env" not in run.call_args.kwargs
    assert json.loads(run.call_args.kwargs["input"]) == {"x": 1}


def test_checkout_job_refuses_owner_before_import(monkeypatch):
    monkeypatch.setattr(checkout_job, "_agent_uid", lambda: -1)
    monkeypatch.setattr(checkout_job, "import_module", Mock(side_effect=AssertionError("imported job as owner")))
    with pytest.raises(SystemExit, match="configured agent account"):
        checkout_job.checkout_job(cast(typer.Context, SimpleNamespace(args=["job.module"])))


def test_acceptance_metadata_and_lock_use_agent_git(tmp_path, monkeypatch):
    metadata = tmp_path / ".git"
    metadata.mkdir()
    run = Mock(return_value=subprocess.CompletedProcess([], 0, str(metadata), ""))
    monkeypatch.setattr(acceptance, "run_source_git", run)
    monkeypatch.setattr(acceptance.subprocess, "run", Mock(side_effect=AssertionError("owner source Git")))
    with acceptance.repo_lock(tmp_path, purpose="deployment"):
        assert acceptance.acceptance_artifact_directory(tmp_path) == metadata / "st" / "acceptance"
    assert run.call_count == 2
    assert all(call.kwargs["cwd"] == tmp_path for call in run.call_args_list)


def test_check_root_discovery_uses_agent_git(tmp_path, monkeypatch):
    monkeypatch.setattr(check_runner, "get_project_override", lambda: None)
    run = Mock(return_value=subprocess.CompletedProcess([], 0, str(tmp_path), ""))
    monkeypatch.setattr(check_runner, "run_source_git", run)
    assert check_runner._resolve_repo_root() == tmp_path
    assert run.call_args.args[0] == ["git", "rev-parse", "--show-toplevel"]
