"""Thin terminal client for Neri's saved investigations and evidence API."""
from __future__ import annotations

import json
import re
import sys
from contextlib import suppress
from enum import StrEnum
from pathlib import Path
from typing import Annotated, Any, Literal
from urllib.parse import quote, urlencode, urljoin, urlsplit
from uuid import UUID, uuid4

import httpx
import typer

from .._client_base import APIError
from .._project_client import ProjectApi, ProjectApiClient, ProjectApiConnectError, resolve_api_url
from ..lib.usage import usage
from ..output import output_json
from ._api_paths import (
    NERI_LOCAL_WORKER_BENCHMARK_PATH,
    NERI_LOCAL_WORKER_EVALUATE_PATH,
    NERI_LOCAL_WORKER_STATUS_PATH,
)
from .memory_api import agent_hub_request

app = typer.Typer(help="Read and maintain Neri targets, investigations, notes, reports and disclosure programs")
evidence_app = typer.Typer(help="Import evidence and inspect retained artifacts")
notes_app = typer.Typer(help="Save contextual notes and direction")
report_app = typer.Typer(help="Read exact report and review revisions, save reports and download drafts")
report_severity_app = typer.Typer(help="Read and save immutable severity assessments for an exact report revision")
executor_app = typer.Typer(help="Submit explicit typed actions to a registered local target")
target_app = typer.Typer(help="Inspect and maintain registered target metadata")
group_app = typer.Typer(help="Read and organize passive investigations containing saved attempts")
target_notes_app = typer.Typer(help="Save target direction and read its state history")
group_notes_app = typer.Typer(help="Save investigation direction and read its state history")
program_app = typer.Typer(help="Maintain passive disclosure programs and exact policy revisions")
target_programs_app = typer.Typer(help="Record exact target applicability and its revision history")
runtime_app = typer.Typer(help="Inspect or operate Neri's emergency admission stop")
research_app = typer.Typer(help="Read research capability progress and save exact associations")
worker_app = typer.Typer(
    help="Inspect the bounded local candidate and Neri-owned qualification evidence"
)
app.add_typer(evidence_app, name="evidence")
app.add_typer(notes_app, name="notes")
app.add_typer(report_app, name="report")
report_app.add_typer(report_severity_app, name="severity")
app.add_typer(executor_app, name="execute")
app.add_typer(target_app, name="target")
app.add_typer(group_app, name="group")
target_app.add_typer(target_notes_app, name="notes")
group_app.add_typer(group_notes_app, name="notes")
app.add_typer(program_app, name="program")
target_app.add_typer(target_programs_app, name="programs")
app.add_typer(runtime_app, name="runtime")
app.add_typer(research_app, name="research")
app.add_typer(worker_app, name="worker")
NERI_API = ProjectApi(project_id="neri", env_var="ST_NERI_API_URL", default_url="http://localhost:8017")
NERI_LOCAL_WORKER_QUALIFICATION_PATH = "/api/research/local-worker/qualification"
NERI_LOCAL_WORKER_QUALIFICATION_DECISIONS_PATH = f"{NERI_LOCAL_WORKER_QUALIFICATION_PATH}/decisions"
NERI_LOCAL_WORKER_SHADOW_ASSIGNMENTS_PATH = "/api/research/local-worker/shadow-assignments"
LOCAL_WORKER_SHADOW_TIMEOUT_SECONDS = 330.0
SAFE_NERI_PROBLEMS: dict[str, tuple[str, str | None]] = {
    "control_evidence_incomplete": ("Add evidence for every required control.", "control_evidence"),
    "control_evidence_unreviewed": ("Use control evidence covered by the exact review.", "control_evidence"),
    "environment_mismatch": ("Use the environment pinned by the target.", "environment_kind"),
    "evidence_reference_invalid": ("Use evidence saved in this investigation.", "evidence_refs"),
    "missing_program_binding": ("Select the exact program and scope revision.", "program_binding_revision_id"),
    "missing_required_tool": ("Include every tool required by this method.", "configuration_identity.tool_capability_ids"),
    "report_revision_invalid": ("Use an exact report revision from this investigation.", "report_revision_id"),
    "request_identity_conflict": ("This retry key belongs to different content.", "request_key"),
    "request_key_conflict": ("This request key already belongs to another record.", "request_key"),
    "research_case_invalid": ("The research case is not valid.", None),
    "result_already_associated": ("This prospective case already has a saved result.", "selection_id"),
    "review_revision_invalid": ("Use the review bound to the exact report.", "review_revision_id"),
    "safety_policy_mismatch": ("Reload and acknowledge the current method safety rules.", "configuration_identity.safety_policy_digest"),
    "selection_already_closed": ("This prospective case already has a closeout record.", "selection_id"),
    "selection_already_exists": ("This prospective case selection already exists.", "request_key"),
    "selection_has_result": ("A reviewed result cannot be replaced by case invalidation.", "selection_id"),
    "selection_invalidated": ("This prospective case was closed without method evidence.", "selection_id"),
    "selection_mismatch": ("Use the selection for this exact planned case.", "selection_link_id"),
    "selection_not_found": ("The prospective case selection was not found.", "selection_id"),
    "target_build_mismatch": ("Use the build pinned by this investigation.", "configuration_identity.target_build_identity"),
    "target_manifest_mismatch": ("Reload the investigation's pinned target.", "run_id"),
    "tool_not_permitted": ("Remove tools that are not allowed for this target.", "additional_tool_capability_ids"),
    "unknown_capability_revision": ("Reload and select an available research method revision.", "capability_id"),
}


class Action(StrEnum):
    pause = "pause"
    stop = "stop"


class NoteState(StrEnum):
    acknowledged = "acknowledged"
    resolved = "resolved"


class DirectionNoteState(StrEnum):
    saved = "saved"
    acknowledged = "acknowledged"
    resolved = "resolved"


class ReportView(StrEnum):
    investigations = "investigations"


class WorkspaceFilter(StrEnum):
    all = "all"
    active = "active"
    attention = "attention"
    awaiting_review = "awaiting_review"
    reviewed_findings = "reviewed_findings"
    reviewed_no_findings = "reviewed_no_findings"


class LocalWorkerTask(StrEnum):
    facts_unknowns = "facts_unknowns"
    evidence_consistency = "evidence_consistency"
    scope_policy_parse = "scope_policy_parse"
    evidence_condensation = "evidence_condensation"
    matrix_construction = "matrix_construction"
    hypothesis_controls = "hypothesis_controls"
    candidate_triage = "candidate_triage"
    learning_draft = "learning_draft"


class LocalWorkerArm(StrEnum):
    bare_schema = "bare_schema"
    role_checklist = "role_checklist"
    grounded_decomposition = "grounded_decomposition"
    critique_repair = "critique_repair"


class LocalWorkerSplit(StrEnum):
    development = "development"
    locked = "locked"


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


def request(path: str, body: dict | None = None, *, method: str | None = None, emit: bool = True,
            identity_field: Literal["id", "mutation_id", "request_id"] = "id",
            timeout: float = 30.0) -> Any:
    """Use the shared project transport once; never echo failed input or credentials."""
    identity = {}
    if body and identity_field in body:
        # Target manifest IDs are not mutation UUIDs.
        with suppress(AttributeError, TypeError, ValueError):
            identity["request_id"] = str(UUID(body[identity_field]))
    resolved = resolve_api_url(NERI_API)
    try:
        with ProjectApiClient(resolved.url, timeout=timeout) as client:
            if method == "PUT":
                result = client.put(path, json_body=body)
            elif method == "PATCH":
                result = client.patch(path, json_body=body)
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
        problem = None
        if isinstance(exc.detail, dict):
            code = exc.detail.get("code")
            safe_problem = SAFE_NERI_PROBLEMS.get(code) if isinstance(code, str) else None
            if safe_problem:
                message, field = safe_problem
                problem = {"code": code, "message": message}
                if field:
                    problem["field"] = field
        output_json({
            "ok": False,
            "error": "neri_api_error",
            "status": exc.status_code,
            **identity,
            **({"problem": problem} if problem else {}),
            "hint": (
                "Correct the named field and retry with the same request key only when "
                "the saved content is unchanged"
                if problem else
                "Check the API schema and current record; reuse the request ID only for identical content"
            ),
        })
        raise typer.Exit(1) from None


