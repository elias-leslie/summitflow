"""Thin CLI for Neri's canonical investigation API; no duplicate execution logic."""
from __future__ import annotations

import json
import sys
from enum import StrEnum
from pathlib import Path
from typing import Annotated
from urllib.parse import quote, urlencode
from uuid import UUID

import httpx
import typer

from .._client_base import APIError
from .._project_client import ProjectApi, ProjectApiClient, ProjectApiConnectError, resolve_api_url
from ..lib.usage import usage
from ..output import output_json

app = typer.Typer(help="Run and inspect Neri's registered local investigations")
brief_app = typer.Typer(help="Save investigation objectives, prospects, sources and decisions")
app.add_typer(brief_app, name="brief")
budget_app = typer.Typer(help="Read advisory subscription usage; legacy allocation preferences do not gate execution")
app.add_typer(budget_app, name="budget")
runtime_app = typer.Typer(help="Inspect or operate Neri's durable global stop")
app.add_typer(runtime_app, name="runtime")
hypothesis_app = typer.Typer(help="Maintain evidence-linked investigation hypotheses")
app.add_typer(hypothesis_app, name="hypothesis")
gap_app = typer.Typer(help="Record and follow verified capability improvements")
app.add_typer(gap_app, name="gap")
evolution_app = typer.Typer(help="Inspect and advance linked development requests through Neri verification")
app.add_typer(evolution_app, name="evolution")
help_app = typer.Typer(help="Inspect assistance requests, attach context and record owner resolutions")
app.add_typer(help_app, name="help")
target_app = typer.Typer(help="Inspect and register local target manifests without executing target work")
app.add_typer(target_app, name="target")
grant_app = typer.Typer(help="Inspect and issue versioned investigation grants through owner-authenticated routes")
app.add_typer(grant_app, name="grant")
kernel_app = typer.Typer(help="Inspect and configure Neri's adaptive kernel")
app.add_typer(kernel_app, name="kernel")
rollout_app = typer.Typer(help="Inspect and update the revisioned automatic evolution rollout")
kernel_app.add_typer(rollout_app, name="rollout")
NERI_API = ProjectApi(project_id="neri", env_var="ST_NERI_API_URL", default_url="http://localhost:8017")


class Variant(StrEnum):
    benchmark = "benchmark"
    secure = "secure"
    object = "object"
    export = "export"
    revocation = "revocation"


class ReasoningProfile(StrEnum):
    automatic = 'sol-automatic'
    astra = 'astra-standard'
    sol = 'sol-daybreak-blue'


class Action(StrEnum):
    pause = "pause"
    resume = "resume"
    step = "step"
    stop = "stop"
    direct = "direct"


def request(path: str, body: dict | None = None, *, method: str | None = None, emit: bool = True) -> dict:
    resolved = resolve_api_url(NERI_API)
    try:
        with ProjectApiClient(resolved.url) as client:
            if method == "PUT":
                result = client.put(path, json_body=body)
            else:
                result = client.get(path) if body is None else client.post(path, json_body=body)
        if emit:
            output_json(result)
        return result
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
@usage(surface="st.neri.start", cmd='st neri start [--target-id TARGET_ID] [--variant benchmark]', when='start an investigation against a registered local target', precautions=('select an active registered target; target manifest and controller mode govern admission; no live bounty targets',), task_types=("neri", "security-labs"), tier="reference")
def start(variant: Variant = Variant.benchmark, advanced: bool = False,
          external: bool = False, native: bool = False, controller_id: str | None = None,
          title: str | None = None, verification: bool = False,
          brief_id: UUID | None = None,
          target_id: str | None = None,
          hunter_profile: ReasoningProfile | None = None,
          reviewer_profile: ReasoningProfile | None = None) -> None:
    """Start a registered local investigation. Guidance does not change permissions."""
    body: dict = {"variant": variant.value, "guidance": "advanced" if advanced else "helper"}
    if native and external:
        raise typer.BadParameter("--native and --external are mutually exclusive")
    if hunter_profile or reviewer_profile:
        if not (native or external):
            raise typer.BadParameter('Explicit profiles require --native or --external')
        body['reasoning_profiles'] = {'hunter': hunter_profile or 'sol-automatic', 'reviewer': reviewer_profile or 'astra-standard'}
    if external:
        if not controller_id:
            raise typer.BadParameter("--controller-id is required for --external")
        body.update(controller_mode="external", controller_id=controller_id)
    elif controller_id:
        raise typer.BadParameter("--controller-id requires --external")
    elif native:
        body["controller_mode"] = "native"
    if title:
        body["title"] = title
    if verification:
        body["origin"] = "verification"
    if brief_id:
        body["brief_id"] = str(brief_id)
    if target_id is not None:
        body["target_id"] = target_id
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
    native = "native"


