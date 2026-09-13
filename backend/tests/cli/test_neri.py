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
MUTATION = "44444444-4444-4444-8444-444444444444"


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
    (["reports", "--view", "investigations", "--target", "document?version"], "/api/reports?limit=40&view=investigations&target_id=document%3Fversion"),
    (["reports", "--view", "investigations", "--target-id", "documents", "--limit", "7", "--cursor", "opaque+/=&cursor"], "/api/reports?limit=7&cursor=opaque%2B%2F%3D%26cursor&view=investigations&target_id=documents"),
    (["report", "show", INVESTIGATION], f"/api/runs/{INVESTIGATION}/report"),
    (["report", "revision", INVESTIGATION, RECORD], f"/api/runs/{INVESTIGATION}/reports/{RECORD}"),
    (["report", "review-revision", INVESTIGATION, RECORD], f"/api/runs/{INVESTIGATION}/reviews/{RECORD}"),
    (["capabilities"], "/api/capabilities?compact=true"),
    (["capabilities", "--full"], "/api/capabilities"),
    (["target", "list"], "/api/targets?compact=true"),
    (["target", "show", "document?version"], "/api/targets/document%3Fversion"),
    (["target", "list", "--workspace"], "/api/targets?view=workspace&limit=40"),
    (["target", "list", "--workspace", "--limit", "7", "--cursor", "opaque+/=&cursor", "--search", "source & notes", "--filter", "attention"], "/api/targets?view=workspace&limit=7&cursor=opaque%2B%2F%3D%26cursor&q=source+%26+notes&filter=attention"),
    (["target", "show", "document?version", "--workspace"], "/api/targets/document%3Fversion?view=workspace"),
    (["group", "list", "document?version"], "/api/targets/document%3Fversion/investigations?limit=40"),
    (["group", "list", "documents", "--limit", "7", "--cursor", "opaque+/=&cursor", "--search", "source & notes", "--class-key", "unclassified", "--filter", "awaiting_review", "--include-empty"], "/api/targets/documents/investigations?limit=7&cursor=opaque%2B%2F%3D%26cursor&q=source+%26+notes&class_key=unclassified&filter=awaiting_review&include_empty=true"),
    (["group", "show", "document?version", INVESTIGATION], f"/api/targets/document%3Fversion/investigations/{INVESTIGATION}?attempt_limit=40&report_limit=40"),
    (["group", "show", "documents", INVESTIGATION, "--limit", "7", "--cursor", "opaque+/=&cursor"], f"/api/targets/documents/investigations/{INVESTIGATION}?attempt_limit=7&report_limit=40&attempt_cursor=opaque%2B%2F%3D%26cursor"),
    (["group", "show", "documents", INVESTIGATION, "--attempt-limit", "3", "--attempt-cursor", "a+cursor", "--report-limit", "7", "--report-cursor", "r/cursor"], f"/api/targets/documents/investigations/{INVESTIGATION}?attempt_limit=3&report_limit=7&attempt_cursor=a%2Bcursor&report_cursor=r%2Fcursor"),
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
    (["create"], "/api/investigations", {
        "title": "Source completeness", "objective": "Review supplied source records",
        "target_id": "documents", "group_id": OTHER, "role": "supporting",
    }),
    (["group", "create", "document?version"], "/api/targets/document%3Fversion/investigations", {
        "title": "Source completeness", "objective": "Which source records remain missing?",
        "class_key": "unclassified", "class_label": "Unclassified",
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


GROUP_MUTATIONS = [
    ("classify", "PATCH", "classification", {
        "expected_revision": 2, "class_key": "unclassified", "class_label": "Unclassified",
        "reason": "Review source categorization",
    }),
    ("select-report", "POST", "report-selection", {
        "expected_revision": 3, "report_revision_id": OTHER, "reason": "Select the reviewed record",
    }),
    ("select-report", "POST", "report-selection", {
        "expected_revision": 4, "report_revision_id": None, "reason": "Clear the selected record",
    }),
    ("membership", "POST", "memberships", {
        "run_id": RECORD, "expected_revision": 2, "role": "verification",
        "predecessor_run_id": OTHER, "verifies_report_event_id": OTHER,
        "reason": "Preserve the explicit relationship",
    }),
]


@pytest.mark.parametrize(("command", "method", "suffix", "payload"), GROUP_MUTATIONS)
def test_group_mutations_preserve_separate_mutation_identity_and_exact_fields(
    transport, tmp_path, command, method, suffix, payload,
):
    calls, response = transport
    response.body = {"group_id": INVESTIGATION, "run_id": RECORD, "report_revision_id": OTHER,
                     "selection_revision": 5, "membership_revision_id": RECORD}
    path = f"/api/targets/document%3Fversion/investigations/{INVESTIGATION}/{suffix}"
    args = ["group", command, "document?version", INVESTIGATION]
    body = {**payload, "mutation_id": MUTATION}
    file = tmp_path / "request.json"
    file.write_text(json.dumps(body))
    runner = CliRunner()
    for source in [str(file), "-"]:
        result = runner.invoke(neri.app, [*args, "--file", source], input=json.dumps(body) if source == "-" else None)
        assert result.exit_code == 0, result.output
        assert json.loads(result.output) == {**response.body, "request_id": MUTATION}
    assert calls == [(method, path, body), (method, path, body)]
    result = runner.invoke(neri.app, [*args, "--file", "-", "--id", MUTATION], input=json.dumps(payload))
    assert result.exit_code == 0, result.output
    assert calls[-1] == (method, path, body)
    result = runner.invoke(neri.app, [*args, "--file", "-"], input=json.dumps(payload))
    assert result.exit_code == 0, result.output
    generated_id = json.loads(result.output)["request_id"]
    assert str(UUID(generated_id)) == generated_id
    assert calls[-1] == (method, path, {**payload, "mutation_id": generated_id})
    assert "id" not in calls[-1][2]


@pytest.mark.parametrize(("command", "method", "suffix", "payload"), GROUP_MUTATIONS)
def test_group_mutations_reject_invalid_mutation_identity_before_transport(
    transport, tmp_path, command, method, suffix, payload,
):
    calls, _ = transport
    args = ["group", command, "documents", INVESTIGATION]
    runner = CliRunner()
    for body in ["[]", "null", "{invalid", '{"mutation_id": null}', '{"mutation_id": 123}', '{"mutation_id": "bad-id"}']:
        assert runner.invoke(neri.app, [*args, "--file", "-"], input=body).exit_code != 0
    assert runner.invoke(neri.app, args).exit_code != 0
    assert runner.invoke(neri.app, [*args, "--file", str(tmp_path / "absent")]).exit_code != 0
    result = runner.invoke(neri.app, [*args, "--file", "-", "--id", OTHER],
                           input=json.dumps({**payload, "mutation_id": RECORD}))
    assert result.exit_code != 0
    assert "--id must match the JSON mutation_id" in result.output
    assert not calls


@pytest.mark.parametrize("args", [
    ["investigations", "--limit", "101"], ["investigations", "--limit", "0"],
    ["reports", "--limit", "101"], ["reports", "--limit", "0"],
    ["reports", "--view", "invalid"], ["reports", "--target", "documents"],
    ["target", "list", "--workspace", "--limit", "0"], ["target", "list", "--workspace", "--limit", "101"],
    ["target", "list", "--limit", "7"], ["target", "list", "--cursor", "cursor"],
    ["target", "list", "--search", "source"],
    ["target", "list", "--filter", "attention"], ["target", "list", "--workspace", "--filter", "invalid"],
    ["group", "list", "documents", "--limit", "0"], ["group", "list", "documents", "--limit", "101"],
    ["group", "list", "documents", "--filter", "invalid"],
    ["group", "show", "documents", INVESTIGATION, "--limit", "0"],
    ["group", "show", "documents", INVESTIGATION, "--limit", "101"],
    ["group", "show", "documents", INVESTIGATION, "--report-limit", "0"],
    ["group", "show", "documents", INVESTIGATION, "--report-limit", "101"],
    ["group", "show", "documents", "bad-id"], ["group", "classify", "documents", "bad-id", "--file", "-"],
    ["group", "membership", "documents", "bad-id", "--file", "-"],
    ["group", "select-report", "documents", "bad-id", "--file", "-"],
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
@pytest.mark.parametrize(("args", "identity_field"), [
    (["notes", "add", INVESTIGATION], "id"),
    (["group", "classify", "documents", INVESTIGATION], "mutation_id"),
    (["group", "select-report", "documents", INVESTIGATION], "mutation_id"),
    (["group", "membership", "documents", INVESTIGATION], "mutation_id"),
])
def test_api_errors_keep_mutation_id_without_leaking_input_or_retrying(transport, status, args, identity_field):
    calls, response = transport
    response.status = status
    response.body = {"detail": [{"input": "private-sentinel", "msg": "private-sentinel"}]}
    result = CliRunner().invoke(neri.app, [*args, "--file", "-"],
                                input=json.dumps({"body": "private-sentinel", "context": {"tab": "investigation"}}))
    assert result.exit_code == 1
    assert "private-sentinel" not in result.output
    assert json.loads(result.output)["status"] == status
    assert json.loads(result.output)["request_id"] == calls[0][2][identity_field]
    assert len(calls) == 1


@pytest.mark.parametrize(("args", "identity_field"), [
    (["create"], "id"),
    (["group", "classify", "documents", INVESTIGATION], "mutation_id"),
])
def test_connection_failure_keeps_id_without_logging_url_or_retrying(transport, args, identity_field):
    calls, response = transport
    response.error = httpx.ConnectError("private-sentinel")
    result = CliRunner().invoke(neri.app, [*args, "--file", "-"], input='{"title":"Document review"}')
    assert result.exit_code == 2
    assert "private-sentinel" not in result.output
    assert json.loads(result.output)["request_id"] == calls[0][2][identity_field]
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
            "st.neri.operation", "st.neri.target.list", "st.neri.runtime.stop",
            "st.neri.group.list", "st.neri.group.create", "st.neri.group.show", "st.neri.group.classify",
            "st.neri.group.select-report", "st.neri.group.membership"} <= surfaces
    assert all(spec.get("precautions") for spec in specs)
    commands = {spec["surface"]: spec["cmd"] for spec in specs}
    assert commands["st.neri.evidence.list"] == "st neri evidence list <investigation-id> [--after 0 --limit 40]"
    assert commands["st.neri.reports"] == "st neri reports [--view investigations --target TARGET --limit 40 --cursor TOKEN]"
    assert "--workspace" in commands["st.neri.target.list"]
    assert "--workspace" in commands["st.neri.target.show"]
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
        for identifier_format in ["UUID", "E<number>", "operation:<UUID>"]:
            assert identifier_format in result.output
