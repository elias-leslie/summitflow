"""`st vm` goes through the backend route when this shell has no Proxmox token."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from typer.testing import CliRunner

from cli.commands import vm
from cli.lib import proxmox
from cli.lib.proxmox import ProxmoxError, ProxmoxTokenMissing
from cli.lib.proxmox_remote import RemoteProxmoxClient


class FakeHttp:
    def __init__(self, response=None, error=None):
        self.posted, self.response, self.error = [], response or {"result": None}, error
        self._client = SimpleNamespace(headers={})

    def _global_url(self, path):
        return f"http://api{path}"

    def post(self, url, json=None, params=None):
        self.posted.append((url, json))
        if self.error:
            raise self.error
        return self.response


def _no_token(monkeypatch, tmp_path):
    for name in ("PROXMOX_API_URL", "PROXMOX_TOKEN_ID", "PROXMOX_TOKEN_SECRET", "PROXMOX_NODE", "PROXMOX_CA_BUNDLE"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(proxmox.Path, "home", lambda: tmp_path)
    monkeypatch.setattr(proxmox, "get_compose_env_file", lambda: tmp_path / "missing.env")


def test_missing_token_raises_the_route_signal(monkeypatch, tmp_path):
    _no_token(monkeypatch, tmp_path)
    with pytest.raises(ProxmoxTokenMissing):
        proxmox.load_proxmox_config()


def test_cli_uses_the_route_when_the_token_is_missing(monkeypatch, tmp_path):
    _no_token(monkeypatch, tmp_path)
    http = FakeHttp({"result": [{"vmid": 191, "name": "ns-boundary-lab", "status": "running", "maxmem": 0, "maxdisk": 0}]})
    monkeypatch.setattr("cli.lib.proxmox_remote.STClient", lambda **_: http)
    result = CliRunner().invoke(vm.app, ["list"])
    assert result.exit_code == 0, result.output
    assert "ns-boundary-lab" in result.output
    assert http.posted == [("http://api/vm/op", {"op": "list_vms", "vmid": None, "args": {}})]


def test_cli_keeps_the_direct_path_with_a_token(monkeypatch):
    monkeypatch.setattr(vm, "ProxmoxClient", lambda: "direct")
    assert vm._client() == "direct"


def test_route_error_surfaces_as_a_proxmox_error():
    from cli.client import APIError

    remote = RemoteProxmoxClient(FakeHttp(error=APIError(400, {"error": "http_error", "message": "Proxmox API error 403: Permission check failed"})))
    with pytest.raises(ProxmoxError, match="Permission check failed"):
        remote.stop("140")


def test_remote_start_leaves_the_lab_declaration_to_the_caller(monkeypatch):
    http, declared = FakeHttp(), []
    monkeypatch.setattr("cli.lib.proxmox_remote.declare_if_lab", lambda *a: declared.append(a))
    RemoteProxmoxClient(http).start("191", lab_hours=2, lab_reason="why")
    assert http.posted[0][1] == {"op": "start", "vmid": "191", "args": {}}
    assert declared == [("191", 2, "why")]


def test_remote_clone_returns_server_progress():
    http = FakeHttp({"result": ["COPY ONLY", "done"]})
    assert RemoteProxmoxClient(http).run_clone("9001", "200", "x", clone_only=True) == ["COPY ONLY", "done"]
    assert http.posted[0][1]["args"] == {"template": "9001", "newid": "200", "name": "x", "clone_only": True}


def test_admin_token_env_is_sent_as_a_header_on_route_calls(monkeypatch):
    http = FakeHttp()
    monkeypatch.setattr("cli.lib.proxmox_remote.STClient", lambda **_: http)
    monkeypatch.setenv("PROXMOX_ADMIN_TOKEN", "summitflow@pve!prod-admin=sekrit")
    RemoteProxmoxClient().stop("150")
    assert http._client.headers == {"X-Proxmox-Admin-Token": "summitflow@pve!prod-admin=sekrit"}


def test_admin_token_env_replaces_the_local_token(monkeypatch, tmp_path):
    monkeypatch.setenv("PROXMOX_API_URL", "https://pve")
    monkeypatch.setenv("PROXMOX_NODE", "node")
    monkeypatch.setenv("PROXMOX_TOKEN_ID", "summitflow@pve!lab")
    monkeypatch.setenv("PROXMOX_TOKEN_SECRET", "lab-secret")
    monkeypatch.setenv("PROXMOX_CA_BUNDLE", str(tmp_path / "ca.pem"))
    (tmp_path / "ca.pem").write_text("x")
    monkeypatch.setenv("PROXMOX_ADMIN_TOKEN", "summitflow@pve!prod-admin=a=b")
    config = proxmox.load_proxmox_config()
    assert (config.token_id, config.token_secret) == ("summitflow@pve!prod-admin", "a=b")


def test_malformed_admin_token_is_refused_without_echo(monkeypatch):
    monkeypatch.setenv("PROXMOX_ADMIN_TOKEN", "nosplit-secret")
    with pytest.raises(ProxmoxError) as failure:
        proxmox.load_proxmox_config()
    assert "nosplit-secret" not in str(failure.value)
