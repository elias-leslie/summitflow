"""Thin terminal client for Neri's saved investigations and evidence API."""
from __future__ import annotations

import json
import re
import sys
from contextlib import suppress
from enum import StrEnum
from pathlib import Path
from typing import Annotated, Any
from urllib.parse import quote, urlencode, urljoin, urlsplit
from uuid import UUID, uuid4

import httpx
import typer

from .._client_base import APIError
from .._project_client import ProjectApi, ProjectApiClient, ProjectApiConnectError, resolve_api_url
from ..lib.usage import usage
from ..output import output_json

app = typer.Typer(help="Read and maintain Neri investigations, evidence, notes and reports")
evidence_app = typer.Typer(help="Import evidence and inspect retained artifacts")
notes_app = typer.Typer(help="Save contextual notes and direction")
report_app = typer.Typer(help="Read exact report and review revisions, save reports and download drafts")
executor_app = typer.Typer(help="Submit explicit typed actions to a registered local target")
target_app = typer.Typer(help="Inspect and maintain registered target metadata")
runtime_app = typer.Typer(help="Inspect or operate Neri's emergency admission stop")
app.add_typer(evidence_app, name="evidence")
app.add_typer(notes_app, name="notes")
app.add_typer(report_app, name="report")
app.add_typer(executor_app, name="execute")
app.add_typer(target_app, name="target")
app.add_typer(runtime_app, name="runtime")
NERI_API = ProjectApi(project_id="neri", env_var="ST_NERI_API_URL", default_url="http://localhost:8017")


class Action(StrEnum):
    pause = "pause"
    stop = "stop"


class NoteState(StrEnum):
    acknowledged = "acknowledged"
    resolved = "resolved"


def evidence_identifier(value: str) -> str:
    """Accept retained UUIDs, event labels and operation receipt identities."""
    if re.fullmatch(r"E[1-9][0-9]*", value):
        return value
    prefix = "operation:" if value.startswith("operation:") else ""
    try:
        return prefix + str(UUID(value.removeprefix(prefix)))
    except ValueError:
        raise typer.BadParameter("Evidence ID must be a UUID, E<number> (positive), or operation:<UUID>") from None


EvidenceId = Annotated[str, typer.Argument(parser=evidence_identifier, help="UUID, E<number>, or operation:<UUID>")]


def request(path: str, body: dict | None = None, *, method: str | None = None, emit: bool = True) -> Any:
    """Use the shared project transport once; never echo failed input or credentials."""
    identity = {}
    if body and "id" in body:
        # Target manifest IDs are not mutation UUIDs.
        with suppress(AttributeError, TypeError, ValueError):
            identity["request_id"] = str(UUID(body["id"]))
    resolved = resolve_api_url(NERI_API)
    try:
        with ProjectApiClient(resolved.url) as client:
            if method == "PUT":
                result = client.put(path, json_body=body)
            else:
                result = client.get(path) if body is None else client.post(path, json_body=body)
        if emit:
            payload = result
            if identity:
                payload = {**result, **identity} if isinstance(result, dict) else {"result": result, **identity}
            output_json(payload)
        return result
    except ProjectApiConnectError:
        output_json({"ok": False, "error": "neri_unreachable", **identity,
                     "hint": "Check st service status neri or ST_NERI_API_URL; reuse the request ID for an identical retry"})
        raise typer.Exit(2) from None
    except APIError as exc:
        # Validation errors can contain raw evidence input, including credentials.
        output_json({"ok": False, "error": "neri_api_error", "status": exc.status_code, **identity,
                     "hint": "Check the API schema and current record; reuse the request ID only for identical content"})
        raise typer.Exit(1) from None


