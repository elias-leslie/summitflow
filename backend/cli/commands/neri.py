"""Thin CLI for Neri's canonical investigation API; no duplicate execution logic."""
from __future__ import annotations

import json
import sys
from enum import StrEnum
from pathlib import Path
from typing import Annotated
from urllib.parse import urlencode
from uuid import UUID

import httpx
import typer

from .._client_base import APIError
from .._project_client import ProjectApi, ProjectApiClient, ProjectApiConnectError, resolve_api_url
from ..lib.usage import usage
from ..output import output_json

app = typer.Typer(help="Run and inspect Neri's isolated discovery labs")
brief_app = typer.Typer(help="Save investigation objectives, prospects, sources and decisions")
app.add_typer(brief_app, name="brief")
NERI_API = ProjectApi(project_id="neri", env_var="ST_NERI_API_URL", default_url="http://localhost:8017")


class Variant(StrEnum):
    benchmark = "benchmark"
    secure = "secure"
    object = "object"
    export = "export"
    revocation = "revocation"


class Action(StrEnum):
    pause = "pause"
    resume = "resume"
    step = "step"
    stop = "stop"
    direct = "direct"


def request(path: str, body: dict | None = None, *, method: str | None = None) -> None:
    resolved = resolve_api_url(NERI_API)
    try:
        with ProjectApiClient(resolved.url) as client:
            if method == "PUT":
                result = client.put(path, json_body=body)
            else:
                result = client.get(path) if body is None else client.post(path, json_body=body)
        output_json(result)
    except ProjectApiConnectError:
        output_json({"ok": False, "error": "neri_unreachable", "hint": "Check st service status neri or ST_NERI_API_URL"})
        raise typer.Exit(2) from None
    except APIError as exc:
        output_json({"ok": False, "error": "neri_api_error", "detail": exc.detail})
        raise typer.Exit(1) from None


@app.command()
@usage(surface="st.neri.labs", cmd='st neri labs', when='list Neri authorized lab environments', precautions=('read-only; never implies live-target authorization',), task_types=("neri", "security-labs"), tier="reference")
def labs() -> None:
    """List available authorized lab environments."""
    request("/api/labs")


@app.command()
@usage(surface="st.neri.runs", cmd='st neri runs', when='inspect Neri investigation status and outcomes', precautions=('read-only; seeded outcomes are not bounty income',), task_types=("neri", "security-labs"), tier="reference")
def runs() -> None:
    """List persisted investigations and outcomes."""
    request("/api/runs")


@app.command()
@usage(surface="st.neri.start", cmd='st neri start --variant benchmark', when='start real agent-led discovery inside Neri labs', precautions=('executes lab requests within the run budget; no live bounty targets',), task_types=("neri", "security-labs"), tier="reference")
def start(variant: Variant = Variant.benchmark, advanced: bool = False,
          external: bool = False, controller_id: str | None = None,
          title: str | None = None, verification: bool = False,
          brief_id: UUID | None = None) -> None:
    """Start actual agent-led discovery. Guidance mode does not change permissions."""
    body = {"variant": variant.value, "guidance": "advanced" if advanced else "helper"}
    if external:
        if not controller_id:
            raise typer.BadParameter("--controller-id is required for --external")
        body.update(controller_mode="external", controller_id=controller_id)
    elif controller_id:
        raise typer.BadParameter("--controller-id requires --external")
    if title:
        body["title"] = title
    if verification:
        body["origin"] = "verification"
    if brief_id:
        body["brief_id"] = str(brief_id)
    request("/api/runs", body)


@app.command()
@usage(surface="st.neri.show", cmd='st neri show <run-id>', when='inspect a persisted Neri timeline and evidence', precautions=('read-only; replay never reissues target requests',), task_types=("neri", "security-labs"), tier="reference")
def show(run_id: UUID) -> None:
    """Read a run and its ordered timeline; never executes lab actions."""
    request(f"/api/runs/{run_id}")


