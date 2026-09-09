"""Durable detached rebuild results and explicit backend feature selection."""

import json
import subprocess
from dataclasses import replace
from unittest.mock import Mock

import pytest
from typer.testing import CliRunner

from cli.commands import service
from cli.lib import service_ops


@pytest.fixture
def jobs(tmp_path, monkeypatch):
    monkeypatch.setattr(service_ops, "get_repo_root", lambda: tmp_path)
    monkeypatch.setattr(service_ops, "systemctl", lambda *args: subprocess.CompletedProcess([], 0, "inactive\n", ""))
    monkeypatch.setattr(service_ops, "capture", lambda *args: subprocess.CompletedProcess([], 0, "queued\n", ""))
    return tmp_path / ".dev-tools" / "service-jobs"


def queued_job(jobs):
    assert service_ops.queue_detached("example", False) == 0
    paths = list(jobs.glob("*.json"))
    assert len(paths) == 1
    return paths[0].stem


def test_queue_creates_durable_unique_result(jobs):
    identifier = queued_job(jobs)
    record = json.loads((jobs / f"{identifier}.json").read_text())
    assert record["state"] == "queued"
    assert record["exit_code"] is None
    assert record["command"] == ["st", "service", "rebuild", "example"]


@pytest.mark.parametrize("code,state", [(0, "succeeded"), (7, "failed")])
def test_runner_persists_actual_result_after_unit_collection(jobs, monkeypatch, code, state):
    identifier = queued_job(jobs)
    monkeypatch.setattr(service_ops.subprocess, "run", lambda *args, **kwargs: subprocess.CompletedProcess([], code))
    assert service_ops.run_detached_job(identifier) == code
    result = service_ops.detached_result(identifier)
    assert result["state"] == state
    assert result["exit_code"] == code


def test_missing_unit_without_terminal_result_is_interrupted(jobs):
    identifier = queued_job(jobs)
    result = service_ops.detached_result(identifier)
    assert result["state"] == "interrupted"
    assert result["exit_code"] is None


def test_unavailable_systemd_is_unknown(jobs, monkeypatch):
    identifier = queued_job(jobs)
    monkeypatch.setattr(service_ops, "systemctl", lambda *args: subprocess.CompletedProcess([], 1, "", "bus unavailable"))
    assert service_ops.detached_result(identifier)["state"] == "unknown"


def test_reused_unit_does_not_hide_interrupted_job(jobs, monkeypatch):
    identifier = queued_job(jobs)
    path = jobs / f"{identifier}.json"
    record = json.loads(path.read_text())
    record.update(state="running", invocation_id="old")
    path.write_text(json.dumps(record))
    monkeypatch.setattr(service_ops, "systemctl", lambda *args: subprocess.CompletedProcess([], 0, "ActiveState=active\nInvocationID=new\nLoadState=loaded\n", ""))
    assert service_ops.detached_result(identifier)["state"] == "interrupted"


def test_result_rejects_path_traversal(jobs):
    with pytest.raises(service_ops.ServiceError):
        service_ops.detached_result("../other")


def test_wait_returns_terminal_failure_code(monkeypatch):
    monkeypatch.setattr(service_ops, "detached_result", lambda _: {"job_id": "fixture", "state": "failed", "exit_code": 7})
    result = CliRunner().invoke(service.app, ["wait", "fixture"])
    assert result.exit_code == 7, result.output


def test_wait_timeout_does_not_claim_success(monkeypatch):
    monkeypatch.setattr(service_ops, "detached_result", lambda _: {"job_id": "fixture", "state": "running", "exit_code": None})
    result = CliRunner().invoke(service.app, ["wait", "fixture", "--timeout", "0"])
    assert result.exit_code != 0
    assert "running" in result.output


def test_configured_extras_are_loaded_from_managed_identity(monkeypatch, tmp_path):
    monkeypatch.setattr(service_ops, "get_project_identity", lambda _: {"project": {"id": "example"}, "runtime": {"backend_extras": ["voice"]}})
    monkeypatch.setattr(service_ops, "get_project_identity_root", lambda _: str(tmp_path))
    assert service_ops.load_project("example").backend_extras == ("voice",)


def test_invalid_extra_configuration_is_not_silently_dropped(monkeypatch, tmp_path):
    monkeypatch.setattr(service_ops, "get_project_identity", lambda _: {"runtime": {"backend_extras": "voice"}})
    monkeypatch.setattr(service_ops, "get_project_identity_root", lambda _: str(tmp_path))
    with pytest.raises(service_ops.ServiceError):
        service_ops.load_project("example")