def read_object(path: Path, *, request_id: UUID | None = None, identified: bool = False) -> dict:
    """Read literal JSON from a file/stdin and retain or allocate its mutation UUID."""
    try:
        value = json.loads(sys.stdin.read() if str(path) == "-" else path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise typer.BadParameter(f"Could not read JSON object: {type(exc).__name__}") from None
    if not isinstance(value, dict):
        raise typer.BadParameter("The JSON document must be an object")
    if identified:
        if "id" in value:
            try:
                supplied_id = UUID(value["id"])
            except (AttributeError, TypeError, ValueError):
                raise typer.BadParameter("JSON id must be a UUID") from None
            if request_id is not None and supplied_id != request_id:
                raise typer.BadParameter("--id must match the JSON id")
            request_id = supplied_id
        value["id"] = str(request_id or uuid4())
    return value


def download_file(path: str, output: Path) -> None:
    """Download from Neri to an explicitly named new file; redirects are not followed."""
    base_url = resolve_api_url(NERI_API).url.rstrip("/") + "/"
    url = urljoin(base_url, path)
    base, destination = urlsplit(base_url), urlsplit(url)
    if (destination.scheme, destination.netloc) != (base.scheme, base.netloc) or destination.fragment:
        raise typer.BadParameter("Download URL must belong to the configured Neri API")
    if output.exists():
        raise typer.BadParameter("Output file already exists; choose a new path")
    created = False
    try:
        with httpx.Client(timeout=30.0, follow_redirects=False) as client, client.stream("GET", url) as response:
            response.raise_for_status()
            with output.open("xb") as artifact:
                created = True
                for chunk in response.iter_bytes():
                    artifact.write(chunk)
        output_json({"ok": True, "path": str(output), "bytes": output.stat().st_size})
    except (httpx.HTTPError, OSError) as exc:
        if created:
            output.unlink(missing_ok=True)
        output_json({"ok": False, "error": "neri_download_failed", "reason": type(exc).__name__})
        raise typer.Exit(2) from None


@app.command()
@usage(surface="st.neri.investigations", cmd="st neri investigations [--limit 40 --cursor TOKEN]", when="list saved Neri investigations", precautions=("read-only; next_cursor resumes the saved listing",), task_types=("neri",))
def investigations(limit: Annotated[int, typer.Option(min=1, max=100)] = 40, cursor: str | None = None) -> None:
    params: dict[str, str | int] = {"limit": limit}
    if cursor is not None:
        params["cursor"] = cursor
    request(f"/api/investigations?{urlencode(params)}")


@app.command()
@usage(surface="st.neri.create", cmd="st neri create --file investigation.json [--id UUID]", when="save an investigation title, objective and scope", precautions=("passive creation; JSON id or --id is retained, otherwise generated and printed; reuse only for identical content",), task_types=("neri",))
def create(file: Annotated[Path, typer.Option()], request_id: Annotated[UUID | None, typer.Option("--id")] = None) -> None:
    """Create a saved investigation. --file - reads JSON from stdin."""
    request("/api/investigations", read_object(file, request_id=request_id, identified=True))


@app.command()
@usage(surface="st.neri.show", cmd="st neri show <investigation-id>", when="inspect a saved investigation", precautions=("read-only; saved state does not imply external terminal execution was observed",), task_types=("neri",))
def show(investigation_id: UUID) -> None:
    request(f"/api/investigations/{investigation_id}")


@app.command()
@usage(surface="st.neri.activity", cmd="st neri activity <investigation-id> [--after 0 --limit 40]", when="read a page of retained investigation activity", precautions=("read-only; resume using the returned event sequence",), task_types=("neri",))
def activity(investigation_id: UUID, after: Annotated[int, typer.Option(min=0)] = 0,
             limit: Annotated[int, typer.Option(min=1, max=100)] = 40) -> None:
    request(f"/api/runs/{investigation_id}/activity?{urlencode({'after': after, 'limit': limit})}")


@app.command("record-activity")
@usage(surface="st.neri.activity.record", cmd="st neri record-activity <investigation-id> --file activity.json [--id UUID]", when="record a public objective, hypothesis, decision, progress update, blocker or follow-up", precautions=("passive record only; cite exact evidence and SummitFlow task IDs; private chain-of-thought does not belong here; UUID is retained or generated",), task_types=("neri",))
def record_activity(investigation_id: UUID, file: Annotated[Path, typer.Option()],
                    request_id: Annotated[UUID | None, typer.Option("--id")] = None) -> None:
    request(f"/api/runs/{investigation_id}/activity", read_object(file, request_id=request_id, identified=True))


@app.command()
@usage(surface="st.neri.context", cmd="st neri context <investigation-id> [--after 0 --limit 40]", when="load compact local investigation state and evidence references", precautions=("read-only local projection; retrieval is not proof of model consumption",), task_types=("neri",))
def context(investigation_id: UUID, after: Annotated[int, typer.Option(min=0)] = 0,
            limit: Annotated[int, typer.Option(min=1, max=100)] = 40) -> None:
    request(f"/api/runs/{investigation_id}/context?{urlencode({'after': after, 'limit': limit})}")


@app.command()
@usage(surface="st.neri.capabilities", cmd="st neri capabilities [--full]", when="discover Neri API payload contracts", precautions=("read-only; compact output omits schemas and --full returns every payload schema",), task_types=("neri",))
def capabilities(full: bool = False) -> None:
    request("/api/capabilities" if full else "/api/capabilities?compact=true")


@evidence_app.command("list")
@usage(surface="st.neri.evidence.list", cmd="st neri evidence list <investigation-id> [--after 0 --limit 40]", when="list a page of retained evidence references", precautions=("read-only; resume with through_seq while has_more; preserve provenance and completeness",), task_types=("neri",))
def evidence_list(investigation_id: UUID, after: Annotated[int, typer.Option(min=0)] = 0,
                  limit: Annotated[int, typer.Option(min=1, max=100)] = 40) -> None:
    request(f"/api/runs/{investigation_id}/evidence?{urlencode({'after': after, 'limit': limit})}")


@evidence_app.command("show")
@usage(surface="st.neri.evidence.show", cmd="st neri evidence show <investigation-id> <evidence-id>", when="inspect retained evidence detail", precautions=("read-only; ID accepts UUID, E<number>, or operation:<UUID>; imported evidence is not automatically independently verified",), task_types=("neri",))
def evidence_show(investigation_id: UUID, evidence_id: EvidenceId) -> None:
    request(f"/api/runs/{investigation_id}/evidence/{evidence_id}")


@evidence_app.command("import")
@usage(surface="st.neri.evidence.import", cmd="st neri evidence import <investigation-id> --file evidence.json [--id UUID]", when="import an actual external capture with provenance", precautions=("JSON object or stdin; preserve provenance and completeness; UUID is retained or generated and printed",), task_types=("neri",))
def evidence_import(investigation_id: UUID, file: Annotated[Path, typer.Option()],
                    request_id: Annotated[UUID | None, typer.Option("--id")] = None) -> None:
    request(f"/api/runs/{investigation_id}/evidence", read_object(file, request_id=request_id, identified=True))


@evidence_app.command("artifact")
@usage(surface="st.neri.evidence.artifact", cmd="st neri evidence artifact <investigation-id> <evidence-id>", when="inspect artifact metadata and its download URL", precautions=("read-only; ID accepts UUID, E<number>, or operation:<UUID>; does not print artifact bytes",), task_types=("neri",))
def evidence_artifact(investigation_id: UUID, evidence_id: EvidenceId) -> None:
    evidence = request(f"/api/runs/{investigation_id}/evidence/{evidence_id}", emit=False)
    output_json({"evidence_id": str(evidence_id), "artifact": evidence.get("artifact")})


@evidence_app.command("download")
@usage(surface="st.neri.evidence.download", cmd="st neri evidence download <investigation-id> <evidence-id> --output PATH", when="save retained artifact bytes to a new local file", precautions=("ID accepts UUID, E<number>, or operation:<UUID>; does not overwrite files; download stays on the configured Neri API",), task_types=("neri",))
def evidence_download(investigation_id: UUID, evidence_id: EvidenceId, output: Annotated[Path, typer.Option()]) -> None:
    evidence = request(f"/api/runs/{investigation_id}/evidence/{evidence_id}", emit=False)
    artifact = evidence.get("artifact") or {}
    path = artifact.get("download_url")
    if not isinstance(path, str) or not path:
        raise typer.BadParameter("This evidence has no downloadable artifact")
    download_file(path, output)


@notes_app.command("list")
@usage(surface="st.neri.notes.list", cmd="st neri notes list <investigation-id>", when="read saved investigation notes and direction", precautions=("read-only; notes retain their context and state",), task_types=("neri",))
def notes_list(investigation_id: UUID) -> None:
    request(f"/api/runs/{investigation_id}/notes")


@notes_app.command("add")
@usage(surface="st.neri.notes.add", cmd="st neri notes add <investigation-id> --file note.json [--id UUID]", when="save direction or a note linked to investigation activity, evidence or report", precautions=("JSON object or stdin; UUID is retained or generated and printed; saving direction does not run an agent",), task_types=("neri",))
def notes_add(investigation_id: UUID, file: Annotated[Path, typer.Option()],
              request_id: Annotated[UUID | None, typer.Option("--id")] = None) -> None:
    request(f"/api/runs/{investigation_id}/notes", read_object(file, request_id=request_id, identified=True))


@notes_app.command("state")
@usage(surface="st.neri.notes.state", cmd="st neri notes state <investigation-id> <note-id> acknowledged|resolved [--id UUID]", when="acknowledge or resolve a saved note", precautions=("state mutation UUID is retained or generated and printed; no automatic retry",), task_types=("neri",))
def notes_state(investigation_id: UUID, note_id: UUID, state: NoteState,
                request_id: Annotated[UUID | None, typer.Option("--id")] = None) -> None:
    request(f"/api/runs/{investigation_id}/notes/{note_id}/state", {"id": str(request_id or uuid4()), "state": state.value})


@app.command()
@usage(surface="st.neri.reports", cmd="st neri reports [--limit 40 --cursor TOKEN]", when="list a page of saved investigation reports", precautions=("read-only; next_cursor resumes the listing; report status and independent review remain separate",), task_types=("neri",))
def reports(limit: Annotated[int, typer.Option(min=1, max=100)] = 40, cursor: str | None = None) -> None:
    params: dict[str, str | int] = {"limit": limit}
    if cursor is not None:
        params["cursor"] = cursor
    request(f"/api/reports?{urlencode(params)}")


@report_app.command("show")
@usage(surface="st.neri.report.show", cmd="st neri report show <investigation-id>", when="read a saved report and its reviews", precautions=("read-only; retain caveats and evidence references",), task_types=("neri",))
def report_show(investigation_id: UUID) -> None:
    request(f"/api/runs/{investigation_id}/report")


@report_app.command("revision")
@usage(surface="st.neri.report.revision", cmd="st neri report revision <investigation-id> <revision-id>", when="read one immutable report revision", precautions=("read-only; fetches only the cited revision; retain caveats and evidence references",), task_types=("neri",))
def report_revision(investigation_id: UUID, revision_id: UUID) -> None:
    """Read one exact report revision without loading report history."""
    request(f"/api/runs/{investigation_id}/reports/{revision_id}")


@report_app.command("review-revision")
@usage(surface="st.neri.report.review-revision", cmd="st neri report review-revision <investigation-id> <revision-id>", when="read one immutable review revision", precautions=("read-only; fetches only the cited revision; preserve its report_revision_id and objections",), task_types=("neri",))
def report_review_revision(investigation_id: UUID, revision_id: UUID) -> None:
    """Read one exact review revision without loading report history."""
    request(f"/api/runs/{investigation_id}/reviews/{revision_id}")


@report_app.command("save")
@usage(surface="st.neri.report.save", cmd="st neri report save <investigation-id> --file report.json [--id UUID]", when="save a report revision based on retained evidence", precautions=("JSON object or stdin; UUID is retained or generated and printed; does not submit reports externally",), task_types=("neri",))
def report_save(investigation_id: UUID, file: Annotated[Path, typer.Option()],
                request_id: Annotated[UUID | None, typer.Option("--id")] = None) -> None:
    request(f"/api/runs/{investigation_id}/report", read_object(file, request_id=request_id, identified=True))


@report_app.command("review")
@usage(surface="st.neri.report.review", cmd="st neri report review <investigation-id> --file review.json [--id UUID]", when="record an independent review of a specific report revision", precautions=("preserve report_revision_id, objections and actual verification attempts; UUID is retained or generated and printed",), task_types=("neri",))
def report_review(investigation_id: UUID, file: Annotated[Path, typer.Option()],
                  request_id: Annotated[UUID | None, typer.Option("--id")] = None) -> None:
    request(f"/api/runs/{investigation_id}/review", read_object(file, request_id=request_id, identified=True))


@report_app.command("download")
@usage(surface="st.neri.report.download", cmd="st neri report download <investigation-id> --output PATH [--revision UUID]", when="download a saved report draft or exact revision", precautions=("omit revision for the latest report; writes a new local file; no external submission",), task_types=("neri",))
def report_download(investigation_id: UUID, output: Annotated[Path, typer.Option()],
                    revision: Annotated[UUID | None, typer.Option(help="Download this exact report revision")] = None) -> None:
    path = f"/api/runs/{investigation_id}/report-download"
    if revision is not None:
        path += f"?{urlencode({'revision': str(revision)})}"
    download_file(path, output)


@app.command()
@usage(surface="st.neri.control", cmd="st neri control <investigation-id> pause|stop", when="pause or stop a Neri-managed operation", precautions=("in-flight work may finish; external terminals remain under their own control",), task_types=("neri",))
def control(investigation_id: UUID, action: Action) -> None:
    request(f"/api/runs/{investigation_id}/control", {"action": action.value, "message": ""})


@app.command()
@usage(surface="st.neri.operation", cmd="st neri operation <investigation-id> <operation-id>", when="inspect a retained managed-operation result", precautions=("read-only; queued status is not completion evidence",), task_types=("neri",))
def operation(investigation_id: UUID, operation_id: UUID) -> None:
    request(f"/api/workbench/{investigation_id}/operations/{operation_id}")


@executor_app.command("operation")
@usage(surface="st.neri.execute.operation", cmd="st neri execute operation <investigation-id> --file operation.json [--id UUID]", when="submit one explicit HTTP or browser action to a run-pinned registered local target", precautions=("target action; include current agent controller identity; no automatic retry; inspect the same operation UUID after an uncertain response",), task_types=("neri",))
def execute_operation(investigation_id: UUID, file: Annotated[Path, typer.Option()],
                      request_id: Annotated[UUID | None, typer.Option("--id")] = None) -> None:
    request(
        f"/api/workbench/{investigation_id}/operations",
        read_object(file, request_id=request_id, identified=True),
    )


@executor_app.command("sequence")
@usage(surface="st.neri.execute.sequence", cmd="st neri execute sequence <investigation-id> --file sequence.json [--id UUID]", when="submit a finite prepared action sequence to a run-pinned registered local target", precautions=("target actions; use only when intermediate judgment is unnecessary; include current controller identity; no automatic retry; inspect the same UUID after uncertainty",), task_types=("neri",))
def execute_sequence(investigation_id: UUID, file: Annotated[Path, typer.Option()],
                     request_id: Annotated[UUID | None, typer.Option("--id")] = None) -> None:
    request(
        f"/api/workbench/{investigation_id}/sequences",
        read_object(file, request_id=request_id, identified=True),
    )


@executor_app.command("reset")
@usage(surface="st.neri.execute.reset", cmd="st neri execute reset <investigation-id> --file reset.json [--id UUID]", when="recreate the exact run-pinned local target from its registered clean state", precautions=("target mutation; global stop and a settled run are required; bind expected_target_manifest_digest; reconcile the same UUID after uncertainty",), task_types=("neri",))
def execute_reset(investigation_id: UUID, file: Annotated[Path, typer.Option()],
                  request_id: Annotated[UUID | None, typer.Option("--id")] = None) -> None:
    request(
        f"/api/workbench/{investigation_id}/target-reset",
        read_object(file, request_id=request_id, identified=True),
    )


@runtime_app.command("show")
@usage(surface="st.neri.runtime.show", cmd="st neri runtime show", when="inspect the Neri emergency admission stop and revision", precautions=("read-only; external terminals remain under their own control",), task_types=("neri",))
def show_runtime() -> None:
    request("/api/runtime-control")


@runtime_app.command("stop")
@usage(surface="st.neri.runtime.stop", cmd="st neri runtime stop", when="hold new Neri-managed work and request cancellation of owned work", precautions=("submitted work may finish; does not stop external terminals; stale stop revisions are accepted",), task_types=("neri",))
def stop_runtime() -> None:
    # Stop accepts stale revisions, so an extra read must not delay it.
    request("/api/runtime-control", {"stopped": True, "expected_revision": 1}, method="PUT")


@runtime_app.command("release")
@usage(surface="st.neri.runtime.release", cmd="st neri runtime release --revision N", when="release emergency admission stop using its observed revision", precautions=("no conflict retry; releasing admission does not resume existing operations",), task_types=("neri",))
def release_runtime(revision: Annotated[int, typer.Option(min=1)]) -> None:
    request("/api/runtime-control", {"stopped": False, "expected_revision": revision}, method="PUT")


@target_app.command("list")
@usage(surface="st.neri.target.list", cmd="st neri target list", when="list compact registered target metadata", precautions=("read-only; registration does not start target work",), task_types=("neri",))
def target_list() -> None:
    request("/api/targets?compact=true")


@target_app.command("show")
@usage(surface="st.neri.target.show", cmd="st neri target show <target-id>", when="read a registered target manifest and digest", precautions=("read-only; inspect the manifest before status changes",), task_types=("neri",))
def target_show(target_id: str) -> None:
    request(f"/api/targets/{quote(target_id, safe='')}")


@target_app.command("register")
@usage(surface="st.neri.target.register", cmd="st neri target register --file target.json", when="register target metadata through Neri", precautions=("JSON object or stdin; records metadata only; API validates boundaries and version identity",), task_types=("neri",))
def target_register(file: Annotated[Path, typer.Option()]) -> None:
    request("/api/targets", read_object(file))


@target_app.command("status")
@usage(surface="st.neri.target.status", cmd="st neri target status <target-id> --file status.json", when="update a registered target's active status", precautions=("preserve manifest_digest, expected_status, status and reason; conflicts are not retried",), task_types=("neri",))
def target_status(target_id: str, file: Annotated[Path, typer.Option()]) -> None:
    request(f"/api/targets/{quote(target_id, safe='')}/status", read_object(file), method="PUT")