def read_object(path: Path, *, request_id: UUID | None = None, identified: bool = False,
                identity_field: Literal["id", "mutation_id", "request_id"] = "id") -> dict:
    """Read literal JSON from a file/stdin and retain or allocate its mutation UUID."""
    try:
        value = json.loads(sys.stdin.read() if str(path) == "-" else path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise typer.BadParameter(f"Could not read JSON object: {type(exc).__name__}") from None
    if not isinstance(value, dict):
        raise typer.BadParameter("The JSON document must be an object")
    if identified:
        if identity_field in value:
            try:
                supplied_id = UUID(value[identity_field])
            except (AttributeError, TypeError, ValueError):
                raise typer.BadParameter(f"JSON {identity_field} must be a UUID") from None
            if request_id is not None and supplied_id != request_id:
                raise typer.BadParameter(f"--id must match the JSON {identity_field}")
            request_id = supplied_id
        value[identity_field] = str(request_id or uuid4())
    return value


def local_worker_qualification_path(task_family: LocalWorkerTask | None = None) -> str:
    """Build the canonical Neri qualification read without widening the API surface."""
    if task_family is None:
        return NERI_LOCAL_WORKER_QUALIFICATION_PATH
    return f"{NERI_LOCAL_WORKER_QUALIFICATION_PATH}?{urlencode({'task_family': task_family.value})}"


def local_worker_shadow_assignments_path(
    *,
    run_id: UUID | None = None,
    task_family: LocalWorkerTask | None = None,
) -> str:
    """Build the canonical filtered assignment read in a stable query order."""
    params = {
        "run_id": str(run_id) if run_id is not None else None,
        "task_family": task_family.value if task_family is not None else None,
    }
    query = urlencode({key: value for key, value in params.items() if value is not None})
    return f"{NERI_LOCAL_WORKER_SHADOW_ASSIGNMENTS_PATH}?{query}" if query else NERI_LOCAL_WORKER_SHADOW_ASSIGNMENTS_PATH


def local_worker_shadow_assignment_path(assignment_id: UUID) -> str:
    """Address one server-issued assignment identity exactly."""
    return f"{NERI_LOCAL_WORKER_SHADOW_ASSIGNMENTS_PATH}/{assignment_id}"


def bind_local_worker_run(payload: dict, run_id: UUID) -> dict:
    """Bind a reusable file payload to the positional run without silent contradiction."""
    supplied_run_id = payload.get("run_id")
    if supplied_run_id is not None:
        try:
            parsed_run_id = UUID(str(supplied_run_id))
        except (AttributeError, TypeError, ValueError):
            raise typer.BadParameter("JSON run_id must be a UUID when supplied") from None
        if parsed_run_id != run_id:
            raise typer.BadParameter("JSON run_id must match the positional run ID")
    return {**payload, "run_id": str(run_id)}


@worker_app.command("status")
@usage(
    surface="st.neri.worker.status",
    cmd="st neri worker status",
    when="verify the exact local Neri candidate runtime before assigning passive work",
    task_types=("security-research", "model-review"),
)
def local_worker_status() -> None:
    """Inspect the dedicated local runtime and promotion state."""
    output_json(
        agent_hub_request(
            "GET",
            NERI_LOCAL_WORKER_STATUS_PATH,
            tool_name="st neri worker status",
        )
    )


@worker_app.command("evaluate")
@usage(
    surface="st.neri.worker.evaluate",
    cmd="st neri worker evaluate --task-family FAMILY --file packet.json [--arm ARM]",
    when="delegate a sanitized passive evidence task to an evidence-qualified local worker",
    task_types=("security-research", "model-review"),
    precautions=(
        "Packet must contain only sanitized objective/evidence/constraints; output is an unreviewed draft",
    ),
)
def local_worker_evaluate(
    task_family: Annotated[LocalWorkerTask, typer.Option("--task-family")],
    file: Annotated[Path, typer.Option("--file", exists=True, dir_okay=False)],
    arm: Annotated[LocalWorkerArm, typer.Option("--arm")] = LocalWorkerArm.grounded_decomposition,
    reasoning_effort: Annotated[
        Literal["low", "medium", "xhigh"], typer.Option("--reasoning-effort")
    ] = "xhigh",
    max_output_tokens: Annotated[int, typer.Option("--max-output-tokens", min=256, max=8192)] = 4096,
) -> None:
    """Run one fallback-free, tool-free local analysis over a sanitized packet."""
    packet = read_object(file)
    payload = {
        "task_family": task_family.value,
        "harness_arm": arm.value,
        "packet": packet,
        "reasoning_effort": reasoning_effort,
        "max_output_tokens": max_output_tokens,
    }
    output_json(
        agent_hub_request(
            "POST",
            NERI_LOCAL_WORKER_EVALUATE_PATH,
            json=payload,
            tool_name="st neri worker evaluate",
            read_timeout_seconds=300.0,
        )
    )


@worker_app.command("benchmark")
@usage(
    surface="st.neri.worker.benchmark",
    cmd=(
        "st neri worker benchmark --split development|locked [--arm ARM] [--case-id ID] [--runs N] "
        "[--study-id ID --study-block N --study-case-position N --study-replacement N]"
    ),
    when="compare model-alone and model-plus-harness behavior before routing any task family",
    task_types=("security-research", "model-review"),
    precautions=(
        "Locked cases are promotion evidence; never tune the harness against their answers",
        "Study mode is frozen; attempts are durable one case at a time and outputs are unreviewed",
        "Study replacements preserve originals and label a full block; they never enable selective case reruns",
    ),
)
def local_worker_benchmark(
    split: Annotated[LocalWorkerSplit, typer.Option("--split")] = LocalWorkerSplit.development,
    arms: Annotated[list[LocalWorkerArm] | None, typer.Option("--arm")] = None,
    task_families: Annotated[list[LocalWorkerTask] | None, typer.Option("--task-family")] = None,
    case_ids: Annotated[list[str] | None, typer.Option("--case-id")] = None,
    runs: Annotated[int, typer.Option("--runs", min=1, max=3)] = 1,
    reasoning_effort: Annotated[
        Literal["low", "medium", "xhigh"], typer.Option("--reasoning-effort")
    ] = "xhigh",
    max_output_tokens: Annotated[int, typer.Option("--max-output-tokens", min=256, max=8192)] = 4096,
    no_persist: Annotated[bool, typer.Option("--no-persist")] = False,
    study_id: Annotated[str | None, typer.Option("--study-id")] = None,
    study_block: Annotated[int | None, typer.Option("--study-block", min=1, max=8)] = None,
    study_case_position: Annotated[
        int | None, typer.Option("--study-case-position", min=1, max=24)
    ] = None,
    study_replacement: Annotated[int, typer.Option("--study-replacement", min=0, max=3)] = 0,
) -> None:
    """Run the bounded harness-arm suite sequentially on the single local GPU."""
    study_binding = (study_id, study_block, study_case_position)
    if any(value is not None for value in study_binding) and not all(
        value is not None for value in study_binding
    ):
        raise typer.BadParameter(
            "--study-id, --study-block, and --study-case-position must be supplied together"
        )

    study_mode = study_id is not None
    if study_mode:
        if case_ids or task_families:
            raise typer.BadParameter("Study mode does not accept --case-id or --task-family")
        if runs != 1:
            raise typer.BadParameter("Study mode requires --runs 1")
        if arms is not None and arms != [LocalWorkerArm.role_checklist]:
            raise typer.BadParameter("Study mode accepts exactly one --arm role_checklist")
        if no_persist:
            raise typer.BadParameter("Study mode requires durable attempts; do not use --no-persist")
        selected_arms = [LocalWorkerArm.role_checklist]
    else:
        if study_replacement != 0:
            raise typer.BadParameter("--study-replacement requires a complete study binding")
        selected_arms = arms or list(LocalWorkerArm)

    payload = {
        "split": split.value,
        "harness_arms": [arm.value for arm in selected_arms],
        "task_families": [family.value for family in task_families] if task_families else None,
        "case_ids": case_ids,
        "runs_per_case": runs,
        "reasoning_effort": reasoning_effort,
        "max_output_tokens": max_output_tokens,
        "persist": not no_persist,
        "study_id": study_id,
        "study_block": study_block,
        "study_case_position": study_case_position,
        "study_replacement": study_replacement,
    }
    output_json(
        agent_hub_request(
            "POST",
            NERI_LOCAL_WORKER_BENCHMARK_PATH,
            json=payload,
            tool_name="st neri worker benchmark",
            read_timeout_seconds=3_600.0,
        )
    )


@worker_app.command("qualification")
@usage(
    surface="st.neri.worker.qualification",
    cmd="st neri worker qualification [--task-family FAMILY]",
    when="read the durable Neri promotion decision and evidence summary before assigning local work",
    task_types=("security-research", "model-review"),
    precautions=(
        "A held or missing family remains on its established frontier-model route",
        "Qualification state grants no target authority and does not make the local worker a reviewer",
    ),
)
def local_worker_qualification(task_family: LocalWorkerTask | None = None) -> None:
    """Read current qualification state from Neri, not the Agent Hub runtime."""
    request(local_worker_qualification_path(task_family))


@worker_app.command("qualify")
@usage(
    surface="st.neri.worker.qualify",
    cmd="st neri worker qualify --file decision.json [--id UUID]",
    when="append an independently reviewed qualification decision to Neri",
    task_types=("security-research", "model-review"),
    precautions=(
        "The JSON must cite the exact immutable benchmark and review evidence",
        "Decisions are append-only; a promotion never grants scope or submission authority",
    ),
)
def local_worker_qualify(
    file: Annotated[Path, typer.Option("--file", exists=True, dir_okay=False)],
    request_id: Annotated[UUID | None, typer.Option("--id")] = None,
) -> None:
    """Append one qualification decision while retaining its idempotency identity."""
    payload = read_object(
        file,
        request_id=request_id,
        identified=True,
        identity_field="request_id",
    )
    request(
        NERI_LOCAL_WORKER_QUALIFICATION_DECISIONS_PATH,
        payload,
        identity_field="request_id",
    )


@worker_app.command("shadow")
@usage(
    surface="st.neri.worker.shadow",
    cmd="st neri worker shadow <run-id> --file assignment.json [--id UUID]",
    when="save a passive local-worker shadow assignment before its draft exists",
    task_types=("security-research", "model-review"),
    precautions=(
        "Use only a sanitized referenced packet; the local worker gets no target, tool, memory, or network authority",
        "The positional run is authoritative and a contradictory JSON run_id is rejected",
    ),
)
def local_worker_shadow(
    run_id: UUID,
    file: Annotated[Path, typer.Option("--file", exists=True, dir_okay=False)],
    request_id: Annotated[UUID | None, typer.Option("--id")] = None,
) -> None:
    """Create one predeclared shadow assignment through Neri."""
    payload = read_object(
        file,
        request_id=request_id,
        identified=True,
        identity_field="request_id",
    )
    request(
        NERI_LOCAL_WORKER_SHADOW_ASSIGNMENTS_PATH,
        bind_local_worker_run(payload, run_id),
        identity_field="request_id",
        timeout=LOCAL_WORKER_SHADOW_TIMEOUT_SECONDS,
    )


@worker_app.command("assignments")
@usage(
    surface="st.neri.worker.assignments",
    cmd="st neri worker assignments [--run-id UUID] [--task-family FAMILY]",
    when="list saved local-worker shadow assignments and their current review disposition",
    task_types=("security-research", "model-review"),
    precautions=("Read-only; assignment IDs are server-issued and identify exact retained drafts",),
)
def local_worker_assignments(
    run_id: Annotated[UUID | None, typer.Option("--run-id")] = None,
    task_family: Annotated[LocalWorkerTask | None, typer.Option("--task-family")] = None,
) -> None:
    """List assignment projections, optionally narrowed to one run or family."""
    request(local_worker_shadow_assignments_path(run_id=run_id, task_family=task_family))


@worker_app.command("assignment")
@usage(
    surface="st.neri.worker.assignment",
    cmd="st neri worker assignment <assignment-id>",
    when="read one exact saved shadow assignment, draft provenance, and review disposition",
    task_types=("security-research", "model-review"),
    precautions=("Read-only; a retained draft remains inert until a frontier review accepts it",),
)
def local_worker_assignment(assignment_id: UUID) -> None:
    """Read one assignment using its server-issued identity without fallback."""
    request(local_worker_shadow_assignment_path(assignment_id))


@worker_app.command("review")
@usage(
    surface="st.neri.worker.review",
    cmd="st neri worker review <run-id> <assignment-id> --file review.json [--id UUID]",
    when="append a frontier review and exact corrections for one local-worker shadow draft",
    task_types=("security-research", "model-review"),
    precautions=(
        "The reviewer must verify every reference, supported inference, and uncertainty",
        "Reviews are immutable; acceptance records draft usefulness but grants no broad family promotion",
    ),
)
def local_worker_review(
    run_id: UUID,
    assignment_id: UUID,
    file: Annotated[Path, typer.Option("--file", exists=True, dir_okay=False)],
    request_id: Annotated[UUID | None, typer.Option("--id")] = None,
) -> None:
    """Append one immutable frontier review to an exact assignment."""
    payload = read_object(
        file,
        request_id=request_id,
        identified=True,
        identity_field="request_id",
    )
    request(
        f"{local_worker_shadow_assignment_path(assignment_id)}/reviews",
        bind_local_worker_run(payload, run_id),
        identity_field="request_id",
    )


def request_page(path: str, limit: int, cursor: str | None,
                 **filters: str | int | None) -> None:
    """Read one cursor page and preserve the server's continuation envelope."""
    params = {"limit": limit, "cursor": cursor, **filters}
    request(f"{path}?{urlencode({key: value for key, value in params.items() if value is not None})}")


def direction_notes_path(target_id: str, group_id: UUID | None = None) -> str:
    path = f"/api/targets/{quote(target_id, safe='')}"
    if group_id is not None:
        path += f"/investigations/{group_id}"
    return f"{path}/notes"


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
@usage(surface="st.neri.investigations", cmd="st neri investigations [--limit 40 --cursor TOKEN]", when="list saved Neri attempts using the legacy investigation contract", precautions=("read-only; IDs identify runs, not passive groups; next_cursor resumes the saved listing",), task_types=("neri",))
def investigations(limit: Annotated[int, typer.Option(min=1, max=100)] = 40, cursor: str | None = None) -> None:
    request_page("/api/investigations", limit, cursor)


@app.command()
@usage(surface="st.neri.create", cmd="st neri create --file investigation.json [--id UUID]", when="save an attempt with title, objective, scope and optional group membership", precautions=("passive creation; preserve group_id and role when supplied; JSON id or --id is retained, otherwise generated and printed; reuse only for identical content",), task_types=("neri",))
def create(file: Annotated[Path, typer.Option()], request_id: Annotated[UUID | None, typer.Option("--id")] = None) -> None:
    """Create a saved attempt through the legacy investigation API. --file - reads JSON from stdin."""
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
@usage(surface="st.neri.context", cmd="st neri context <investigation-id> [--after 0 --limit 40 --research-digest SHA256]", when="load compact local investigation state, evidence references and independently invalidated research guidance", precautions=("read-only local projection; retrieval is not proof of model consumption",), task_types=("neri", "security-research"))
def context(investigation_id: UUID, after: Annotated[int, typer.Option(min=0)] = 0,
            limit: Annotated[int, typer.Option(min=1, max=100)] = 40,
            research_digest: Annotated[str | None, typer.Option("--research-digest")] = None) -> None:
    params = {"after": after, "limit": limit, "research_digest": research_digest}
    request(f"/api/runs/{investigation_id}/context?{urlencode({key: value for key, value in params.items() if value is not None})}")


@research_app.command("catalogue")
@usage(surface="st.neri.research.catalogue", cmd="st neri research catalogue [--full]", when="read versioned research capability definitions", precautions=("definitions are assessment metadata; draft or active state is explicit and grants no target authority",), task_types=("neri", "security-research"))
def research_catalogue(full: bool = False) -> None:
    request(f"/api/research/capabilities?{urlencode({'compact': str(not full).lower()})}")


@research_app.command("show")
@usage(surface="st.neri.research.show", cmd="st neri research show <capability-id> [--version VERSION]", when="read one exact research capability revision", precautions=("read-only definition; required tools and prerequisites must still be established",), task_types=("neri", "security-research"))
def research_show(capability_id: str, version: str | None = None) -> None:
    path = f"/api/research/capabilities/{quote(capability_id, safe='')}"
    request(f"{path}?{urlencode({'version': version})}" if version else path)


@research_app.command("case-schema")
@usage(surface="st.neri.research.case-schema", cmd="st neri research case-schema <capability-id> [--version VERSION]", when="read only the inputs, controls and safety rules needed to prepare one capability case", precautions=("read-only method contract; it grants no target authority",), task_types=("neri", "security-research"))
def research_case_schema(capability_id: str, version: str | None = None) -> None:
    path = f"/api/research/case-schema/{quote(capability_id, safe='')}"
    request(f"{path}?{urlencode({'version': version})}" if version else path)


@research_app.command("matrix")
@usage(surface="st.neri.research.matrix", cmd="st neri research matrix", when="read technical evidence, implementation readiness and commercial outcomes", precautions=("projection is evidence-derived; inspect denominators, counterevidence and contamination",), task_types=("neri", "security-research"))
def research_matrix() -> None:
    request("/api/research/matrix")


@research_app.command("context")
@usage(surface="st.neri.research.context", cmd="st neri research context <investigation-id> [--previous-digest SHA256]", when="read independently invalidated research guidance for an investigation", precautions=("read-only guidance; unchanged means the exact research input digest did not change",), task_types=("neri", "security-research"))
def research_context(investigation_id: UUID,
                     previous_digest: Annotated[str | None, typer.Option("--previous-digest")] = None) -> None:
    path = f"/api/runs/{investigation_id}/research-context"
    request(f"{path}?{urlencode({'previous_digest': previous_digest})}" if previous_digest else path)


@research_app.command("recommend")
@usage(surface="st.neri.research.recommend", cmd="st neri research recommend <investigation-id>", when="read deterministic capability guidance", precautions=("does not call a model, write state, grant authority or perform target interaction",), task_types=("neri", "security-research"))
def research_recommend(investigation_id: UUID) -> None:
    request(f"/api/runs/{investigation_id}/research-recommendation")


@research_app.command("links")
@usage(surface="st.neri.research.links", cmd="st neri research links <investigation-id>", when="read immutable capability selections and evidence associations", precautions=("technical verdicts remain owned by exact reviews",), task_types=("neri", "security-research"))
def research_links(investigation_id: UUID) -> None:
    request(f"/api/runs/{investigation_id}/research-links")


@research_app.command("associate")
@usage(surface="st.neri.research.associate", cmd="st neri research associate <investigation-id> --file association.json [--id UUID]", when="save a prospective selection or exact reviewed evidence association", precautions=("JSON or stdin; selection must precede all result evidence for prospective credit; no verdict is accepted here",), task_types=("neri", "security-research"))
def research_associate(investigation_id: UUID, file: Annotated[Path, typer.Option()],
                       request_id: Annotated[UUID | None, typer.Option("--id")] = None) -> None:
    request(f"/api/runs/{investigation_id}/research-links",
            read_object(file, request_id=request_id, identified=True))


@research_app.command("prepare-case")
@usage(surface="st.neri.research.prepare-case", cmd="st neri research prepare-case <investigation-id> --file case.json", when="derive and save a prospective capability selection from a compact case description", precautions=("server derives target build, environment, required tools, safety digest and configuration digest; a needs_input response writes no selection",), task_types=("neri", "security-research"))
def research_prepare_case(
    investigation_id: UUID,
    file: Annotated[Path, typer.Option()],
) -> None:
    request(
        f"/api/runs/{investigation_id}/research-cases/prepare",
        read_object(file),
    )


@research_app.command("associate-case")
@usage(surface="st.neri.research.associate-case", cmd="st neri research associate-case <investigation-id> <selection-id> --file result.json", when="bind an exact report, review and controls to a prospective capability selection", precautions=("server copies immutable selection identity; the report and review remain authoritative for the verdict",), task_types=("neri", "security-research"))
def research_associate_case(
    investigation_id: UUID,
    selection_id: UUID,
    file: Annotated[Path, typer.Option()],
) -> None:
    request(
        f"/api/runs/{investigation_id}/research-cases/{selection_id}/associate",
        read_object(file),
    )


@research_app.command("invalidate-case")
@usage(surface="st.neri.research.invalidate-case", cmd="st neri research invalidate-case <investigation-id> <selection-id> --file closeout.json", when="close a prospective case whose tooling, evidence, scope or authorization became unsuitable", precautions=("does not create method counterevidence or erase saved history; use a reviewed result for actual method outcomes",), task_types=("neri", "security-research"))
def research_invalidate_case(
    investigation_id: UUID,
    selection_id: UUID,
    file: Annotated[Path, typer.Option()],
) -> None:
    request(
        f"/api/runs/{investigation_id}/research-cases/{selection_id}/invalidate",
        read_object(file),
    )


@research_app.command("snapshot")
@usage(surface="st.neri.research.snapshot", cmd="st neri research snapshot <investigation-id> --file snapshot.json [--id UUID]", when="save the exact deterministic recommendation and input digest", precautions=("server rejects stale input digests; saving does not dispatch work",), task_types=("neri", "security-research"))
def research_snapshot(investigation_id: UUID, file: Annotated[Path, typer.Option()],
                      request_id: Annotated[UUID | None, typer.Option("--id")] = None) -> None:
    request(f"/api/runs/{investigation_id}/research-recommendations",
            read_object(file, request_id=request_id, identified=True))


@research_app.command("snapshots")
@usage(surface="st.neri.research.snapshots", cmd="st neri research snapshots <investigation-id>", when="read saved deterministic recommendation history", precautions=("bounded read-only history; preserve input and source digests",), task_types=("neri", "security-research"))
def research_snapshots(investigation_id: UUID) -> None:
    request(f"/api/runs/{investigation_id}/research-recommendations")


@research_app.command("outcomes")
@usage(surface="st.neri.research.outcomes", cmd="st neri research outcomes <investigation-id>", when="read immutable commercial outcome history", precautions=("owner-confirmed program/report attribution only; technical support remains in reviews",), task_types=("neri", "security-research"))
def research_outcomes(investigation_id: UUID) -> None:
    request(f"/api/runs/{investigation_id}/commercial-outcomes")


@research_app.command("record-outcome")
@usage(surface="st.neri.research.record-outcome", cmd="st neri research record-outcome <investigation-id> --file outcome.json [--id UUID]", when="append an owner-confirmed commercial status", precautions=("requires exact report, finding and program binding revisions; never infers acceptance or payment",), task_types=("neri", "security-research"))
def research_record_outcome(investigation_id: UUID, file: Annotated[Path, typer.Option()],
                            request_id: Annotated[UUID | None, typer.Option("--id")] = None) -> None:
    request(f"/api/runs/{investigation_id}/commercial-outcomes",
            read_object(file, request_id=request_id, identified=True))


@research_app.command("cohorts")
@usage(
    surface="st.neri.research.cohorts",
    cmd="st neri research cohorts",
    when="read prospective fixed-denominator evaluation cohorts and economics",
    precautions=(
        "read-only; observed margin is not a statistical guarantee of future profit",
        "unknown cost or human time blocks a complete economics claim",
    ),
    task_types=("neri", "security-research"),
)
def research_cohorts() -> None:
    request("/api/research/evaluation-cohorts")


@research_app.command("cohort")
@usage(
    surface="st.neri.research.cohort",
    cmd="st neri research cohort <cohort-id>",
    when="inspect one exact cohort, case denominator, work receipts, closure and economics",
    precautions=("read-only; preserve exact program, capability and configuration identities",),
    task_types=("neri", "security-research"),
)
def research_cohort(cohort_id: UUID) -> None:
    request(f"/api/research/evaluation-cohorts/{cohort_id}")


@research_app.command("register-cohort")
@usage(
    surface="st.neri.research.cohort.register",
    cmd="st neri research register-cohort --file cohort.json [--id UUID]",
    when="freeze a prospective evaluation before result-generating work",
    precautions=(
        "requires exact current program scope, target build, capability/configuration and cases",
        "new opportunities or material configuration changes require a successor cohort",
    ),
    task_types=("neri", "security-research"),
)
def research_register_cohort(
    file: Annotated[Path, typer.Option()],
    request_id: Annotated[UUID | None, typer.Option("--id")] = None,
) -> None:
    request(
        "/api/research/evaluation-cohorts",
        read_object(file, request_id=request_id, identified=True),
    )


@research_app.command("close-cohort")
@usage(
    surface="st.neri.research.cohort.close",
    cmd="st neri research close-cohort <cohort-id> --file closure.json [--id UUID]",
    when="append the one outcome-independent closure assessment for a frozen cohort",
    precautions=(
        "must retain every registered case and frozen coverage item",
        "closure never authorizes submission or infers finding validity/payment",
    ),
    task_types=("neri", "security-research"),
)
def research_close_cohort(
    cohort_id: UUID,
    file: Annotated[Path, typer.Option()],
    request_id: Annotated[UUID | None, typer.Option("--id")] = None,
) -> None:
    request(
        f"/api/research/evaluation-cohorts/{cohort_id}/closure",
        read_object(file, request_id=request_id, identified=True),
    )


@research_app.command("finalize-accounting")
@usage(
    surface="st.neri.research.cohort.finalize_accounting",
    cmd="st neri research finalize-accounting <cohort-id> --file accounting.json [--id UUID]",
    when="freeze the commercial measurement cutoff after research and later handling finish",
    precautions=(
        "research closure must already exist; retain every registered case",
        "complete accounting requires exact final outcomes and known time/direct costs",
        "later payments or costs do not rewrite this immutable as-of measurement",
    ),
    task_types=("neri", "security-research"),
)
def research_finalize_accounting(
    cohort_id: UUID,
    file: Annotated[Path, typer.Option()],
    request_id: Annotated[UUID | None, typer.Option("--id")] = None,
) -> None:
    request(
        f"/api/research/evaluation-cohorts/{cohort_id}/accounting-closure",
        read_object(file, request_id=request_id, identified=True),
    )


@research_app.command("work")
@usage(
    surface="st.neri.research.work",
    cmd="st neri research work <investigation-id>",
    when="read immutable research work receipts for an investigation",
    precautions=("read-only; zero and unknown measurements have distinct meanings",),
    task_types=("neri", "security-research"),
)
def research_work(investigation_id: UUID) -> None:
    request(f"/api/runs/{investigation_id}/research-work-receipts")


@research_app.command("record-work")
@usage(
    surface="st.neri.research.work.record",
    cmd="st neri research record-work <investigation-id> --file receipt.json [--id UUID]",
    when="append measured agent, tool and owner work to a prospective cohort",
    precautions=(
        "requires exact cohort/case/configuration and evidence references",
        "never coerce missing time, token usage or direct cost to zero",
    ),
    task_types=("neri", "security-research"),
)
def research_record_work(
    investigation_id: UUID,
    file: Annotated[Path, typer.Option()],
    request_id: Annotated[UUID | None, typer.Option("--id")] = None,
) -> None:
    request(
        f"/api/runs/{investigation_id}/research-work-receipts",
        read_object(file, request_id=request_id, identified=True),
    )


@research_app.command("application")
@usage(
    surface="st.neri.research.application",
    cmd="st neri research application <investigation-id>",
    when="inspect the experimental passive application-evidence projection",
    precautions=(
        "read-only; static candidates do not establish reachability or vulnerability",
        "projection executes no JavaScript, follows no links and calls no model",
    ),
    task_types=("neri", "security-research"),
)
def research_application(investigation_id: UUID) -> None:
    request(f"/api/runs/{investigation_id}/application-evidence-projection")


@research_app.command("application-snapshots")
@usage(
    surface="st.neri.research.application.snapshots",
    cmd="st neri research application-snapshots <investigation-id>",
    when="read immutable application-evidence snapshot history",
    precautions=("read-only; preserve source and build identities",),
    task_types=("neri", "security-research"),
)
def research_application_snapshots(investigation_id: UUID) -> None:
    request(f"/api/runs/{investigation_id}/application-evidence-snapshots")


@research_app.command("snapshot-application")
@usage(
    surface="st.neri.research.application.snapshot",
    cmd=(
        "st neri research snapshot-application <investigation-id> "
        "--file snapshot.json [--id UUID]"
    ),
    when="freeze the current exact application-evidence source projection",
    precautions=(
        "server rejects a stale source digest",
        "saving a projection performs no target interaction and grants no capability credit",
    ),
    task_types=("neri", "security-research"),
)
def research_snapshot_application(
    investigation_id: UUID,
    file: Annotated[Path, typer.Option()],
    request_id: Annotated[UUID | None, typer.Option("--id")] = None,
) -> None:
    request(
        f"/api/runs/{investigation_id}/application-evidence-snapshots",
        read_object(file, request_id=request_id, identified=True),
    )


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
@usage(surface="st.neri.reports", cmd="st neri reports [--view investigations --target TARGET --limit 40 --cursor TOKEN]", when="list saved attempt reports or explicitly selected investigation reports", precautions=("read-only; default retains run-valued investigation_id; investigations view preserves group, run and exact report/review IDs; next_cursor resumes the listing",), task_types=("neri",))
def reports(limit: Annotated[int, typer.Option(min=1, max=100)] = 40, cursor: str | None = None,
            view: ReportView | None = None,
            target_id: Annotated[str | None, typer.Option("--target", "--target-id")] = None) -> None:
    if target_id is not None and view is None:
        raise typer.BadParameter("--target requires --view investigations")
    request_page("/api/reports", limit, cursor, view=view.value if view is not None else None,
                 target_id=target_id)


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


@report_severity_app.command("list")
@usage(surface="st.neri.report.severity.list", cmd="st neri report severity list <investigation-id> <revision-id> [--limit 40 --before-sequence N]", when="read immutable severity assessment history for an exact report revision", precautions=("read-only; preserve authority, scheme, native values and next_before_sequence; pass next_before_sequence to continue history",), task_types=("neri",))
def report_severity_list(investigation_id: UUID, revision_id: UUID,
                         limit: Annotated[int, typer.Option(min=1, max=100)] = 40,
                         before_sequence: Annotated[int | None, typer.Option(help="Continue from the returned next_before_sequence")] = None) -> None:
    request_page(f"/api/runs/{investigation_id}/reports/{revision_id}/severity-assessments", limit, None,
                 before_sequence=before_sequence)


@report_severity_app.command("show")
@usage(surface="st.neri.report.severity.show", cmd="st neri report severity show <investigation-id> <revision-id> <assessment-id>", when="read one immutable severity assessment for an exact report revision", precautions=("read-only; preserve the assessment identity and source; no fallback to another assessment or report revision",), task_types=("neri",))
def report_severity_show(investigation_id: UUID, revision_id: UUID, assessment_id: UUID) -> None:
    request(f"/api/runs/{investigation_id}/reports/{revision_id}/severity-assessments/{assessment_id}")


@report_severity_app.command("save")
@usage(surface="st.neri.report.severity.save", cmd="st neri report severity save <investigation-id> <revision-id> --file assessment.json [--id UUID]", when="save an attributed severity assessment for an exact report revision", precautions=("JSON object or stdin; preserve authority, scheme, native values, rationale and source; id is retained or generated and printed; server validates assessment fields; no automatic retry",), task_types=("neri",))
def report_severity_save(investigation_id: UUID, revision_id: UUID, file: Annotated[Path, typer.Option()],
                         request_id: Annotated[UUID | None, typer.Option("--id")] = None) -> None:
    request(f"/api/runs/{investigation_id}/reports/{revision_id}/severity-assessments",
            read_object(file, request_id=request_id, identified=True))


@report_app.command("download")
@usage(surface="st.neri.report.download", cmd="st neri report download <investigation-id> --output PATH [--revision UUID --review UUID]", when="download a saved report draft or exact report/review pair", precautions=("omit both selectors for the latest report; --review selects its bound report; supplying both pins the exact pair and mismatches are rejected; writes a new local file; no external submission",), task_types=("neri",))
def report_download(investigation_id: UUID, output: Annotated[Path, typer.Option()],
                    revision: Annotated[UUID | None, typer.Option(help="Download this exact report revision")] = None,
                    review: Annotated[UUID | None, typer.Option(help="Bind this exact review revision and its report")] = None) -> None:
    path = f"/api/runs/{investigation_id}/report-download"
    params = {key: str(value) for key, value in {"revision": revision, "review": review}.items() if value is not None}
    if params:
        path += f"?{urlencode(params)}"
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
@usage(surface="st.neri.target.list", cmd="st neri target list [--workspace --limit 40 --cursor TOKEN --search TEXT --filter FILTER]", when="list compact manifests or logical target workspace summaries", precautions=("read-only; default preserves registered manifest metadata; workspace uses filter-bound cursors and bounded summaries",), task_types=("neri",))
def target_list(workspace: bool = False, limit: Annotated[int, typer.Option(min=1, max=100)] = 40,
                cursor: str | None = None, search: str | None = None,
                workspace_filter: Annotated[WorkspaceFilter | None, typer.Option("--filter")] = None) -> None:
    if not workspace:
        if limit != 40 or cursor is not None or search is not None or workspace_filter is not None:
            raise typer.BadParameter("Pagination, search and filters require --workspace")
        request("/api/targets?compact=true")
        return
    params: dict[str, str | int] = {"view": "workspace", "limit": limit}
    if cursor is not None:
        params["cursor"] = cursor
    if search is not None:
        params["q"] = search
    if workspace_filter is not None:
        params["filter"] = workspace_filter.value
    request(f"/api/targets?{urlencode(params)}")


@target_app.command("show")
@usage(surface="st.neri.target.show", cmd="st neri target show <target-id> [--workspace]", when="read a target manifest or its compact workspace context", precautions=("read-only; default preserves the manifest and digest; read workspace context before exact attempts",), task_types=("neri",))
def target_show(target_id: str, workspace: bool = False) -> None:
    path = f"/api/targets/{quote(target_id, safe='')}"
    request(f"{path}?view=workspace" if workspace else path)


@group_app.command("list")
@usage(surface="st.neri.group.list", cmd="st neri group list <target-id> [--limit 40 --cursor TOKEN --search TEXT --class-key KEY --filter FILTER --include-empty]", when="list passive investigations for a logical target", precautions=("read-only; filters apply before pagination; preserve group IDs and section continuation cursors; empty historical groups are omitted unless requested",), task_types=("neri",))
def group_list(target_id: str, limit: Annotated[int, typer.Option(min=1, max=100)] = 40,
               cursor: str | None = None, search: str | None = None, class_key: str | None = None,
               workspace_filter: Annotated[WorkspaceFilter | None, typer.Option("--filter")] = None,
               include_empty: bool = False) -> None:
    request_page(f"/api/targets/{quote(target_id, safe='')}/investigations", limit, cursor,
                 q=search, class_key=class_key,
                 filter=workspace_filter.value if workspace_filter is not None else None,
                 include_empty="true" if include_empty else None)


@group_app.command("create")
@usage(surface="st.neri.group.create", cmd="st neri group create <target-id> --file group.json [--id UUID]", when="save a sustained investigation before assigning attempts", precautions=("passive grouping only; JSON id or --id identifies the group and is retained or generated; reuse only for identical content",), task_types=("neri",))
def group_create(target_id: str, file: Annotated[Path, typer.Option()],
                 request_id: Annotated[UUID | None, typer.Option("--id")] = None) -> None:
    request(f"/api/targets/{quote(target_id, safe='')}/investigations",
            read_object(file, request_id=request_id, identified=True))


@group_app.command("show")
@usage(surface="st.neri.group.show", cmd="st neri group show <target-id> <group-id> [--limit 40 --cursor TOKEN --report-limit 40 --report-cursor TOKEN]", when="read compact investigation context with paginated attempts and report history", precautions=("read-only; limit/cursor apply to attempts; report pagination is independent; preserve membership, selection and exact report/review IDs; no selection is a valid state",), task_types=("neri",))
def group_show(target_id: str, group_id: UUID,
               limit: Annotated[int, typer.Option("--limit", "--attempt-limit", min=1, max=100)] = 40,
               cursor: Annotated[str | None, typer.Option("--cursor", "--attempt-cursor")] = None,
               report_limit: Annotated[int, typer.Option(min=1, max=100)] = 40,
               report_cursor: str | None = None) -> None:
    params: dict[str, str | int] = {"attempt_limit": limit, "report_limit": report_limit}
    if cursor is not None:
        params["attempt_cursor"] = cursor
    if report_cursor is not None:
        params["report_cursor"] = report_cursor
    request(f"/api/targets/{quote(target_id, safe='')}/investigations/{group_id}?{urlencode(params)}")


@group_app.command("classify")
@usage(surface="st.neri.group.classify", cmd="st neri group classify <target-id> <group-id> --file classification.json [--id UUID]", when="revise an investigation's primary class metadata", precautions=("preserve expected_revision, class_key, class_label and reason; --id identifies mutation_id; conflicts are not retried",), task_types=("neri",))
def group_classify(target_id: str, group_id: UUID, file: Annotated[Path, typer.Option()],
                   request_id: Annotated[UUID | None, typer.Option("--id")] = None) -> None:
    request(f"/api/targets/{quote(target_id, safe='')}/investigations/{group_id}/classification",
            read_object(file, request_id=request_id, identified=True, identity_field="mutation_id"),
            method="PATCH", identity_field="mutation_id")


@group_app.command("select-report")
@usage(surface="st.neri.group.select-report", cmd="st neri group select-report <target-id> <group-id> --file selection.json [--id UUID]", when="select or explicitly clear an exact investigation report", precautions=("preserve expected_revision and reason; report_revision_id null clears selection; --id identifies mutation_id; newer reports never replace the selection automatically",), task_types=("neri",))
def group_select_report(target_id: str, group_id: UUID, file: Annotated[Path, typer.Option()],
                        request_id: Annotated[UUID | None, typer.Option("--id")] = None) -> None:
    request(f"/api/targets/{quote(target_id, safe='')}/investigations/{group_id}/report-selection",
            read_object(file, request_id=request_id, identified=True, identity_field="mutation_id"),
            identity_field="mutation_id")


@group_app.command("membership")
@usage(surface="st.neri.group.membership", cmd="st neri group membership <target-id> <group-id> --file membership.json [--id UUID]", when="assign or reassign an attempt to a passive investigation", precautions=("preserve run_id, expected_revision, role, exact predecessor/report references and reason; --id identifies mutation_id; clear a selected report before moving its owner run; no automatic retry",), task_types=("neri",))
def group_membership(target_id: str, group_id: UUID, file: Annotated[Path, typer.Option()],
                     request_id: Annotated[UUID | None, typer.Option("--id")] = None) -> None:
    request(f"/api/targets/{quote(target_id, safe='')}/investigations/{group_id}/memberships",
            read_object(file, request_id=request_id, identified=True, identity_field="mutation_id"),
            identity_field="mutation_id")


@target_app.command("register")
@usage(surface="st.neri.target.register", cmd="st neri target register --file target.json", when="register target metadata through Neri", precautions=("JSON object or stdin; records metadata only; API validates boundaries and version identity",), task_types=("neri",))
def target_register(file: Annotated[Path, typer.Option()]) -> None:
    request("/api/targets", read_object(file))


@target_app.command("status")
@usage(surface="st.neri.target.status", cmd="st neri target status <target-id> --file status.json", when="update a registered target's active status", precautions=("preserve manifest_digest, expected_status, status and reason; conflicts are not retried",), task_types=("neri",))
def target_status(target_id: str, file: Annotated[Path, typer.Option()]) -> None:
    request(f"/api/targets/{quote(target_id, safe='')}/status", read_object(file), method="PUT")


@target_notes_app.command("list")
@usage(surface="st.neri.target.notes.list", cmd="st neri target notes list <target-id> [--state saved|acknowledged|resolved --limit 40 --cursor TOKEN]", when="read a page of target direction notes", precautions=("read-only; previews may truncate bodies; preserve note IDs and next_cursor",), task_types=("neri",))
def target_notes_list(target_id: str, limit: Annotated[int, typer.Option(min=1, max=100)] = 40,
                      cursor: str | None = None, state: DirectionNoteState | None = None) -> None:
    request_page(direction_notes_path(target_id), limit, cursor, state=state.value if state else None)


@target_notes_app.command("add")
@usage(surface="st.neri.target.notes.add", cmd="st neri target notes add <target-id> --file note.json [--id UUID]", when="save target direction with exact saved context references", precautions=("JSON object or stdin; id is retained or generated and printed; preserve run/event/evidence/report/review references; passive notes do not imply delivery or execution",), task_types=("neri",))
def target_notes_add(target_id: str, file: Annotated[Path, typer.Option()],
                     request_id: Annotated[UUID | None, typer.Option("--id")] = None) -> None:
    request(direction_notes_path(target_id), read_object(file, request_id=request_id, identified=True))


@target_notes_app.command("show")
@usage(surface="st.neri.target.notes.show", cmd="st neri target notes show <target-id> <note-id>", when="read one target direction note with its full body and context", precautions=("read-only; uses the exact note ID without falling back to a preview",), task_types=("neri",))
def target_notes_show(target_id: str, note_id: UUID) -> None:
    request(f"{direction_notes_path(target_id)}/{note_id}")


@target_notes_app.command("history")
@usage(surface="st.neri.target.notes.history", cmd="st neri target notes history <target-id> <note-id> [--limit 40 --cursor TOKEN]", when="read immutable target note state transitions", precautions=("read-only; preserve state_revision_id, mutation_id, revision and next_cursor",), task_types=("neri",))
def target_notes_history(target_id: str, note_id: UUID,
                         limit: Annotated[int, typer.Option(min=1, max=100)] = 40,
                         cursor: str | None = None) -> None:
    request_page(f"{direction_notes_path(target_id)}/{note_id}/history", limit, cursor)


@target_notes_app.command("state")
@usage(surface="st.neri.target.notes.state", cmd="st neri target notes state <target-id> <note-id> --file state.json [--id UUID]", when="acknowledge, resolve or reopen target direction", precautions=("JSON includes expected_revision, state and reason; --id identifies mutation_id; retained or generated ID is printed; same-state writes and stale revisions are rejected; no automatic retry",), task_types=("neri",))
def target_notes_state(target_id: str, note_id: UUID, file: Annotated[Path, typer.Option()],
                       request_id: Annotated[UUID | None, typer.Option("--id")] = None) -> None:
    """Save a state revision. JSON state accepts saved, acknowledged or resolved."""
    request(f"{direction_notes_path(target_id)}/{note_id}/state",
            read_object(file, request_id=request_id, identified=True, identity_field="mutation_id"),
            identity_field="mutation_id")


@group_notes_app.command("list")
@usage(surface="st.neri.group.notes.list", cmd="st neri group notes list <target-id> <group-id> [--state saved|acknowledged|resolved --limit 40 --cursor TOKEN]", when="read a page of passive investigation direction notes", precautions=("read-only; group IDs are distinct from run IDs; previews may truncate bodies; preserve next_cursor",), task_types=("neri",))
def group_notes_list(target_id: str, group_id: UUID,
                     limit: Annotated[int, typer.Option(min=1, max=100)] = 40,
                     cursor: str | None = None, state: DirectionNoteState | None = None) -> None:
    request_page(direction_notes_path(target_id, group_id), limit, cursor,
                 state=state.value if state else None)


@group_notes_app.command("add")
@usage(surface="st.neri.group.notes.add", cmd="st neri group notes add <target-id> <group-id> --file note.json [--id UUID]", when="save passive investigation direction with exact saved context references", precautions=("JSON object or stdin; id is retained or generated and printed; context survives reassignment; passive notes do not imply delivery, execution or blockers",), task_types=("neri",))
def group_notes_add(target_id: str, group_id: UUID, file: Annotated[Path, typer.Option()],
                    request_id: Annotated[UUID | None, typer.Option("--id")] = None) -> None:
    request(direction_notes_path(target_id, group_id),
            read_object(file, request_id=request_id, identified=True))


@group_notes_app.command("show")
@usage(surface="st.neri.group.notes.show", cmd="st neri group notes show <target-id> <group-id> <note-id>", when="read one investigation direction note with its full body and context", precautions=("read-only; preserves the exact group, note and contextual record IDs",), task_types=("neri",))
def group_notes_show(target_id: str, group_id: UUID, note_id: UUID) -> None:
    request(f"{direction_notes_path(target_id, group_id)}/{note_id}")


@group_notes_app.command("history")
@usage(surface="st.neri.group.notes.history", cmd="st neri group notes history <target-id> <group-id> <note-id> [--limit 40 --cursor TOKEN]", when="read immutable investigation note state transitions", precautions=("read-only; preserve state_revision_id, mutation_id, revision and next_cursor",), task_types=("neri",))
def group_notes_history(target_id: str, group_id: UUID, note_id: UUID,
                        limit: Annotated[int, typer.Option(min=1, max=100)] = 40,
                        cursor: str | None = None) -> None:
    request_page(f"{direction_notes_path(target_id, group_id)}/{note_id}/history", limit, cursor)


@group_notes_app.command("state")
@usage(surface="st.neri.group.notes.state", cmd="st neri group notes state <target-id> <group-id> <note-id> --file state.json [--id UUID]", when="acknowledge, resolve or reopen investigation direction", precautions=("JSON includes expected_revision, state and reason; --id identifies mutation_id; retained or generated ID is printed; same-state writes and stale revisions are rejected; no automatic retry",), task_types=("neri",))
def group_notes_state(target_id: str, group_id: UUID, note_id: UUID, file: Annotated[Path, typer.Option()],
                      request_id: Annotated[UUID | None, typer.Option("--id")] = None) -> None:
    """Save a state revision. JSON state accepts saved, acknowledged or resolved."""
    request(f"{direction_notes_path(target_id, group_id)}/{note_id}/state",
            read_object(file, request_id=request_id, identified=True, identity_field="mutation_id"),
            identity_field="mutation_id")


@program_app.command("list")
@usage(surface="st.neri.program.list", cmd="st neri program list [--limit 40 --cursor TOKEN]", when="read saved disclosure program identities", precautions=("read-only; program identity is distinct from its immutable policy revisions; preserve next_cursor",), task_types=("neri",))
def program_list(limit: Annotated[int, typer.Option(min=1, max=100)] = 40,
                 cursor: str | None = None) -> None:
    request_page("/api/disclosure-programs", limit, cursor)


@program_app.command("create")
@usage(surface="st.neri.program.create", cmd="st neri program create --file program.json [--id UUID]", when="save a named disclosure program identity", precautions=("JSON object or stdin; id is retained or generated and printed; passive record only; policy is saved separately as a revision",), task_types=("neri",))
def program_create(file: Annotated[Path, typer.Option()],
                   request_id: Annotated[UUID | None, typer.Option("--id")] = None) -> None:
    request("/api/disclosure-programs", read_object(file, request_id=request_id, identified=True))


@program_app.command("show")
@usage(surface="st.neri.program.show", cmd="st neri program show <program-id>", when="read one disclosure program identity and its current revision reference", precautions=("read-only; fetch the exact policy revision separately",), task_types=("neri",))
def program_show(program_id: UUID) -> None:
    request(f"/api/disclosure-programs/{program_id}")


@program_app.command("revisions")
@usage(surface="st.neri.program.revisions", cmd="st neri program revisions <program-id> [--limit 40 --cursor TOKEN]", when="read a page of immutable disclosure policy revision summaries", precautions=("read-only; summaries omit policy_snapshot and may truncate summary; use revision for exact detail",), task_types=("neri",))
def program_revisions(program_id: UUID, limit: Annotated[int, typer.Option(min=1, max=100)] = 40,
                      cursor: str | None = None) -> None:
    request_page(f"/api/disclosure-programs/{program_id}/revisions", limit, cursor)


@program_app.command("revise")
@usage(surface="st.neri.program.revise", cmd="st neri program revise <program-id> --file revision.json [--id UUID]", when="save an immutable disclosure policy snapshot and sources", precautions=("JSON includes expected_revision, policy_snapshot and sources; verification fields record manually supplied facts; id is retained or generated and printed; policy revisions never rewrite bindings; no automatic retry",), task_types=("neri",))
def program_revise(program_id: UUID, file: Annotated[Path, typer.Option()],
                   request_id: Annotated[UUID | None, typer.Option("--id")] = None) -> None:
    request(f"/api/disclosure-programs/{program_id}/revisions",
            read_object(file, request_id=request_id, identified=True))


@program_app.command("revision")
@usage(surface="st.neri.program.revision", cmd="st neri program revision <program-id> <revision-id>", when="read one full immutable disclosure policy revision", precautions=("read-only; exact revision ID is preserved; no fallback to the current policy",), task_types=("neri",))
def program_revision(program_id: UUID, revision_id: UUID) -> None:
    """Read the full policy snapshot at one exact revision."""
    request(f"/api/disclosure-programs/{program_id}/revisions/{revision_id}")


@target_programs_app.command("list")
@usage(surface="st.neri.target.programs.list", cmd="st neri target programs list <target-id> [--manifest-id UUID --environment NAME --include-history --limit 40 --cursor TOKEN]", when="read current target program applicability bindings or their revision history", precautions=("read-only; manifest and environment filters are exact; list previews omit full policy; preserve binding and binding revision IDs",), task_types=("neri",))
def target_programs_list(target_id: str, limit: Annotated[int, typer.Option(min=1, max=100)] = 40,
                         cursor: str | None = None, manifest_id: UUID | None = None,
                         environment: str | None = None, include_history: bool = False) -> None:
    request_page(f"/api/targets/{quote(target_id, safe='')}/programs", limit, cursor,
                 manifest_id=str(manifest_id) if manifest_id is not None else None,
                 environment=environment, include_history="true" if include_history else None)


@target_programs_app.command("bind")
@usage(surface="st.neri.target.programs.bind", cmd="st neri target programs bind <target-id> --file binding.json [--id UUID]", when="save or revise exact target program applicability", precautions=("JSON preserves program_revision_id, manifest_id, environment and optional run/report/finding IDs; include expected_revision; target_scope_status and eligibility_status are separate; id identifies the immutable binding revision and is retained or generated; no automatic retry",), task_types=("neri",))
def target_programs_bind(target_id: str, file: Annotated[Path, typer.Option()],
                         request_id: Annotated[UUID | None, typer.Option("--id")] = None) -> None:
    request(f"/api/targets/{quote(target_id, safe='')}/programs",
            read_object(file, request_id=request_id, identified=True))


@target_programs_app.command("show")
@usage(surface="st.neri.target.programs.show", cmd="st neri target programs show <target-id> <binding-id> [--revision-id UUID]", when="read full current or exact immutable binding detail and its pinned policy", precautions=("read-only; --revision-id pins an immutable binding revision; binding identity is distinct from its revision ID; no fallback",), task_types=("neri",))
def target_programs_show(target_id: str, binding_id: UUID, revision_id: UUID | None = None) -> None:
    path = f"/api/targets/{quote(target_id, safe='')}/programs/{binding_id}"
    if revision_id is not None:
        path += f"?{urlencode({'revision_id': str(revision_id)})}"
    request(path)


@target_programs_app.command("history")
@usage(surface="st.neri.target.programs.history", cmd="st neri target programs history <target-id> <binding-id> [--limit 40 --cursor TOKEN]", when="read immutable revisions of one exact applicability binding", precautions=("read-only; history omits full policy; preserve supersedes_revision_id and next_cursor",), task_types=("neri",))
def target_programs_history(target_id: str, binding_id: UUID,
                            limit: Annotated[int, typer.Option(min=1, max=100)] = 40,
                            cursor: str | None = None) -> None:
    request_page(f"/api/targets/{quote(target_id, safe='')}/programs/{binding_id}/history", limit, cursor)
