"""Lean Neri CLI contracts use the canonical HTTP client and passive records."""

import json
from types import SimpleNamespace
from uuid import UUID

import httpx
import pytest
from typer.testing import CliRunner

from cli.commands import neri
from cli.commands.tools import app as tools_app

INVESTIGATION = "11111111-1111-4111-8111-111111111111"
RECORD = "22222222-2222-4222-8222-222222222222"
OTHER = "33333333-3333-4333-8333-333333333333"


@pytest.fixture
def transport(monkeypatch):
    calls = []
    response = SimpleNamespace(status=200, body={"ok": True}, error=None)

    def handle(request):
        body = json.loads(request.content) if request.content else None
        calls.append((request.method, request.url.raw_path.decode(), body))
        if response.error:
            raise response.error
        return httpx.Response(response.status, json=response.body)

    client = httpx.Client
    monkeypatch.setenv("ST_NERI_API_URL", "https://neri.invalid")
    monkeypatch.setattr(httpx, "Client", lambda **kwargs: client(transport=httpx.MockTransport(handle), **kwargs))
    return calls, response


@pytest.mark.parametrize(("args", "path"), [
    (["investigations"], "/api/investigations?limit=40"),
    (["investigations", "--limit", "7", "--cursor", "opaque+/=&cursor"], "/api/investigations?limit=7&cursor=opaque%2B%2F%3D%26cursor"),
    (["show", INVESTIGATION], f"/api/investigations/{INVESTIGATION}"),
    (["activity", INVESTIGATION, "--after", "9", "--limit", "10"], f"/api/runs/{INVESTIGATION}/activity?after=9&limit=10"),
    (["context", INVESTIGATION, "--after", "7", "--limit", "8"], f"/api/runs/{INVESTIGATION}/context?after=7&limit=8"),
    (["evidence", "list", INVESTIGATION], f"/api/runs/{INVESTIGATION}/evidence?after=0&limit=40"),
    (["evidence", "list", INVESTIGATION, "--after", "42", "--limit", "100"], f"/api/runs/{INVESTIGATION}/evidence?after=42&limit=100"),
    (["evidence", "show", INVESTIGATION, RECORD], f"/api/runs/{INVESTIGATION}/evidence/{RECORD}"),
    (["evidence", "show", INVESTIGATION, "E42"], f"/api/runs/{INVESTIGATION}/evidence/E42"),
    (["evidence", "show", INVESTIGATION, f"operation:{RECORD}"], f"/api/runs/{INVESTIGATION}/evidence/operation:{RECORD}"),
    (["evidence", "show", INVESTIGATION, RECORD.replace("-", "")], f"/api/runs/{INVESTIGATION}/evidence/{RECORD}"),
    (["evidence", "show", INVESTIGATION, f"urn:uuid:{RECORD}"], f"/api/runs/{INVESTIGATION}/evidence/{RECORD}"),
    (["notes", "list", INVESTIGATION], f"/api/runs/{INVESTIGATION}/notes"),
    (["reports"], "/api/reports?limit=40"),
    (["reports", "--limit", "7", "--cursor", "opaque+/=&cursor"], "/api/reports?limit=7&cursor=opaque%2B%2F%3D%26cursor"),
    (["report", "show", INVESTIGATION], f"/api/runs/{INVESTIGATION}/report"),
    (["report", "revision", INVESTIGATION, RECORD], f"/api/runs/{INVESTIGATION}/reports/{RECORD}"),
    (["report", "review-revision", INVESTIGATION, RECORD], f"/api/runs/{INVESTIGATION}/reviews/{RECORD}"),
    (["capabilities"], "/api/capabilities?compact=true"),
    (["capabilities", "--full"], "/api/capabilities"),
    (["target", "list"], "/api/targets?compact=true"),
    (["target", "show", "document?version"], "/api/targets/document%3Fversion"),
    (["runtime", "show"], "/api/runtime-control"),
    (["operation", INVESTIGATION, RECORD], f"/api/workbench/{INVESTIGATION}/operations/{RECORD}"),
])
def test_reads_use_canonical_routes_and_preserve_server_projection(transport, args, path):
    calls, response = transport
    response.body = {"items": [], "has_more": True, "next_cursor": "opaque-token", "through_seq": 42}
    result = CliRunner().invoke(neri.app, args)
    assert result.exit_code == 0, result.output
    assert calls == [("GET", path, None)]
    assert json.loads(result.output) == response.body


