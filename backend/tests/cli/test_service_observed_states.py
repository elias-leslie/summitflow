"""Characterize how st service status observes each managed unit's state."""

from dataclasses import replace
from pathlib import Path

import httpx
import pytest

from app import runtime_deployment
from cli.lib import service_ops


@pytest.fixture
def project(tmp_path: Path) -> service_ops.ProjectServices:
    return service_ops.ProjectServices(
        project_id="example", root=tmp_path, backend_service="backend.service",
        frontend_service="web.socket", default_workers=("worker",), optional_workers=(),
        backend_port=8001, frontend_port=3001, backend_dir=tmp_path / "backend",
        frontend_dir=tmp_path / "frontend", health_endpoint="/health",
    )


class _Client:
    def __init__(self, rows=None, error: Exception | None = None):
        self.rows, self.error, self.calls = rows, error, 0

    def __call__(self, **_kwargs):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return False

    def _global_url(self, path: str) -> str:
        return f"global:{path}"

    def get(self, url: str):
        assert url == "global:/docker/status"
        self.calls += 1
        if self.error:
            raise self.error
        return self.rows


def _local(monkeypatch, states: dict[str, str], *, exists: bool = False, client: _Client | None = None):
    monkeypatch.setattr(service_ops, "service_state", lambda unit: states[unit])
    monkeypatch.setattr(service_ops, "service_exists", lambda _unit: exists)
    client = client or _Client(rows=[])
    monkeypatch.setattr(service_ops, "STClient", client)
    return client


ALL_ACTIVE = {"backend.service": "active", "web.socket": "active", "web.service": "active", "worker": "active"}


def test_units_include_the_paired_activated_service(project, monkeypatch):
    client = _local(monkeypatch, ALL_ACTIVE)
    assert service_ops.observed_service_states(project) == ALL_ACTIVE
    assert client.calls == 0


def test_runtime_user_projects_never_consult_the_runtime_api(project, monkeypatch):
    states = dict.fromkeys(ALL_ACTIVE, "inactive")
    client = _local(monkeypatch, states)
    assert service_ops.observed_service_states(replace(project, runtime_user="agent")) == states
    assert client.calls == 0


def test_installed_or_failed_units_keep_their_local_state(project, monkeypatch):
    states = {**ALL_ACTIVE, "worker": "inactive", "backend.service": "failed"}
    client = _local(monkeypatch, states, exists=True)
    assert service_ops.observed_service_states(project) == states
    assert client.calls == 0


def _row(name, state, status="", health=None, manager="systemd"):
    return {"manager": manager, "name": name, "state": state, "status": status, "health": health}


@pytest.mark.parametrize(("row", "expected"), [
    (_row("worker.service", "running"), "active"),
    (_row("worker.service", "starting"), "activating"),
    (_row("worker.service", "failed"), "failed"),
    (_row("worker.service", "paused"), "unknown"),
    (_row("worker.service", "running", health="unhealthy"), "unhealthy"),
    (_row("worker.service", "running", health="healthy"), "active"),
    (_row("worker.service", "stopped", "systemd inactive (dead)"), "inactive"),
    (_row("worker.service", "stopped", "systemd failed since"), "failed"),
    (_row("worker.service", "stopped", "systemd deactivating"), "deactivating"),
    (_row("worker.service", "stopped", "systemd active"), "unknown"),
    (_row("worker.service", "stopped", "exited 0"), "unknown"),
    (_row("worker.service", "stopped", None), "unknown"),
    (_row("worker.service", None), "unknown"),
    (_row("worker.service", "running", manager="docker"), "unknown"),
    (_row("worker", "running"), "unknown"),
])
def test_missing_units_map_their_runtime_api_row(project, monkeypatch, row, expected):
    _local(monkeypatch, {**ALL_ACTIVE, "worker": "inactive"}, client=_Client(rows=[row]))
    assert service_ops.observed_service_states(project) == {**ALL_ACTIVE, "worker": expected}


def test_ambiguous_runtime_rows_leave_the_unit_unknown(project, monkeypatch):
    rows = [_row("worker.service", "running"), _row("worker.service", "running")]
    _local(monkeypatch, {**ALL_ACTIVE, "worker": "inactive"}, client=_Client(rows=rows))
    assert service_ops.observed_service_states(project)["worker"] == "unknown"


def test_each_missing_unit_reads_its_own_row(project, monkeypatch):
    rows = [_row("backend.service", "running"), _row("web.service", "failed"), _row("other.service", "running")]
    states = {**ALL_ACTIVE, "backend.service": "inactive", "web.service": "activating"}
    _local(monkeypatch, states, client=_Client(rows=rows))
    assert service_ops.observed_service_states(project) == {
        **ALL_ACTIVE, "backend.service": "active", "web.service": "failed"}


@pytest.mark.parametrize("client", [
    _Client(rows={"not": "a list"}),
    _Client(rows=[_row("worker.service", "running"), "not a row"]),
    _Client(error=httpx.ConnectError("down")),
    _Client(error=service_ops.APIError(503, "refused")),
    _Client(error=ValueError("bad json")),
    _Client(error=OSError("socket")),
])
def test_unreadable_runtime_status_leaves_missing_units_unknown(project, monkeypatch, client):
    _local(monkeypatch, {**ALL_ACTIVE, "worker": "inactive"}, client=client)
    assert service_ops.observed_service_states(project) == {**ALL_ACTIVE, "worker": "unknown"}


def test_deployed_projects_read_unit_states_from_the_deployment(project, monkeypatch):
    deployment = object()
    seen = {}

    def unit_states(target, units):
        seen["args"] = (target, units)
        return {"backend.service": {"ActiveState": "active"}, "worker": {"ActiveState": "failed"}}

    monkeypatch.setattr(service_ops.runtime_deployment, "unit_states", unit_states)
    assert service_ops.observed_service_states(replace(project, deployment=deployment)) == {
        "backend.service": "active", "web.socket": "unknown", "web.service": "unknown", "worker": "failed"}
    assert seen["args"] == (deployment, ["backend.service", "web.socket", "web.service", "worker"])


def test_unreachable_deployment_reports_every_unit_unknown(project, monkeypatch):
    def unit_states(_target, _units):
        raise runtime_deployment.DeploymentError("offline")

    monkeypatch.setattr(service_ops.runtime_deployment, "unit_states", unit_states)
    assert service_ops.observed_service_states(replace(project, deployment=object())) == dict.fromkeys(
        ALL_ACTIVE, "unknown")
