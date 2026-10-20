"""The installed owner handler binds identity and emits bounded runtime state."""
from __future__ import annotations

import struct
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from cli.lib import service_owner_runtime as owner


@pytest.fixture
def action_request():
    return {"schema": 1, "request_id": "action_request", "action": "owner.deploy",
            "params": {"project": "example", "sha": "a" * 40, "operation": "deploy"}, "expected_uid": 1000,
            "tool_revision": "revision"}


@pytest.fixture
def installed(monkeypatch):
    config = {"tool_revision": "revision", "projects": {"example": {"units": ["example.service"]}}}
    monkeypatch.setattr(owner, "_identity", lambda _: (1000, config))
    return config


def test_owner_target_identity_comes_from_installed_site_not_request(monkeypatch, action_request):
    monkeypatch.setattr(owner, "_trusted_json", lambda path: (
        {"owner": {"user": "configured-owner"}} if path == owner.SITE else {"tool_revision": "revision"}))
    monkeypatch.setattr(owner.pwd, "getpwnam", lambda name: SimpleNamespace(pw_uid=1000))
    monkeypatch.setattr(owner.os, "getuid", lambda: 1001)
    monkeypatch.setattr(owner.os, "geteuid", lambda: 1001)
    action_request["expected_uid"] = 1001
    with pytest.raises(ValueError, match="configured owner"):
        owner._identity(action_request)


def test_owner_target_requires_actual_owner_session_and_tool(monkeypatch, action_request):
    monkeypatch.setattr(owner, "_trusted_json", lambda path: (
        {"owner": {"user": "configured-owner"}} if path == owner.SITE else {"tool_revision": "revision"}))
    monkeypatch.setattr(owner.pwd, "getpwnam", lambda name: SimpleNamespace(pw_uid=1000))
    monkeypatch.setattr(owner.os, "getuid", lambda: 1000)
    monkeypatch.setattr(owner.os, "geteuid", lambda: 1000)
    monkeypatch.setattr(Path, "stat", lambda _: SimpleNamespace(st_uid=1000))
    monkeypatch.setattr(Path, "is_socket", lambda _: True)
    monkeypatch.setenv("XDG_RUNTIME_DIR", "/run/user/1000")
    monkeypatch.setenv("DBUS_SESSION_BUS_ADDRESS", "unix:path=/run/user/1000/bus")
    bus = Mock()
    bus.__enter__ = Mock(return_value=bus)
    bus.__exit__ = Mock(return_value=False)
    bus.getsockopt.return_value = struct.pack("3i", 1234, 1000, 1000)
    monkeypatch.setattr(owner.socket, "socket", Mock(return_value=bus))
    assert owner._identity(action_request)[0] == 1000
    action_request["tool_revision"] = "caller-tool"
    with pytest.raises(ValueError, match="revision mismatch"):
        owner._identity(action_request)


def test_installed_config_cannot_be_agent_owned(tmp_path):
    config = tmp_path / "config.json"
    config.write_text("{}")
    with pytest.raises(ValueError, match="installed by root"):
        owner._trusted_json(config)


@pytest.mark.parametrize("action", ["owner.status", "owner.service", "owner.command"])
def test_private_handler_only_accepts_deploy_action(installed, action_request, action):
    action_request["action"] = action
    with pytest.raises(ValueError, match="protocol, action or phase"):
        owner.handle("precheck", action_request)


@pytest.mark.parametrize("active", [[], ["example-backend.service", "example-frontend.service"],
                                    ["example-backend.service", "example-worker.service"]])
def test_first_deployment_rollback_restores_existing_runtime(tmp_path, monkeypatch, active):
    project = owner.service_ops.ProjectServices(
        project_id="example", root=tmp_path, backend_service="example-backend.service",
        frontend_service="example-frontend.service", backend_port=8000, frontend_port=3000,
        default_workers=("example-worker.timer",), optional_workers=(), backend_dir=tmp_path, frontend_dir=tmp_path,
        health_endpoint="/health", runtime_user="owner")
    units = tmp_path / "units"
    units.mkdir()
    previous = {name: f"old {name}\n" for name in (project.backend_service, project.frontend_service,
                                                  "example-worker.timer", "example-worker.service")}
    for name in previous:
        (units / name).write_text("failed new release\n")
    state = tmp_path / "state"
    state.mkdir()
    (state / "current").symlink_to("failed-release")
    monkeypatch.setattr(owner, "_pointer", lambda *args: "b" * 32)
    monkeypatch.setattr(owner, "_units_dir", lambda: units)
    monkeypatch.setattr(owner.releases, "_project_state", lambda _: state)
    monkeypatch.setattr(owner.service_ops, "run", lambda _: 0)
    stop = Mock(return_value=0)
    restart = Mock(return_value=0)
    health = Mock(return_value=0)
    monkeypatch.setattr(owner.service_ops, "stop_services", stop)
    monkeypatch.setattr(owner.service_ops, "restart_service", restart)
    monkeypatch.setattr(owner.service_ops, "verify_health", health)
    frozen = {"current": None, "previous": None, "units": previous, "optional": [], "active": active}

    assert owner._restore(project, frozen, "b" * 32) is True
    assert {name: (units / name).read_text() for name in previous} == previous
    assert not (state / "current").is_symlink()
    stop.assert_called_once_with(project)
    assert [call.args[0] for call in restart.call_args_list] == active
    assert health.call_count == {project.backend_service, project.frontend_service}.issubset(active)