def test_sync_preserves_configured_extras_and_dev(monkeypatch, tmp_path):
    monkeypatch.setattr(service_ops, "get_project_identity", lambda _: {"runtime": {"backend_extras": ["voice", "dev", "voice"]}})
    monkeypatch.setattr(service_ops, "get_project_identity_root", lambda _: str(tmp_path))
    project = replace(service_ops.load_project("example"), backend_dir=tmp_path)
    (tmp_path / "pyproject.toml").write_text('[project.optional-dependencies]\ndev=[]\nvoice=[]\n')
    (tmp_path / "uv.lock").touch()
    run = Mock(return_value=0)
    monkeypatch.setattr(service_ops, "run", run)
    assert service_ops.sync_backend(project) == 0
    assert run.call_args.args[0] == ["uv", "sync", "--locked", "--extra", "dev", "--extra", "voice"]


def test_unknown_configured_extra_fails_before_environment_mutation(monkeypatch, tmp_path):
    monkeypatch.setattr(service_ops, "get_project_identity", lambda _: {"runtime": {"backend_extras": ["typo"]}})
    monkeypatch.setattr(service_ops, "get_project_identity_root", lambda _: str(tmp_path))
    project = replace(service_ops.load_project("example"), backend_dir=tmp_path)
    (tmp_path / "pyproject.toml").write_text('[project.optional-dependencies]\ndev=[]\n')
    (tmp_path / "uv.lock").touch()
    run = Mock()
    monkeypatch.setattr(service_ops, "run", run)
    assert service_ops.sync_backend(project) != 0
    run.assert_not_called()


@pytest.mark.skipif(__import__("os").environ.get("ST_RUN_SERVICE_SYSTEMD_TESTS") != "1", reason="explicit isolated systemd validation")
@pytest.mark.parametrize("code", [0, 7])
def test_real_detached_result_survives_collection(tmp_path, monkeypatch, code):
    import os
    import shutil
    import sys
    import time
    import uuid

    real_st = shutil.which("st")
    assert real_st is not None
    isolated_bin = tmp_path / "bin"
    isolated_bin.mkdir()
    shim = isolated_bin / "st"
    shim.write_text(
        f"#!{sys.executable}\nimport os, sys\n"
        "if sys.argv[1:3] == ['service', 'rebuild']:\n"
        f"    print('isolated rebuild fixture'); sys.exit({code})\n"
        f"os.execv({real_st!r}, [{real_st!r}, *sys.argv[1:]])\n"
    )
    shim.chmod(0o700)
    monkeypatch.setenv("PATH", str(isolated_bin) + os.pathsep + os.environ["PATH"])
    monkeypatch.setattr(service_ops, "get_repo_root", lambda: tmp_path)
    project = "fixture-" + uuid.uuid4().hex[:12]
    assert service_ops.queue_detached(project, False) == 0
    records = list((tmp_path / ".dev-tools" / "service-jobs").glob("*.json"))
    assert len(records) == 1
    identifier = records[0].stem
    deadline = time.monotonic() + 15
    while True:
        result = service_ops.detached_result(identifier)
        if result["state"] not in {"queued", "running"} or time.monotonic() > deadline:
            break
        time.sleep(0.1)
    assert result["state"] == ("succeeded" if code == 0 else "failed"), result
    assert result["exit_code"] == code
    assert records[0].with_suffix(".log").read_text().strip() == "isolated rebuild fixture"
    deadline = time.monotonic() + 5
    while service_ops.service_state(result["unit"]) in {"active", "deactivating"} and time.monotonic() < deadline:
        time.sleep(0.1)
    assert service_ops.service_state(result["unit"]) not in {"active", "deactivating"}
    assert service_ops.detached_result(identifier)["exit_code"] == code


def test_collected_queued_job_cannot_attach_to_reused_unit(jobs, monkeypatch):
    identifier = queued_job(jobs)
    monkeypatch.setattr(service_ops, "systemctl", lambda *args: subprocess.CompletedProcess(
        [], 0, "ActiveState=active\nDescription=Detached rebuild for another job\nLoadState=loaded\n", "",
    ))
    assert service_ops.detached_result(identifier)["state"] == "interrupted"


def test_active_project_rejects_duplicate_queue(jobs, monkeypatch):
    monkeypatch.setattr(service_ops, "systemctl", lambda *args: subprocess.CompletedProcess([], 0, "activating", ""))
    assert service_ops.queue_detached("example", False) == 1
    assert not list(jobs.glob("*.json"))


def test_systemd_submission_failure_is_durable(jobs, monkeypatch):
    monkeypatch.setattr(service_ops, "capture", lambda *args: subprocess.CompletedProcess([], 5, "", "fixture rejection"))
    assert service_ops.queue_detached("example", False) == 5
    identifier = next(jobs.glob("*.json")).stem
    result = service_ops.detached_result(identifier)
    assert result["state"] == "failed"
    assert result["exit_code"] == 5