@pytest.mark.parametrize(("command", "collection"), [("revision", "reports"), ("review-revision", "reviews")])
def test_exact_revision_not_found_does_not_fall_back_to_report_history(transport, command, collection):
    calls, response = transport
    response.status = 404
    response.body = {"detail": "Revision not found"}
    result = CliRunner().invoke(neri.app, ["report", command, INVESTIGATION, RECORD])
    assert result.exit_code == 1
    assert json.loads(result.output)["status"] == 404
    assert calls == [("GET", f"/api/runs/{INVESTIGATION}/{collection}/{RECORD}", None)]


MUTATIONS = [
    (["create"], "/api/investigations", {
        "title": "Document inventory", "objective": "Review supplied source records",
        "scope_notes": "Retained documents only", "target_id": "documents",
    }),
    (["evidence", "import", INVESTIGATION], f"/api/runs/{INVESTIGATION}/evidence", {
        "kind": "source_excerpt", "title": "Retained excerpt", "summary": "Keep `text` and $(values).",
        "source_url": "https://example.invalid/document", "content_base64": "ZG9jdW1lbnQ=",
        "filename": "document.txt", "media_type": "text/plain",
        "provenance": {"execution_owner": "external", "capture_origin": "external_import",
                       "client": "terminal", "completeness": "partial", "completeness_notes": "Excerpt only"},
    }),
    (["notes", "add", INVESTIGATION], f"/api/runs/{INVESTIGATION}/notes", {
        "body": "Review this source next", "context": {"tab": "evidence", "evidence_id": OTHER},
    }),
    (["report", "save", INVESTIGATION], f"/api/runs/{INVESTIGATION}/report", {
        "status": "incomplete", "title": "Document review", "summary": "More source material needed",
        "findings": [], "uncertainties": ["Source is incomplete"],
    }),
    (["report", "review", INVESTIGATION], f"/api/runs/{INVESTIGATION}/review", {
        "report_revision_id": OTHER, "verdict": "needs_work", "summary": "Obtain complete source",
        "objections": ["Excerpt only"], "verification_attempts": [],
    }),
    (["record-activity", INVESTIGATION], f"/api/runs/{INVESTIGATION}/activity", {
        "kind": "blocker", "title": "Capture adapter is missing",
        "summary": "The current response format is unsupported.",
        "task_ids": ["task-123"], "next_step": "Add and verify a bounded adapter.",
    }),
    (["execute", "operation", INVESTIGATION], f"/api/workbench/{INVESTIGATION}/operations", {
        "kind": "http", "method": "GET", "path": "/rest/products/search?q=juice",
        "purpose": "Read the registered local target response.", "actor": "agent",
        "controller_id": "codex-tui", "controller_revision": 3,
    }),
    (["execute", "sequence", INVESTIGATION], f"/api/workbench/{INVESTIGATION}/sequences", {
        "purpose": "Run two finite read-only target checks.", "actor": "agent",
        "controller_id": "codex-tui", "controller_revision": 3,
        "steps": [{"purpose": "Read status", "method": "GET", "path": "/"}],
    }),
    (["execute", "reset", INVESTIGATION], f"/api/workbench/{INVESTIGATION}/target-reset", {
        "expected_target_manifest_digest": "a" * 64, "actor": "agent",
        "controller_id": "codex-tui", "controller_revision": 3,
    }),
]


@pytest.mark.parametrize(("args", "path", "payload"), MUTATIONS)
def test_mutations_preserve_json_identity_and_data_for_identical_retries(transport, tmp_path, args, path, payload):
    calls, _ = transport
    payload = {**payload, "id": RECORD}
    file = tmp_path / "request.json"
    file.write_text(json.dumps(payload))
    for source in [str(file), "-"]:
        result = CliRunner().invoke(neri.app, [*args, "--file", source], input=json.dumps(payload) if source == "-" else None)
        assert result.exit_code == 0, result.output
        assert json.loads(result.output)["request_id"] == RECORD
    assert calls == [("POST", path, payload), ("POST", path, payload)]


@pytest.mark.parametrize(("args", "path", "payload"), MUTATIONS)
def test_mutations_accept_explicit_id_or_generate_a_printed_uuid(transport, args, path, payload):
    calls, _ = transport
    runner = CliRunner()
    result = runner.invoke(neri.app, [*args, "--file", "-", "--id", RECORD], input=json.dumps(payload))
    assert result.exit_code == 0, result.output
    assert calls[-1] == ("POST", path, {**payload, "id": RECORD})
    result = runner.invoke(neri.app, [*args, "--file", "-"], input=json.dumps(payload))
    assert result.exit_code == 0, result.output
    generated_id = json.loads(result.output)["request_id"]
    assert str(UUID(generated_id)) == generated_id
    assert calls[-1] == ("POST", path, {**payload, "id": generated_id})