class Role(StrEnum):
    hunter = "hunter"
    reviewer = "reviewer"
    orchestrator = "orchestrator"


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
@usage(surface="st.neri.capabilities", cmd='st neri capabilities [capability-id] [--compact]', when='discover Neri native orchestration interfaces and payload schemas', precautions=('read-only; schemas describe permitted capabilities, not target authorization',), task_types=("neri", "security-labs"), tier="reference")
def capabilities(
    capability_id: Annotated[str | None, typer.Argument()] = None,
    compact: bool = False,
) -> None:
    """Discover contracts, or describe one capability by its stable ID."""
    if capability_id:
        request(f"/api/capabilities/{quote(capability_id, safe='')}")
    else:
        request("/api/capabilities?compact=true" if compact else "/api/capabilities")


@app.command()
@usage(surface="st.neri.context", cmd='st neri context [run-id] --role orchestrator|hunter|reviewer', when='load canonical Neri operating instructions before orchestration or role assignment', precautions=('orchestrator context without a run describes continuous verified extension; preserve native harness instructions; supplied context is not observed consumption',), task_types=("neri", "security-labs"), tier="reference")
def context(run_id: Annotated[UUID | None, typer.Argument()] = None, role: Role = Role.hunter) -> None:
    """Retrieve role context and actual observations without lab answers."""
    if run_id is None:
        if role != Role.orchestrator:
            raise typer.BadParameter('A run ID is required for investigator and reviewer evidence')
        request('/api/orchestration-context')
    else:
        request(f"/api/runs/{run_id}/context?{urlencode({'role': role.value})}")


@gap_app.command('list')
@usage(surface='st.neri.gap.list', cmd='st neri gap list <run-id>', when='inspect capability gaps and their latest implementation status', precautions=('read-only; reported verification is not independent proof',), task_types=('neri',), tier='reference')
def gap_list(run_id: UUID) -> None:
    request(f'/api/runs/{run_id}/capability-gaps')


@gap_app.command('save')
@usage(surface='st.neri.gap.save', cmd='st neri gap save <run-id> --file gap.json', when='record a reusable improvement needed by an investigation or update its verification', precautions=('use the capabilities schema and expected revision; does not dispatch target work or expand scope',), task_types=('neri',), tier='reference')
def gap_save(run_id: UUID, file: Annotated[Path, typer.Option()]) -> None:
    request(f'/api/runs/{run_id}/capability-gaps', read_object(file), method='PUT')


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


@budget_app.command("show")
@usage(surface="st.neri.budget.show", cmd='st neri budget show', when='inspect informational subscription usage and historical allocation preferences', precautions=('usage is advisory shared-account telemetry; it does not stop or authorize execution',), task_types=("neri", "security-labs"), tier="reference")
def show_budget() -> None:
    """Read advisory usage; missing telemetry or allocation values do not gate work."""
    request("/api/budget")


@budget_app.command("set")
@usage(surface="st.neri.budget.set", cmd='st neri budget set <percent>', when='update a historical allocation preference for compatibility', precautions=('informational only; does not cap execution or purchase credits; conflicts are not retried',), task_types=("neri", "security-labs"), tier="reference")
def set_budget(percent: Annotated[int, typer.Argument(min=0, max=100)]) -> None:
    """Compatibility setting only: this percentage does not cap or pause execution."""
    current = request("/api/budget", emit=False)
    revision = current.get("revision")
    if type(revision) is not int or revision < 1:
        raise typer.BadParameter("Neri returned no valid budget revision; no change was sent")
    request("/api/budget", {"weekly_allowance_percent": percent, "expected_revision": revision}, method="PUT")


@runtime_app.command("show")
@usage(surface="st.neri.runtime.show", cmd='st neri runtime show', when='inspect Neri global stop state and release revision', precautions=('read-only; external terminal processes are outside Neri control',), task_types=("neri", "security-labs"), tier="reference")
def show_runtime() -> None:
    """Read the global stop state, revision and cancellation limits."""
    request("/api/runtime-control")


