"""Native commands exercise real client URLs and JSON through an isolated transport."""
from __future__ import annotations

import functools
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from typer.testing import CliRunner

from cli.commands.service import app
from cli.lib.completion_evidence import load_completion_evidence

API_BASE = "https://summitflow.example.invalid/api"
RECEIPT_ID = "a" * 32
DESCRIPTORS = {
    "deployment": {"receipt_id": RECEIPT_ID, "state": "succeeded", "target_id": "fixture-target"},
    "live_validation": {"checks": [{"id": "fixture-route", "state": "success"}]},
}


@pytest.fixture
def native_http(monkeypatch: pytest.MonkeyPatch) -> tuple[list[httpx.Request], list[httpx.Client], dict[str, Any]]:
    requests: list[httpx.Request] = []
    clients: list[httpx.Client] = []
    reply: dict[str, Any] = {"status": 200, "body": DESCRIPTORS}
    original_client = httpx.Client

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(reply["status"], json=reply["body"])

    def isolated_client(*args: Any, **kwargs: Any) -> httpx.Client:
        kwargs["transport"] = httpx.MockTransport(handler)
        client = original_client(*args, **kwargs)
        clients.append(client)
        return client

    # Keep STClient and BaseHTTPClient intact. Only replace network transport
    # and configuration discovery; the ambient project intentionally differs.
    monkeypatch.setattr(httpx, "Client", isolated_client)
    # Cached like the real one: the SDK's set_project_override calls cache_clear().
    monkeypatch.setattr("cli.config.get_config", functools.cache(lambda: SimpleNamespace(
        api_base=API_BASE, project_id="ambient-project",
    )))
    return requests, clients, reply


def test_observe_posts_canonical_project_url_and_writes_only_receipt_reference(tmp_path: Path, native_http) -> None:
    requests, clients, _reply = native_http
    acceptance = tmp_path / "accepted.json"
    acceptance.write_text("fixture acceptance")
    evidence = tmp_path / "evidence.json"

    result = CliRunner().invoke(app, ["observe", "owner-project", "--task", "task-fixture",
                                    "--acceptance", str(acceptance), "--evidence", str(evidence)])

    assert result.exit_code == 0, result.output
    assert len(requests) == 1
    assert requests[0].method == "POST"
    assert str(requests[0].url) == API_BASE + "/projects/owner-project/tasks/task-fixture/deployment-observations"
    assert json.loads(requests[0].content) == {"acceptance_receipt": str(acceptance.resolve())}
    assert json.loads(evidence.read_text()) == {"native_deployment_receipt": RECEIPT_ID}
    output = next(line for line in result.output.splitlines() if line.startswith("NATIVE_DEPLOYMENT:"))
    assert json.loads(output.removeprefix("NATIVE_DEPLOYMENT:")) == DESCRIPTORS
    assert len(clients) == 1 and clients[0].is_closed


def test_observe_api_rejection_closes_client_and_does_not_write_success(tmp_path: Path, native_http) -> None:
    requests, clients, reply = native_http
    reply.update(status=422, body={"detail": "Fixture acceptance rejected"})
    acceptance = tmp_path / "accepted.json"
    acceptance.write_text("fixture acceptance")
    evidence = tmp_path / "evidence.json"

    result = CliRunner().invoke(app, ["observe", "owner-project", "--task", "task-fixture",
                                    "--acceptance", str(acceptance), "--evidence", str(evidence)])

    assert result.exit_code == 1
    assert "Fixture acceptance rejected" in result.output
    assert "NATIVE_DEPLOYMENT:" not in result.output
    assert not evidence.exists()
    assert len(requests) == 1 and requests[0].method == "POST"
    assert len(clients) == 1 and clients[0].is_closed


def test_native_import_gets_canonical_project_url_and_preserves_server_descriptors(tmp_path: Path, native_http) -> None:
    requests, clients, _reply = native_http
    evidence = tmp_path / "evidence.json"
    evidence.write_text(json.dumps({"native_deployment_receipt": RECEIPT_ID}))

    imported = load_completion_evidence(evidence, project_root=tmp_path, project_id="owner-project")

    assert imported == DESCRIPTORS
    assert len(requests) == 1
    assert requests[0].method == "GET"
    assert str(requests[0].url) == API_BASE + "/projects/owner-project/deployment-observations/" + RECEIPT_ID
    assert requests[0].content == b""
    assert len(clients) == 1 and clients[0].is_closed


def test_native_import_api_rejection_is_clean_and_closes_client(tmp_path: Path, native_http) -> None:
    requests, clients, reply = native_http
    reply.update(status=422, body={"detail": "Unknown fixture receipt"})
    evidence = tmp_path / "evidence.json"
    evidence.write_text(json.dumps({"native_deployment_receipt": RECEIPT_ID}))

    with pytest.raises(ValueError, match=r"Server rejected the native receipt:.*Unknown fixture receipt"):
        load_completion_evidence(evidence, project_root=tmp_path, project_id="owner-project")

    assert len(requests) == 1 and requests[0].method == "GET"
    assert len(clients) == 1 and clients[0].is_closed