@pytest.mark.parametrize(("args", "path", "payload"), MUTATIONS)
def test_mutations_reject_bad_or_conflicting_identity_before_transport(transport, tmp_path, args, path, payload):
    calls, _ = transport
    runner = CliRunner()
    for body in ["[]", "null", "{invalid", '{"id": null}', '{"id": 123}', '{"id": "bad-id"}']:
        result = runner.invoke(neri.app, [*args, "--file", "-"], input=body)
        assert result.exit_code != 0, result.output
    assert runner.invoke(neri.app, args).exit_code != 0
    assert runner.invoke(neri.app, [*args, "--file", str(tmp_path / "absent")]).exit_code != 0
    assert runner.invoke(neri.app, [*args, "--file", "-", "--id", OTHER], input=json.dumps({**payload, "id": RECORD})).exit_code != 0
    assert not calls


@pytest.mark.parametrize("args", [
    ["investigations", "--limit", "101"], ["investigations", "--limit", "0"],
    ["reports", "--limit", "101"], ["reports", "--limit", "0"],
    ["evidence", "list", INVESTIGATION, "--after", "-1"],
    ["evidence", "list", INVESTIGATION, "--limit", "0"], ["evidence", "list", INVESTIGATION, "--limit", "101"],
    ["activity", INVESTIGATION, "--after", "-1"], ["activity", INVESTIGATION, "--limit", "0"],
    ["context", INVESTIGATION, "--limit", "101"], ["context"], ["show", "bad-id"],
    ["evidence", "show", INVESTIGATION, "bad-id"], ["notes", "state", INVESTIGATION, RECORD, "invalid"],
    ["report", "revision", INVESTIGATION], ["report", "revision", INVESTIGATION, "bad-id"],
    ["report", "review-revision", INVESTIGATION], ["report", "review-revision", INVESTIGATION, "bad-id"],
    ["control", INVESTIGATION, "resume"], ["control", INVESTIGATION, "step"],
    ["control", INVESTIGATION, "direct"], ["runtime", "release", "--revision", "0"],
])
def test_invalid_routes_and_options_do_not_send_requests(transport, args):
    calls, _ = transport
    assert CliRunner().invoke(neri.app, args).exit_code != 0
    assert not calls


@pytest.mark.parametrize("command", ["show", "artifact", "download"])
@pytest.mark.parametrize("evidence_id", ["E0", "E01", "E-1", "e1", "E1/extra", "E1?extra", "E1#extra", "operation:bad-id"])
def test_invalid_evidence_identifier_does_not_send_requests(transport, tmp_path, command, evidence_id):
    calls, _ = transport
    args = ["evidence", command, INVESTIGATION, evidence_id]
    if command == "download":
        args.extend(["--output", str(tmp_path / "artifact.bin")])
    result = CliRunner().invoke(neri.app, args)
    assert result.exit_code != 0
    assert "Evidence ID must be" in result.output
    assert not calls


@pytest.mark.parametrize("state", ["acknowledged", "resolved"])
def test_note_state_keeps_a_separate_mutation_identity(transport, state):
    calls, _ = transport
    result = CliRunner().invoke(neri.app, ["notes", "state", INVESTIGATION, RECORD, state, "--id", OTHER])
    assert result.exit_code == 0, result.output
    assert calls == [("POST", f"/api/runs/{INVESTIGATION}/notes/{RECORD}/state", {"id": OTHER, "state": state})]
    assert json.loads(result.output)["request_id"] == OTHER


@pytest.mark.parametrize(("args", "method", "path", "payload"), [
    (["control", INVESTIGATION, "pause"], "POST", f"/api/runs/{INVESTIGATION}/control", {"action": "pause", "message": ""}),
    (["control", INVESTIGATION, "stop"], "POST", f"/api/runs/{INVESTIGATION}/control", {"action": "stop", "message": ""}),
    (["runtime", "stop"], "PUT", "/api/runtime-control", {"stopped": True, "expected_revision": 1}),
    (["runtime", "release", "--revision", "7"], "PUT", "/api/runtime-control", {"stopped": False, "expected_revision": 7}),
])
def test_contextual_controls_are_single_requests(transport, args, method, path, payload):
    calls, _ = transport
    result = CliRunner().invoke(neri.app, args)
    assert result.exit_code == 0, result.output
    assert calls == [(method, path, payload)]