@runtime_app.command("stop")
@usage(surface="st.neri.runtime.stop", cmd='st neri runtime stop', when='hold all new Neri-managed work and request cancellation of owned work', precautions=('already-submitted provider or target work may finish; does not stop external terminals; stale stop revisions are accepted',), task_types=("neri", "security-labs"), tier="reference")
def stop_runtime() -> None:
    """Engage global stop immediately. Evidence stays; submitted work may finish."""
    # Stops accept stale revisions, so an extra read must not delay this action.
    request("/api/runtime-control", {"stopped": True, "expected_revision": 1}, method="PUT")


@runtime_app.command("release")
@usage(surface="st.neri.runtime.release", cmd='st neri runtime release --revision N', when='explicitly release Neri global stop after reading its current revision', precautions=('stale release conflicts are not retried; release does not resume runs or scans',), task_types=("neri", "security-labs"), tier="reference")
def release_runtime(revision: Annotated[int, typer.Option(min=1)]) -> None:
    """Release using the observed revision. Preserved work remains held."""
    request("/api/runtime-control", {"stopped": False, "expected_revision": revision}, method="PUT")


@hypothesis_app.command("list")
@usage(surface="st.neri.hypothesis.list", cmd='st neri hypothesis list <run-id>', when='inspect persisted investigation hypotheses', precautions=('read-only; supported status is an evidence claim, not independent validation',), task_types=("neri", "security-labs"), tier="reference")
def hypotheses(run_id: UUID, include_archived: bool = False) -> None:
    path = f"/api/runs/{run_id}/hypotheses"
    request(path + "?include_archived=true" if include_archived else path)


@hypothesis_app.command("create")
@usage(surface="st.neri.hypothesis.create", cmd='st neri hypothesis create <run-id> --file hypothesis.json', when='record an investigation hypothesis through the canonical API', precautions=('use the capabilities schema; agent attribution requires current external controller identity and revision',), task_types=("neri", "security-labs"), tier="reference")
def create_hypothesis(run_id: UUID, file: Annotated[Path, typer.Option()]) -> None:
    request(f"/api/runs/{run_id}/hypotheses", read_object(file))


@hypothesis_app.command("update")
@usage(surface="st.neri.hypothesis.update", cmd='st neri hypothesis update <run-id> <hypothesis-id> --file hypothesis.json', when='update a hypothesis and its supporting or contrary evidence', precautions=('include expected_revision from the current hypothesis; backend enforces evidence and controller fencing',), task_types=("neri", "security-labs"), tier="reference")
def update_hypothesis(run_id: UUID, hypothesis_id: UUID, file: Annotated[Path, typer.Option()]) -> None:
    request(f"/api/runs/{run_id}/hypotheses/{hypothesis_id}", read_object(file), method="PUT")


workbench_app = typer.Typer(help='Operate the isolated HTTP/browser workbench through Neri admission and evidence')
app.add_typer(workbench_app, name='workbench')


@workbench_app.command('targets')
@usage(surface='st.neri.workbench.targets', cmd='st neri workbench targets', when='discover registered proxy targets and qualification state', precautions=('read-only; use only registered authorized targets',), task_types=('neri','security-labs'), tier='reference')
def workbench_targets() -> None:
    request('/api/workbench/targets')


@workbench_app.command('start')
@usage(surface='st.neri.workbench.start', cmd='st neri workbench start --title TEXT --controller-id ID', when='create an isolated workbench investigation for native orchestration', precautions=('no target request is sent; global stop must be explicitly released first',), task_types=('neri','security-labs'), tier='reference')
def workbench_start(title: str='Juice Shop investigation', controller_id: str='native-tui') -> None:
    request('/api/workbench/investigations', {'title':title,'controller_id':controller_id})


@workbench_app.command('traffic')
@usage(surface='st.neri.workbench.traffic', cmd='st neri workbench traffic <run-id>', when='inspect immutable proxy observations and held-message state', precautions=('read-only; does not renew execution; credential and benchmark content is omitted from the reasoning projection',), task_types=('neri','security-labs'), tier='reference')
def workbench_traffic(run_id: UUID) -> None:
    request(f'/api/workbench/{run_id}/traffic')