@app.command()
@usage(surface="st.neri.control", cmd='st neri control <run-id> pause|resume|step|stop|direct --message TEXT', when='direct or control an existing Neri investigation', precautions=('pause waits for an in-flight operation; step executes one action; advanced guidance never expands scope',), task_types=("neri", "security-labs"), tier="reference")
def control(run_id: UUID, action: Action, message: str = "") -> None:
    """Pause, resume, single-step, stop or direct a run through its API."""
    if action == Action.direct and not message.strip():
        raise typer.BadParameter("--message is required for direct")
    request(f"/api/runs/{run_id}/control", {"action": action.value, "message": message})


@app.command()
@usage(surface="st.neri.report", cmd='st neri report <run-id>', when='read Neri evidence-linked report, review and independent grading', precautions=('reviewer caveats are part of the draft; no report submission is authorized',), task_types=("neri", "security-labs"), tier="reference")
def report(run_id: UUID) -> None:
    """Read the report, independent review and benchmark outcome."""
    request(f"/api/runs/{run_id}/report")


class ControllerMode(StrEnum):
    automatic = "automatic"
    external = "external"


class Role(StrEnum):
    hunter = "hunter"
    reviewer = "reviewer"


class CommandKind(StrEnum):
    action = "action"
    review = "review"


def read_object(path: Path) -> dict:
    """Read JSON as data; '-' accepts stdin without shell interpolation."""
    try:
        value = json.loads(sys.stdin.read() if str(path) == "-" else path.read_text())
    except (OSError, ValueError) as exc:
        raise typer.BadParameter(f"Could not read JSON object: {type(exc).__name__}") from None
    if not isinstance(value, dict):
        raise typer.BadParameter("The JSON document must be an object")
    return value


@app.command()
@usage(surface="st.neri.capabilities", cmd='st neri capabilities', when='discover Neri native orchestration interfaces and payload schemas', precautions=('read-only; schemas describe permitted capabilities, not target authorization',), task_types=("neri", "security-labs"), tier="reference")
def capabilities() -> None:
    """Discover canonical command contracts and supported workflow capabilities."""
    request("/api/capabilities")


@app.command()
@usage(surface="st.neri.context", cmd='st neri context <run-id> --role hunter', when='brief a native investigator or reviewer with filtered evidence and canonical Agent Hub instructions', precautions=('preserve native harness instructions; benchmark context excludes grader and operator state; verify delivery provenance before recording acknowledgement',), task_types=("neri", "security-labs"), tier="reference")
def context(run_id: UUID, role: Role = Role.hunter) -> None:
    """Retrieve role context and actual observations without lab answers."""
    request(f"/api/runs/{run_id}/context?{urlencode({'role': role.value})}")


@app.command()
@usage(surface="st.neri.controller", cmd='st neri controller <run-id> external --controller-id SESSION --revision N', when='take over or hand back a Neri investigation at an action boundary', precautions=('requires current revision; does not interrupt or repeat an in-flight request; controller labels are attribution, not credentials',), task_types=("neri", "security-labs"), tier="reference")
def controller(run_id: UUID, mode: ControllerMode,
               revision: Annotated[int, typer.Option(min=1)], controller_id: str | None = None) -> None:
    """Transfer between automatic and native execution using the current revision."""
    if mode == ControllerMode.external and not controller_id:
        raise typer.BadParameter("--controller-id is required for external control")
    request(f"/api/runs/{run_id}/controller", {
        "mode": mode.value, "controller_id": controller_id, "expected_revision": revision,
    })


@app.command()
@usage(surface="st.neri.submit", cmd='st neri submit <run-id> --file payload.json --command-id UUID --controller-id SESSION --revision N', when='submit one native agent action or independent review through the canonical Neri executor', precautions=('use a stable command ID for resubmission; never directly call the lab; kind=review records review, kind=action executes the validated action or report',), task_types=("neri", "security-labs"), tier="reference")
def submit(run_id: UUID, file: Annotated[Path, typer.Option()],
           command_id: Annotated[UUID, typer.Option()], controller_id: Annotated[str, typer.Option()],
           revision: Annotated[int, typer.Option(min=1)], kind: CommandKind = CommandKind.action) -> None:
    """Submit a JSON proposal; '-' reads stdin. Inspect the returned command to follow execution."""
    request(f"/api/runs/{run_id}/commands", {
        "command_id": str(command_id), "controller_id": controller_id,
        "controller_revision": revision, "kind": kind.value, "payload": read_object(file),
    })


