"""Status must distinguish a missing caller unit from a stopped runtime unit."""

import json
from contextlib import nullcontext
from dataclasses import replace
from pathlib import Path
from unittest.mock import Mock

import pytest
from typer.testing import CliRunner

from cli.commands import service
from cli.lib import service_ops


@pytest.fixture
def observed(monkeypatch, tmp_path: Path):
    project = service_ops.ProjectServices(
        project_id="example", root=tmp_path, backend_service="backend.service",
        frontend_service="", default_workers=(), optional_workers=("drain.timer",),
        backend_port=8001, frontend_port=0, backend_dir=tmp_path, frontend_dir=tmp_path,
        health_endpoint="/health",
    )
    monkeypatch.setattr(service, "_load", lambda _: project)
    monkeypatch.setattr(service_ops, "service_state", lambda _: "inactive")
    monkeypatch.setattr(service_ops, "service_exists", lambda _: False)
    client = Mock()
    client._global_url.return_value = "/docker/status"
    client.get.return_value = [
        {"name": "backend.service", "manager": "systemd", "state": "running", "status": "Serving HTTP 200"},
        {"name": "drain.timer", "manager": "systemd", "state": "stopped", "status": "systemd inactive",
         "auto_start": False},
    ]
    factory = Mock(return_value=nullcontext(client))
    monkeypatch.setattr(service_ops, "STClient", factory)
    return project, client, factory


def test_missing_caller_units_use_runtime_observation_and_preserve_disabled_timer(observed):
    _, client, _ = observed
    result = CliRunner().invoke(service.app, ["status", "example"])
    assert result.exit_code == 0, result.output
    assert "backend.service:active" in result.output
    assert "drain.timer:inactive(drain.service:unknown)" in result.output
    client.get.assert_called_once_with("/docker/status")


def test_summitflow_paused_timer_is_optional_and_excluded_from_normal_rebuild(monkeypatch):
    root = Path(__file__).resolve().parents[3]
    project = service_ops._project_from_identity(
        json.loads((root / "project.identity.json").read_text()), "summitflow", root)
    timer = "summitflow-codex-managed-drain.timer"
    monkeypatch.setattr(service_ops, "service_state", lambda _: "inactive")
    assert timer in project.optional_workers
    assert timer not in service._selected_workers(
        project, backend=True, include_all_workers=False, requested_workers=())


@pytest.mark.parametrize("state", ["inactive", "failed"])
def test_verified_local_failures_do_not_depend_on_api(observed, monkeypatch, state):
    _, _, factory = observed
    monkeypatch.setattr(service_ops, "service_state", lambda _: state)
    monkeypatch.setattr(service_ops, "service_exists", lambda _: True)
    result = CliRunner().invoke(service.app, ["status", "example"])
    assert result.exit_code == 1, result.output
    assert f"backend.service:{state}" in result.output
    factory.assert_not_called()


@pytest.mark.parametrize("status,state", [("systemd inactive", "inactive"), ("systemd failed", "failed")])
def test_runtime_failure_is_not_hidden_by_missing_local_unit(observed, status, state):
    _, client, _ = observed
    client.get.return_value[0].update(state="stopped", status=status)
    result = CliRunner().invoke(service.app, ["status", "example"])
    assert result.exit_code == 1, result.output
    assert f"backend.service:{state}" in result.output


@pytest.mark.parametrize("rows", [None, {}, [None], [],
    [{"name": "backend.service", "manager": "docker", "state": "running"}],
    [{"name": "other.service", "manager": "systemd", "state": "running"}],
    [{"name": "backend.service", "manager": "systemd", "state": []}],
    [{"name": "backend.service", "manager": "systemd", "state": "stopped"}],
])
def test_unmatched_or_malformed_runtime_is_unknown(observed, rows):
    _, client, _ = observed
    client.get.return_value = rows
    result = CliRunner().invoke(service.app, ["status", "example"])
    assert result.exit_code == 1, result.output
    assert "backend.service:unknown" in result.output


def test_unavailable_runtime_is_unknown(observed):
    _, client, _ = observed
    client.get.side_effect = service_ops.APIError(503, "offline")
    result = CliRunner().invoke(service.app, ["status", "example"])
    assert result.exit_code == 1, result.output
    assert "backend.service:unknown" in result.output


def test_runtime_paired_failure_is_reported_even_when_timer_is_optional(observed):
    _, client, _ = observed
    client.get.return_value.append(
        {"name": "drain.service", "manager": "systemd", "state": "stopped", "status": "systemd failed"})
    result = CliRunner().invoke(service.app, ["status", "example"])
    assert result.exit_code == 1, result.output
    assert "drain.timer:inactive(drain.service:failed)" in result.output


def test_explicit_local_runtime_does_not_fall_back_to_api(observed, monkeypatch):
    project, _, factory = observed
    monkeypatch.setattr(service, "_load", lambda _: replace(project, runtime_user="agent"))
    monkeypatch.setattr(service.service_deploy_client, "delegated_user", lambda _: "")
    result = CliRunner().invoke(service.app, ["status", "example"])
    assert result.exit_code == 1, result.output
    assert "backend.service:inactive" in result.output
    factory.assert_not_called()


@pytest.mark.parametrize("user", ["owner", "svc", "broker", "agent"])
def test_explicit_delegated_status_keeps_existing_route(observed, monkeypatch, user):
    project, _, factory = observed
    monkeypatch.setattr(service, "_load", lambda _: replace(project, runtime_user=user))
    monkeypatch.setattr(service.service_deploy_client, "delegated_user", lambda _: user)
    delegated = Mock(return_value=0)
    monkeypatch.setattr(service, "_deploy_via_socket", delegated)
    assert CliRunner().invoke(service.app, ["status", "example"]).exit_code == 0
    assert delegated.call_args.args[1:] == (user, "status", None)
    factory.assert_not_called()