@workbench_app.command('send')
@usage(surface='st.neri.workbench.send', cmd='st neri workbench send <run-id> --file operation.json', when='submit a scoped HTTP request or browser action', precautions=('load capabilities schema and controller context first; include actor=agent and current identity/revision; reuse an operation UUID only for identical submission; inspect uncertainty instead of retrying',), task_types=('neri','security-labs'), tier='reference')
def workbench_send(run_id: UUID, file: Annotated[Path,typer.Option()]) -> None:
    request(f'/api/workbench/{run_id}/operations',read_object(file))


@workbench_app.command('operation')
@usage(surface='st.neri.workbench.operation', cmd='st neri workbench operation <run-id> <operation-id>', when='read actual operation completion, browser observations or sequence assertions', precautions=('queued is not proof of transfer; reading does not send target requests',), task_types=('neri','security-labs'), tier='reference')
def workbench_operation(run_id: UUID, operation_id: UUID) -> None:
    request(f'/api/workbench/{run_id}/operations/{operation_id}')


@workbench_app.command('sequence')
@usage(surface='st.neri.workbench.sequence', cmd='st neri workbench sequence <run-id> --file sequence.json', when='execute a finite prepared sequence with named extraction and assertions', precautions=('stops at first failed assertion; no automatic retries; extracted values are substituted only into scoped paths; owner can stop all work',), task_types=('neri','security-labs'), tier='reference')
def workbench_sequence(run_id: UUID, file: Annotated[Path,typer.Option()]) -> None:
    request(f'/api/workbench/{run_id}/sequences',read_object(file))


@workbench_app.command('intercept')
@usage(surface='st.neri.workbench.intercept', cmd='st neri workbench intercept <run-id> --file interception.json', when='configure request or response interception for an investigation', precautions=('configuration sends no target requests; response interception happens after target processing',), task_types=('neri','security-labs'), tier='reference')
def workbench_intercept(run_id: UUID, file: Annotated[Path,typer.Option()]) -> None:
    request(f'/api/workbench/{run_id}/interception',read_object(file))


@workbench_app.command('flow')
@usage(surface='st.neri.workbench.flow', cmd='st neri workbench flow <run-id> <flow-id> --file control.json', when='explicitly forward, edit or drop a held message', precautions=('global stop and controller fencing apply; original message stays immutable; dropping a response cannot undo target effects',), task_types=('neri','security-labs'), tier='reference')
def workbench_flow(run_id: UUID, flow_id: UUID, file: Annotated[Path,typer.Option()]) -> None:
    request(f'/api/workbench/{run_id}/traffic/{flow_id}/control',read_object(file))


@evolution_app.command("list")
@usage(surface="st.neri.evolution.list", cmd="st neri evolution list [--run-id UUID]", when="list Neri development requests and linked managed tasks", precautions=("read-only; task status comes from SummitFlow",), task_types=("neri",), tier="reference")
def evolution_list(run_id: UUID | None = None) -> None:
    request("/api/evolution-attempts" + (f"?{urlencode({'run_id': str(run_id)})}" if run_id else ""))


@evolution_app.command("show")
@usage(surface="st.neri.evolution.show", cmd="st neri evolution show <attempt-id>", when="inspect development request correlation and results", precautions=("use ordinary st context/claim/checkpoint/done on the linked task",), task_types=("neri",), tier="reference")
def evolution_show(attempt_id: UUID) -> None:
    request(f"/api/evolution-attempts/{attempt_id}")


@evolution_app.command("start")
@usage(surface="st.neri.evolution.start", cmd="st neri evolution start <run-id> --file evolution.json", when="record an explicit development attempt for a saved capability gap", precautions=("preserve gap identity and revision; Neri freezes the current grant and resume state; task creation is not activation",), task_types=("neri",), tier="reference")
def evolution_start(run_id: UUID, file: Annotated[Path, typer.Option()]) -> None:
    """Start a managed development request, including when automatic rollout is disabled."""
    request(f"/api/runs/{run_id}/evolution-attempts", read_object(file))


@evolution_app.command("reconcile")
@usage(surface="st.neri.evolution.reconcile", cmd="st neri evolution reconcile <attempt-id>", when="reconcile an evolution attempt with its managed development task", precautions=("may deliver the saved development request; Neri rechecks authority and stop state; do not retry uncertain outcomes blindly",), task_types=("neri",), tier="reference")
def evolution_reconcile(attempt_id: UUID) -> None:
    """Reconcile the saved attempt and its linked SummitFlow task."""
    request(f"/api/evolution-attempts/{attempt_id}/reconcile", {})