@app.command()
@usage(surface="st.neri.command", cmd='st neri command <run-id> <command-id>', when='inspect the durable outcome of a submitted Neri action', precautions=('read-only; inspect an uncertain command before resubmitting its same ID',), task_types=("neri", "security-labs"), tier="reference")
def command(run_id: UUID, command_id: UUID) -> None:
    """Read a command's execution status and persisted result."""
    request(f"/api/runs/{run_id}/commands/{command_id}")


@app.command()
@usage(surface="st.neri.assignment", cmd='st neri assignment <run-id> --file assignment.json', when='record a native agent assignment, context acknowledgement, progress or result in Neri', precautions=('records supplied provenance; never claim model context was consumed merely because it was generated; does not invoke a model',), task_types=("neri", "security-labs"), tier="reference")
def assignment(run_id: UUID, file: Annotated[Path, typer.Option()]) -> None:
    """Record native agent activity using the capabilities assignment schema."""
    request(f"/api/runs/{run_id}/assignments", read_object(file))


@app.command()
@usage(surface="st.neri.watch", cmd='st neri watch <run-id> --after N', when='follow persisted Neri events from a terminal as JSON lines', precautions=('read-only; stream closure is not proof that the worker stopped; reconnect with last recorded sequence',), task_types=("neri", "security-labs"), tier="reference")
def watch(run_id: UUID, after: int = typer.Option(0, min=0)) -> None:
    """Stream new steps and status; Ctrl-C detaches without changing execution."""
    url = resolve_api_url(NERI_API).url.rstrip("/")
    try:
        with (
            httpx.Client(timeout=httpx.Timeout(30, read=None)) as client,
            client.stream("GET", f"{url}/api/runs/{run_id}/events", params={"after": after}) as response,
        ):
            response.raise_for_status()
            event = "message"
            for line in response.iter_lines():
                if line.startswith("event:"):
                    event = line[6:].strip()
                elif line.startswith("data:"):
                    value = json.loads(line[5:].strip())
                    typer.echo(json.dumps({"event": event, "data": value}), nl=True)
    except KeyboardInterrupt:
        return
    except (httpx.HTTPError, ValueError) as exc:
        output_json({"ok": False, "error": "neri_stream_failed", "reason": type(exc).__name__,
                     "hint": "Inspect the run and reconnect using its last recorded event sequence"})
        raise typer.Exit(2) from None


@brief_app.command("list")
@usage(surface="st.neri.brief.list", cmd='st neri brief list', when='read saved Neri investigation briefs and prospects', precautions=('briefs do not authorize live execution',), task_types=("neri", "security-labs"), tier="reference")
def briefs() -> None:
    request("/api/briefs")


@brief_app.command("create")
@usage(surface="st.neri.brief.create", cmd='st neri brief create --file brief.json', when='preserve agreed investigation objectives, prospects, sources and scope notes', precautions=('store agreed decisions and sources; no automatic ingestion of private terminal transcripts',), task_types=("neri", "security-labs"), tier="reference")
def create_brief(file: Annotated[Path, typer.Option()]) -> None:
    request("/api/briefs", read_object(file))


@brief_app.command("update")
@usage(surface="st.neri.brief.update", cmd='st neri brief update <brief-id> --file brief.json', when='update the saved investigation brief with agreed decisions', precautions=('does not expand an execution envelope',), task_types=("neri", "security-labs"), tier="reference")
def update_brief(brief_id: UUID, file: Annotated[Path, typer.Option()]) -> None:
    request(f"/api/briefs/{brief_id}", read_object(file), method="PUT")
