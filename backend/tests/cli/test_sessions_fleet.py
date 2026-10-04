"""New fleet commands preserve existing readers and quiet wait semantics."""

from __future__ import annotations

from unittest.mock import MagicMock

import httpx
import pytest
from st_sdk.fleet import FleetClient
from st_sdk.http import BaseHTTPClient
from typer.testing import CliRunner

from cli.commands import sessions_fleet
from cli.main import app

runner = CliRunner()


def test_wait_defaults_to_300_and_timeout_is_silent(monkeypatch):
    client = MagicMock()
    client.wait.return_value = {"events": [], "cursor": 42}
    monkeypatch.setattr(sessions_fleet, "_client", lambda: client)
    result = runner.invoke(app, ["sessions", "wait", "root-fixture", "--cursor", "42"])
    assert result.exit_code == 0
    assert result.output == ""
    client.wait.assert_called_once_with("root-fixture", cursor=42, timeout=300)


def test_send_retains_instruction_and_reports_capability(monkeypatch):
    client = MagicMock()
    client.send.return_value = {"capability": "unavailable", "delivery": "not-attempted", "retained": True}
    monkeypatch.setattr(sessions_fleet, "_client", lambda: client)
    result = runner.invoke(app, ["sessions", "send", "root-fixture", "Exact short instruction", "--source-key", "revision:1"])
    assert result.exit_code == 0
    assert "not-attempted" in result.output
    client.send.assert_called_once_with("root-fixture", instruction="Exact short instruction", scope={}, source_key="revision:1")


@pytest.mark.parametrize("command", ["show", "close"])
def test_existing_lifecycle_routes_root_handles(monkeypatch, command):
    client = MagicMock()
    getattr(client, command).return_value = {"root": "root-fixture", "status": "closed"}
    monkeypatch.setattr(sessions_fleet, "_client", lambda: client)
    result = runner.invoke(app, ["sessions", command, "root-fixture"])
    assert result.exit_code == 0
    getattr(client, command).assert_called_once_with("root-fixture")


def test_list_fleet_is_explicit_addition(monkeypatch):
    client = MagicMock()
    client.list.return_value = {"roots": []}
    monkeypatch.setattr(sessions_fleet, "_client", lambda: client)
    result = runner.invoke(app, ["sessions", "list", "--fleet", "--project", "neri"])
    assert result.exit_code == 0
    client.list.assert_called_once_with(project_id="neri", limit=20)


def test_public_sdk_append_is_versioned_and_digest_keyed():
    requests = []

    def handle(request):
        requests.append(request)
        return httpx.Response(200, json={"sequence": 1})

    with BaseHTTPClient("http://fixture/api", "fixture", transport=httpx.MockTransport(handle)) as client:
        result = FleetClient(client).append("root-fixture", source_key="neri:run:1:revision:2", event_type="source.changed", attributes={"source_ref": "run:1", "revision": "2"})
    assert result["sequence"] == 1
    assert requests[0].url.path == "/api/fleet/v1/roots/root-fixture/events"
    assert b'"digest"' in requests[0].content


def test_emit_returns_compact_delta_through_public_sdk(monkeypatch):
    client = MagicMock()
    client.append.return_value = {"sequence": 7, "source_key": "source:revision:2"}
    monkeypatch.setattr(sessions_fleet, "_client", lambda: client)
    result = runner.invoke(app, ["sessions", "emit", "root-fixture", "support.delta", "--source-key", "source:revision:2", "--attributes", '{"source_ref":"source:2","kind":"impact-change"}'])
    assert result.exit_code == 0
    client.append.assert_called_once_with("root-fixture", source_key="source:revision:2", event_type="support.delta", attributes={"source_ref": "source:2", "kind": "impact-change"})
    invalid = runner.invoke(app, ["sessions", "emit", "root-fixture", "root.closed", "--source-key", "bad", "--attributes", '{}'])
    assert invalid.exit_code != 0
    assert client.append.call_count == 1