@evolution_app.command("verify")
@usage(surface="st.neri.evolution.verify", cmd="st neri evolution verify <attempt-id> --file verification.json", when="verify a frozen acceptance predicate against a retained capability receipt", precautions=("preserve expected_revision and receipt_id; Neri checks immutable receipt provenance; verification is not activation",), task_types=("neri",), tier="reference")
def evolution_verify(attempt_id: UUID, file: Annotated[Path, typer.Option()]) -> None:
    """Verify the saved attempt using an actual immutable capability receipt."""
    request(f"/api/evolution-attempts/{attempt_id}/verify", read_object(file))


@evolution_app.command("qualify")
@usage(surface="st.neri.evolution.qualify", cmd="st neri evolution qualify <attempt-id>", when="evaluate an evolution candidate against its frozen acceptance evidence", precautions=("uses the deterministic Neri verifier; a task completion or passing CI alone is not acceptance",), task_types=("neri",), tier="reference")
def evolution_qualify(attempt_id: UUID) -> None:
    """Record verifier results from the candidate's retained evidence."""
    request(f"/api/evolution-attempts/{attempt_id}/qualify", {})


@evolution_app.command("activate")
@usage(surface="st.neri.evolution.activate", cmd="st neri evolution activate <attempt-id> --file activation.json", when="activate an accepted capability artifact through Neri", precautions=("JSON object or stdin; preserve verifier receipt, artifact identity and permissions; API checks current grant",), task_types=("neri",), tier="reference")
def evolution_activate(attempt_id: UUID, file: Annotated[Path, typer.Option()]) -> None:
    """Activate the exact accepted artifact described in a JSON object."""
    request(f"/api/evolution-attempts/{attempt_id}/activate", read_object(file))


@evolution_app.command("resume")
@usage(surface="st.neri.evolution.resume", cmd="st neri evolution resume <attempt-id>", when="resume an investigation after its capability improvement is accepted and activated", precautions=("Neri checks the saved resume fence and outstanding work; stale authority or uncertainty blocks continuation",), task_types=("neri",), tier="reference")
def evolution_resume(attempt_id: UUID) -> None:
    """Request continuation through the attempt's saved resume fence."""
    request(f"/api/evolution-attempts/{attempt_id}/resume", {})


@help_app.command("list")
@usage(surface="st.neri.help.list", cmd="st neri help list [--status STATUS]", when="list Neri assistance requests", precautions=("read-only; no new task ownership",), task_types=("neri",), tier="reference")
def help_list(status: str | None = None) -> None:
    request("/api/help-requests" + (f"?{urlencode({'status': status})}" if status else ""))


@help_app.command("show")
@usage(surface="st.neri.help.show", cmd="st neri help show <request-id>", when="inspect an assistance request", precautions=("read-only",), task_types=("neri",), tier="reference")
def help_show(request_id: UUID) -> None:
    request(f"/api/help-requests/{request_id}")


@help_app.command("context")
@usage(surface="st.neri.help.context", cmd="st neri help context <request-id>", when="load canonical assistance context in a connected TUI", precautions=("context retrieval is not observed model consumption",), task_types=("neri",), tier="reference")
def help_context(request_id: UUID) -> None:
    request(f"/api/help-requests/{request_id}/context")


@help_app.command("attach")
@usage(surface="st.neri.help.attach", cmd="st neri help attach <request-id> --file attachment.json", when="attach assistance evidence or an update through Neri", precautions=("JSON object or stdin; preserves supplied revision and attribution",), task_types=("neri",), tier="reference")
def help_attach(request_id: UUID, file: Annotated[Path, typer.Option()]) -> None:
    request(f"/api/help-requests/{request_id}/attachments", read_object(file))


@help_app.command("resolve")
@usage(surface="st.neri.help.resolve", cmd="st neri help resolve <request-id> --file resolution.json", when="record an owner resolution through the canonical Neri route", precautions=("preserves expected revision; API enforces owner authority; no automatic retry",), task_types=("neri",), tier="reference")
def help_resolve(request_id: UUID, file: Annotated[Path, typer.Option()]) -> None:
    request(f"/api/help-requests/{request_id}/resolution", read_object(file), method="PUT")


