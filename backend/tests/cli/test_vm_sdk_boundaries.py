"""Lab VM clients preserve programming failures through the real ST SDK stack."""

from pathlib import Path
from urllib.error import URLError

import httpx
import pytest
from st_sdk import config as sdk_config
from st_sdk.http import BaseHTTPClient

from cli.client import STClient
from cli.lib.proxmox import ProxmoxError
from cli.lib.proxmox_remote import RemoteProxmoxClient


@pytest.fixture()
def sdk_path(monkeypatch, tmp_path):
    """Keep SDK construction/configuration/response parsing intact; isolate IO only."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sdk_config, "_runtime_config", None)
    monkeypatch.setattr(sdk_config, "_project_override", None)
    monkeypatch.setattr(sdk_config.time, "sleep", lambda _: None)
    monkeypatch.setenv("ST_API_BASE", "https://sdk.fixture.invalid/api")
    monkeypatch.setenv("ST_PROJECT_ID", "fixture")
    monkeypatch.delenv("PROXMOX_ADMIN_TOKEN", raising=False)
    owner, agent = tmp_path / "owner-token", tmp_path / "agent-token"
    agent.write_text("agent-fixture")
    monkeypatch.setenv("SUMMITFLOW_OWNER_TOKEN_FILE", str(owner))
    monkeypatch.setenv("SUMMITFLOW_AGENT_TOKEN_FILE", str(agent))
    clients, seen = [], []
    reply = {"response": httpx.Response(200, json={"result": None})}
    original_client = httpx.Client

    def handler(request):
        seen.append(request)
        response = reply["response"]
        if isinstance(response, Exception):
            raise response
        return response

    def isolated_client(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        client = original_client(*args, **kwargs)
        clients.append(client)
        return client

    monkeypatch.setattr(httpx, "Client", isolated_client)
    monkeypatch.setattr(sdk_config, "_get", lambda _url: (200, b"[]"))
    try:
        yield reply, seen, owner
    finally:
        for client in clients:
            client.close()


@pytest.mark.parametrize("error_type", [TypeError, AttributeError, ValueError])
def test_real_sdk_error_response_programming_failures_surface(sdk_path, error_type):
    reply, seen, _ = sdk_path
    error = error_type("synthetic programming defect")

    class BrokenResponse(httpx.Response):
        def json(self, **_):
            raise error

    reply["response"] = BrokenResponse(503, text="fixture response")
    remote = RemoteProxmoxClient.for_lab()
    assert isinstance(remote._http, STClient) and isinstance(remote._http, BaseHTTPClient)
    with pytest.raises(error_type) as exc:
        remote.observe(["120"], "local-lvm")
    assert exc.value is error and len(seen) == 1


@pytest.mark.parametrize("error_type", [TypeError, AttributeError, ValueError])
def test_real_sdk_optional_detection_programming_failures_surface(sdk_path, monkeypatch, error_type):
    monkeypatch.delenv("ST_PROJECT_ID")
    error = error_type("synthetic programming defect")
    calls = []

    def broken_get(*_, **__):
        calls.append(True)
        raise error

    monkeypatch.setattr(sdk_config, "_get", broken_get)
    with pytest.raises(error_type) as exc:
        RemoteProxmoxClient.for_lab()
    assert exc.value is error and calls == [True]


@pytest.mark.parametrize("error_type", [TypeError, AttributeError, ValueError])
def test_real_sdk_token_read_programming_failures_surface(sdk_path, monkeypatch, error_type):
    _, _, owner = sdk_path
    error = error_type("synthetic programming defect")
    original_read = Path.read_text

    def broken_read(path, *args, **kwargs):
        if path == owner:
            raise error
        return original_read(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", broken_read)
    with pytest.raises(error_type) as exc:
        RemoteProxmoxClient.for_lab()
    assert exc.value is error


@pytest.mark.parametrize("response", [httpx.Response(503, text="private-config"), httpx.Response(503, content=b"\xff"),
    httpx.Response(200, text="private-config"), httpx.ConnectError("private-config")])
def test_real_sdk_external_response_failures_remain_redacted(sdk_path, response):
    reply, _, _ = sdk_path
    reply["response"] = response
    with pytest.raises(ProxmoxError) as exc:
        RemoteProxmoxClient.for_lab().observe(["120"], "local-lvm")
    assert "private" not in str(exc.value) and len(str(exc.value)) < 180 and exc.value.__suppress_context__


@pytest.mark.parametrize("error", [URLError("private-config"), TimeoutError("private-config"),
    sdk_config._InvalidURL("private-config"), OSError("private-config")])
def test_real_sdk_optional_detection_external_failures_are_bounded(sdk_path, monkeypatch, caplog, error):
    monkeypatch.delenv("ST_PROJECT_ID")

    def unavailable(*_, **__):
        raise error

    monkeypatch.setattr(sdk_config, "_get", unavailable)
    remote = RemoteProxmoxClient.for_lab()
    assert isinstance(remote._http, STClient) and remote._http.project_id == ""
    assert "private" not in caplog.text


@pytest.mark.parametrize("body", [b"private-config", b"\xff"])
def test_real_sdk_optional_detection_decode_failures_remain_redacted(sdk_path, monkeypatch, body):
    monkeypatch.delenv("ST_PROJECT_ID")
    monkeypatch.setattr(sdk_config, "_get", lambda _url: (200, body))
    with pytest.raises(ProxmoxError) as exc:
        RemoteProxmoxClient.for_lab()
    assert "private" not in str(exc.value) and exc.value.__suppress_context__


@pytest.mark.parametrize("mode", ["invalid_utf8", "missing", "empty"])
def test_real_sdk_malformed_owner_token_retains_agent_fallback(sdk_path, mode):
    _, _, owner = sdk_path
    if mode == "invalid_utf8":
        owner.write_bytes(b"\xff")
    elif mode == "empty":
        owner.write_text("\n")
    remote = RemoteProxmoxClient.for_lab()
    assert remote._http._client.headers["X-SummitFlow-Agent-Token"] == "agent-fixture"
    assert "X-SummitFlow-Owner-Token" not in remote._http._client.headers
