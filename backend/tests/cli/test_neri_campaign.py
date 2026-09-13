"""Campaign CLI preserves protocol data through the existing Neri transport."""

import json
from types import SimpleNamespace

import httpx
import pytest
from typer.testing import CliRunner

from cli.commands import neri
from cli.commands.tools import app as tools_app

CAMPAIGN_ID = "11111111-1111-4111-8111-111111111111"
SNAPSHOT_ID = "22222222-2222-4222-8222-222222222222"


@pytest.fixture
def transport(monkeypatch):
    calls = []
    response = SimpleNamespace(status=200, body={"id": CAMPAIGN_ID})

    def handle(request):
        body = json.loads(request.content) if request.content else None
        calls.append((request.method, request.url.path, body))
        return httpx.Response(response.status, json=response.body)

    client = httpx.Client
    monkeypatch.setenv("ST_NERI_API_URL", "https://neri.invalid")
    monkeypatch.setattr(httpx, "Client", lambda **kwargs: client(transport=httpx.MockTransport(handle), **kwargs))
    return calls, response


def test_campaign_reads_use_existing_transport(transport):
    calls, _ = transport
    runner = CliRunner()
    cases = [
        (["list"], "GET", "/api/campaigns", None),
        (["show", CAMPAIGN_ID], "GET", f"/api/campaigns/{CAMPAIGN_ID}", None),
        (["evaluation", CAMPAIGN_ID, SNAPSHOT_ID], "GET", f"/api/campaigns/{CAMPAIGN_ID}/evaluations/{SNAPSHOT_ID}", None),
    ]
    for args, method, path, body in cases:
        result = runner.invoke(neri.app, ["campaign", *args])
        assert result.exit_code == 0, result.output
        assert json.loads(result.output) == {"id": CAMPAIGN_ID}
        assert calls[-1] == (method, path, body)
    assert len(calls) == len(cases)


def test_campaign_json_files_and_stdin_preserve_identity_revision_and_options(transport, tmp_path):
    calls, _ = transport
    runner = CliRunner()
    cases = [
        (["freeze"], "/api/campaigns/freeze", {
            "protocol_version": "1.0", "title": "Compare document summaries",
            "protocol": {"case_refs": ["artifact:document-a"], "literal": "Keep `text` and $(values)."},
        }),
        (["record", CAMPAIGN_ID], f"/api/campaigns/{CAMPAIGN_ID}/records", {
            "id": SNAPSHOT_ID, "expected_revision": 3, "kind": "observation",
            "payload": {"evidence_refs": ["artifact:summary-a"], "score": 0},
        }),
        (["evaluate", CAMPAIGN_ID], f"/api/campaigns/{CAMPAIGN_ID}/evaluate", {
            "request_key": "evaluation-4", "expected_revision": 4, "cutoff_seq": 3,
        }),
    ]
    for args, path, body in cases:
        file = tmp_path / f"{args[0]}.json"
        file.write_text(json.dumps(body))
        for source in [str(file), "-"]:
            result = runner.invoke(neri.app, ["campaign", *args, "--file", source],
                                   input=json.dumps(body) if source == "-" else None)
            assert result.exit_code == 0, result.output
            assert calls[-1] == ("POST", path, body)
    assert len(calls) == 6


def test_campaign_bad_identifiers_and_json_never_reach_transport(transport, tmp_path):
    calls, _ = transport
    runner = CliRunner()
    for args in [["freeze"], ["record", CAMPAIGN_ID], ["evaluate", CAMPAIGN_ID]]:
        assert runner.invoke(neri.app, ["campaign", *args]).exit_code != 0
    for args in [["freeze"], ["record", CAMPAIGN_ID], ["evaluate", CAMPAIGN_ID]]:
        for invalid in ["[]", "null", "{invalid"]:
            assert runner.invoke(neri.app, ["campaign", *args, "--file", "-"], input=invalid).exit_code != 0
        assert runner.invoke(neri.app, ["campaign", *args, "--file", str(tmp_path / "missing.json")]).exit_code != 0
    for args in [
        ["show", "bad-id"], ["record", "bad-id", "--file", "-"], ["evaluate", "bad-id"],
        ["evaluation", "bad-id", SNAPSHOT_ID], ["evaluation", CAMPAIGN_ID, "bad-id"],
    ]:
        assert runner.invoke(neri.app, ["campaign", *args], input="{}").exit_code != 0
    assert not calls


def test_campaign_record_conflict_is_reported_without_revision_refresh_or_retry(transport):
    calls, response = transport
    response.status = 409
    response.body = {"detail": "Campaign revision changed"}
    body = {"expected_revision": 3, "kind": "observation", "payload": {"note": "Retained evidence"}}
    result = CliRunner().invoke(neri.app, ["campaign", "record", CAMPAIGN_ID, "--file", "-"],
                                input=json.dumps(body))
    assert result.exit_code == 1
    assert json.loads(result.output) == {"ok": False, "error": "neri_api_error", "detail": "Campaign revision changed"}
    assert calls == [("POST", f"/api/campaigns/{CAMPAIGN_ID}/records", body)]


def test_campaign_commands_are_discoverable_through_canonical_manifest():
    runner = CliRunner()
    for command in ["freeze", "list", "show", "record", "evaluate", "evaluation"]:
        surface = f"st.neri.campaign.{command}"
        result = runner.invoke(tools_app, ["manifest", "--surface", surface, "--format", "json"])
        assert result.exit_code == 0, result.output
        specs = json.loads(result.output)["tools"]
        assert len(specs) == 1
        assert specs[0]["surface"] == surface
        assert specs[0]["cmd"].startswith(f"st neri campaign {command}")
        assert specs[0]["precautions"]