@pytest.mark.parametrize(("args", "path", "method", "payload"), [
    (["target", "register"], "/api/targets", "POST", {"id": "documents", "version": "1"}),
    (["target", "status", "documents"], "/api/targets/documents/status", "PUT", {
        "manifest_digest": "abc", "expected_status": "active", "status": "inactive", "reason": "Archive review complete",
    }),
])
def test_target_metadata_preserves_existing_contract(transport, args, path, method, payload):
    calls, _ = transport
    result = CliRunner().invoke(neri.app, [*args, "--file", "-"], input=json.dumps(payload))
    assert result.exit_code == 0, result.output
    assert calls == [(method, path, payload)]


@pytest.mark.parametrize("status", [409, 422, 500])
def test_api_errors_keep_mutation_id_without_leaking_input_or_retrying(transport, status):
    calls, response = transport
    response.status = status
    response.body = {"detail": [{"input": "private-sentinel", "msg": "private-sentinel"}]}
    result = CliRunner().invoke(neri.app, ["notes", "add", INVESTIGATION, "--file", "-"],
                                input=json.dumps({"body": "private-sentinel", "context": {"tab": "investigation"}}))
    assert result.exit_code == 1
    assert "private-sentinel" not in result.output
    assert json.loads(result.output)["status"] == status
    assert json.loads(result.output)["request_id"] == calls[0][2]["id"]
    assert len(calls) == 1


def test_connection_failure_keeps_id_without_logging_url_or_retrying(transport):
    calls, response = transport
    response.error = httpx.ConnectError("private-sentinel")
    result = CliRunner().invoke(neri.app, ["create", "--file", "-"], input='{"title":"Document review"}')
    assert result.exit_code == 2
    assert "private-sentinel" not in result.output
    assert json.loads(result.output)["request_id"] == calls[0][2]["id"]
    assert len(calls) == 1


def test_empty_mutation_response_still_prints_its_identity(transport):
    calls, response = transport
    response.status = 204
    response.body = None
    result = CliRunner().invoke(neri.app, ["create", "--file", "-", "--id", RECORD], input='{"title":"Document review"}')
    assert result.exit_code == 0, result.output
    assert json.loads(result.output) == {"result": None, "request_id": RECORD}
    assert len(calls) == 1


def test_lean_surface_is_discoverable_and_retired_groups_are_gone():
    runner = CliRunner()
    result = runner.invoke(tools_app, ["manifest", "--task", "neri", "--format", "json"])
    assert result.exit_code == 0, result.output
    specs = [spec for spec in json.loads(result.output)["tools"] if spec["surface"].startswith("st.neri.")]
    surfaces = {spec["surface"] for spec in specs}
    assert {"st.neri.investigations", "st.neri.create", "st.neri.activity", "st.neri.context",
            "st.neri.activity.record", "st.neri.execute.operation", "st.neri.execute.sequence",
            "st.neri.execute.reset",
            "st.neri.evidence.import", "st.neri.evidence.artifact", "st.neri.notes.add",
            "st.neri.report.save", "st.neri.report.review", "st.neri.report.download",
            "st.neri.report.revision", "st.neri.report.review-revision",
            "st.neri.operation", "st.neri.target.list", "st.neri.runtime.stop"} <= surfaces
    assert all(spec.get("precautions") for spec in specs)
    commands = {spec["surface"]: spec["cmd"] for spec in specs}
    assert commands["st.neri.evidence.list"] == "st neri evidence list <investigation-id> [--after 0 --limit 40]"
    assert commands["st.neri.reports"] == "st neri reports [--limit 40 --cursor TOKEN]"
    retired = ["labs", "training", "budget", "usage", "campaign", "technique", "kernel", "evolution",
               "grant", "controller", "assignment", "submit", "workbench", "start", "watch", "runs",
               "brief", "hypothesis", "gap", "help"]
    for group in retired:
        assert not any(surface == f"st.neri.{group}" or surface.startswith(f"st.neri.{group}.") for surface in surfaces)
        assert runner.invoke(neri.app, [group, "--help"]).exit_code != 0
    for command in ["revision", "review-revision"]:
        result = runner.invoke(neri.app, ["report", command, "--help"])
        assert result.exit_code == 0, result.output
        assert "REVISION_ID" in result.output
        assert "without loading report history" in result.output
    for command in ["show", "artifact", "download"]:
        result = runner.invoke(neri.app, ["evidence", command, "--help"])
        assert result.exit_code == 0, result.output
        assert "UUID, E<number>, or operation:<UUID>" in result.output