@target_app.command("list")
@usage(surface="st.neri.target.list", cmd="st neri target list", when="discover registered local targets using compact manifests", precautions=("read-only; registration is not execution authorization",), task_types=("neri",), tier="reference")
def target_list() -> None:
    """List compact target identities, status and available capabilities."""
    request("/api/targets?compact=true")


@target_app.command("show")
@usage(surface="st.neri.target.show", cmd="st neri target show <target-id>", when="read a registered target's full manifest and immutable digest", precautions=("read-only; inspect the current manifest before status changes",), task_types=("neri",), tier="reference")
def target_show(target_id: str) -> None:
    """Read the full registered manifest, including setup and reset procedures."""
    request(f"/api/targets/{quote(target_id, safe='')}")


@target_app.command("register")
@usage(surface="st.neri.target.register", cmd="st neri target register --file target.json", when="register a local target manifest through Neri's owner-authenticated API", precautions=("JSON object or stdin; records metadata only; API validates boundaries and version identity",), task_types=("neri",), tier="reference")
def target_register(file: Annotated[Path, typer.Option()]) -> None:
    """Register manifest data; '-' reads stdin. No target work is started."""
    request("/api/targets", read_object(file))


@target_app.command("status")
@usage(surface="st.neri.target.status", cmd="st neri target status <target-id> --file status.json", when="reversibly activate or deactivate a registered target", precautions=("preserve manifest_digest, expected_status, status and reason; API enforces owner authority; conflicts are not retried",), task_types=("neri",), tier="reference")
def target_status(target_id: str, file: Annotated[Path, typer.Option()]) -> None:
    """Update status using the observed manifest digest and expected status."""
    request(f"/api/targets/{quote(target_id, safe='')}/status", read_object(file), method="PUT")


@grant_app.command("list")
@usage(surface="st.neri.grant.list", cmd="st neri grant list <run-id>", when="inspect immutable authority revisions for an investigation", precautions=("read-only; use the latest revision before issuing a new grant",), task_types=("neri",), tier="reference")
def grant_list(run_id: UUID) -> None:
    """Read the investigation's grant history in revision order."""
    request(f"/api/runs/{run_id}/grants")


@grant_app.command("issue")
@usage(surface="st.neri.grant.issue", cmd="st neri grant issue <run-id> --file grant.json", when="issue an authorized immutable investigation grant revision", precautions=("owner-authenticated API; preserve expected_revision and the authorized scope; conflicts are not retried",), task_types=("neri",), tier="reference")
def grant_issue(run_id: UUID, file: Annotated[Path, typer.Option()]) -> None:
    """Issue a new grant revision from an authorized JSON object."""
    request(f"/api/runs/{run_id}/grants", read_object(file))


@grant_app.command("upgrade")
@usage(surface="st.neri.grant.upgrade", cmd="st neri grant upgrade <run-id>", when="explicitly bind a preserved pre-kernel investigation to its registered target grant", precautions=("owner-authenticated API; preserves an existing grant; does not resume the investigation",), task_types=("neri",), tier="reference")
def grant_upgrade(run_id: UUID) -> None:
    """Upgrade a legacy investigation through Neri's grant migration route."""
    request(f"/api/runs/{run_id}/grants/upgrade", {})


@rollout_app.command("show")
@usage(surface="st.neri.kernel.rollout.show", cmd="st neri kernel rollout show", when="inspect the adaptive kernel rollout and acceptance references", precautions=("read-only; disabled rollout preserves manual development workflows",), task_types=("neri",), tier="reference")
def rollout_show() -> None:
    """Read automatic evolution status, revision and decision history."""
    request("/api/kernel-rollout")


@rollout_app.command("set")
@usage(surface="st.neri.kernel.rollout.set", cmd="st neri kernel rollout set --file rollout.json", when="record an authorized kernel rollout decision", precautions=("preserve expected_revision, enabled, acceptance_refs and reason; enabling requires retained verifier acceptance; no conflict retry",), task_types=("neri",), tier="reference")
def rollout_set(file: Annotated[Path, typer.Option()]) -> None:
    """Update rollout using the observed revision and acceptance evidence."""
    request("/api/kernel-rollout", read_object(file), method="PUT")
