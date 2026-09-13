"""Agent-facing Learn-o-Tron operations; the project API owns all learning state."""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from pathlib import Path
from typing import Annotated, Any
from urllib.parse import quote, urlencode
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

import typer

from .._client_base import APIError
from .._project_client import ProjectApi, ProjectApiClient, ProjectApiConnectError, resolve_api_url
from ..client import STClient
from ..config import set_project_override
from ..lib.usage import usage
from ..output import output_json
from .learn_pty import TranscriptSpool, TranscriptSpoolBusy, run_terminal

app = typer.Typer(help="Learn, research and review through Learn-o-Tron's canonical API")
pwn_app = typer.Typer(
    help="Sync the public pwn.college self-study catalog, then choose an activity"
)
session_app = typer.Typer(
    help="Start in native SSH, close to pause, resume later, then finish with learner evidence"
)
improvements_app = typer.Typer(
    help="Capture session lessons, triage them, then explicitly promote accepted work"
)
app.add_typer(pwn_app, name="pwn")
app.add_typer(session_app, name="session")
app.add_typer(improvements_app, name="improvements")
API = ProjectApi(project_id="learn-o-tron", env_var="ST_LEARN_API_URL", default_url="http://127.0.0.1:8018")


_ACTIVITY_PATH = re.compile(r"/dojo/[A-Za-z0-9._-]+/[A-Za-z0-9._-]+/[A-Za-z0-9._-]+")
_CURRENT_ACTIVITY_COMMAND = (
    "test -d /challenge && "
    'test -n "$(find /challenge -mindepth 1 -maxdepth 1 -print -quit 2>/dev/null)" && '
    "python3 -c 'import json, os, urllib.request; "
    'headers={"Authorization": "Bearer " + os.environ["DOJO_AUTH_TOKEN"]}; '
    'host=os.environ.get("DOJO_HOST"); '
    'headers.update({"Host": host} if host else {}); '
    'request=urllib.request.Request("http://pwn.college:80/pwncollege_api/v1/docker", headers=headers); '
    "data=json.load(urllib.request.urlopen(request, timeout=5)); "
    'print("/dojo/{dojo}/{module}/{challenge}".format(**data))\''
)


class LearnRequestError(Exception):
    def __init__(self, error: str, detail: str, exit_code: int, status_code: int | None = None):
        super().__init__(detail)
        self.error = error
        self.detail = detail
        self.exit_code = exit_code
        self.status_code = status_code


class OperatorLeaseLost(Exception):
    """The live terminal no longer owns its study-session operator lease."""


def request_data(
    path: str,
    body: dict | None = None,
    method: str = "POST",
    *,
    timeout: float = 30.0,
):
    try:
        with ProjectApiClient(resolve_api_url(API).url, timeout=timeout) as client:
            if body is None:
                result = client.get(path)
            elif method == "PATCH":
                result = client.patch(path, json_body=body)
            elif method == "PUT":
                result = client.put(path, json_body=body)
            else:
                result = client.post(path, json_body=body)
        return result
    except ProjectApiConnectError as exc:
        raise LearnRequestError(
            "learn_unreachable",
            "Check st service status learn-o-tron or ST_LEARN_API_URL",
            2,
        ) from exc
    except APIError as exc:
        raise LearnRequestError("learn_api_error", str(exc.detail), 1, exc.status_code) from exc


def request(path: str, body: dict | None = None, method: str = "POST"):
    try:
        result = request_data(path, body, method)
        output_json({"ok": True, "schema_version": 2, "data": result})
        return result
    except LearnRequestError as exc:
        payload = {"ok": False, "error": exc.error, "detail": exc.detail}
        if exc.error == "learn_unreachable":
            payload["hint"] = exc.detail
        output_json(payload)
        raise typer.Exit(exc.exit_code) from None


def require_data(path: str, body: dict | None = None, method: str = "POST"):
    try:
        return request_data(path, body, method)
    except LearnRequestError as exc:
        output_json({"ok": False, "error": exc.error, "detail": exc.detail})
        raise typer.Exit(exc.exit_code) from None


def read_file(path: Path):
    try:
        value = json.loads(sys.stdin.read() if str(path) == "-" else path.read_text())
        if not isinstance(value, dict):
            raise ValueError("Expected a JSON object")
        return value
    except (OSError, ValueError) as exc:
        output_json({"ok": False, "error": "invalid_input", "detail": str(exc)})
        raise typer.Exit(3) from None


@app.command()
@usage(surface="st.learn.capabilities", cmd="st learn capabilities", when="discover learning API payloads and terminal workflow", task_types=("learning", "learn-o-tron"), tier="reference")
def capabilities():
    request("/api/capabilities")


class Role(StrEnum):
    researcher = "researcher"
    planner = "planner"
    tutor = "tutor"
    reviewer = "reviewer"


@app.command()
@usage(surface="st.learn.context", cmd="st learn context [--role tutor|researcher|planner|reviewer]", when="resume learning or load canonical Agent Hub role instructions", precautions=("default is compact learning context; role instructions are supplied, not proof of model consumption",), task_types=("learning", "learn-o-tron"), tier="reference")
def context(role: Role | None = None):
    request(f"/api/context/{role.value}" if role else "/api/context")


@app.command()
@usage(surface="st.learn.profile", cmd="st learn profile [--file profile.json]", when="inspect or correct learner goals, experience and preferences", precautions=("updates require current revision; preserve source provenance",), task_types=("learning", "learn-o-tron"), tier="reference")
def profile(file: Annotated[Path | None, typer.Option()] = None):
    request("/api/profile", read_file(file) if file else None, "PATCH")


@app.command()
@usage(surface="st.learn.paths", cmd="st learn paths", when="list saved learning paths", task_types=("learning", "learn-o-tron"), tier="reference")
def paths():
    request("/api/records?kind=curriculum")


@app.command()
@usage(surface="st.learn.show", cmd="st learn show <record-id>", when="read curriculum, recommendation or lab details on demand", task_types=("learning", "learn-o-tron"), tier="reference")
def show(record_id: str):
    from urllib.parse import quote
    request(f"/api/records/{quote(record_id, safe='')}")


@app.command()
@usage(surface="st.learn.focus", cmd="st learn focus --path ID --lesson ID [--step 0]", when="save the shared PWA and terminal resume position", task_types=("learning", "learn-o-tron"), tier="reference")
def focus(path: Annotated[str, typer.Option()], lesson: Annotated[str, typer.Option()], step: int = 0):
    request("/api/focus", {"path_id": path, "lesson_id": lesson, "step": step}, "PUT")


class WorkKind(StrEnum):
    recommend = "recommend"
    curriculum = "curriculum"
    tutor = "tutor"
    review = "review"
    audio = "audio"
    content_review = "content-review"
    prediction = "prediction"


@app.command()
@usage(surface="st.learn.work", cmd="st learn work recommend|curriculum|tutor|review|audio|content-review|prediction [--message TEXT] [--record ID] [--lesson ID] [--step N] [--explanation-seen] [--command-id UUID] [--context-file FILE]", when="request subscription-only learning work, prediction feedback, independent draft review or local audio", precautions=("returns a durable job; inspect status before retrying; preserve command ID only for identical payloads; review record is an attempt ID; content-review record is a draft ID; prediction needs the actual learner answer and zero-based step; never invent a learner response",), task_types=("learning", "learn-o-tron"), tier="reference")
def work(kind: WorkKind, message: str = "", record: str = "", lesson: str = "", command_id: UUID | None = None, step: int | None = None, explanation_seen: bool = False, context_file: Annotated[Path | None, typer.Option(help="Structured learning-check section, saved attempt or current draft; use capabilities for its schema.")] = None):
    payload = {"command_id": str(command_id or uuid4()), "kind": kind.value, "message": message,
               "record_id": record, "lesson_id": lesson, "step": step, "actor": "agent"}
    if kind == WorkKind.prediction:
        payload["explanation_seen"] = explanation_seen
    if context_file:
        if kind != WorkKind.tutor:
            raise typer.BadParameter('--context-file is for tutor discussion')
        payload["learning_check"] = read_file(context_file)
    request("/api/jobs", payload)


@app.command('check')
@usage(surface="st.learn.check", cmd="st learn check --path ID --lesson ID [--attempt ID]", when="resume saved learning-check answers and their automatic Rowan review", precautions=("default is the latest submission; saving an attempt starts a review atomically; a queued review is not completion",), task_types=("learning", "learn-o-tron"), tier="reference")
def learning_check(path: Annotated[str, typer.Option()], lesson: Annotated[str, typer.Option()], attempt: str = ''):
    from urllib.parse import quote
    query = f'?attempt_id={quote(attempt, safe="")}' if attempt else ''
    request(f"/api/paths/{quote(path, safe='')}/lessons/{quote(lesson, safe='')}/learning-check{query}")


@app.command()
@usage(surface="st.learn.discussion", cmd="st learn discussion --path ID --lesson ID --attempt ID | --challenge ID", when="read saved questions, critiques and Rowan replies attached to a learning check", precautions=("send actual learner text with work tutor --context-file; do not fabricate learner messages or evidence",), task_types=("learning", "learn-o-tron"), tier="reference")
def discussion(path: Annotated[str, typer.Option()], lesson: Annotated[str, typer.Option()], attempt: str = '', challenge: str = ''):
    from urllib.parse import quote, urlencode
    if bool(attempt) == bool(challenge):
        raise typer.BadParameter('Choose exactly one of --attempt or --challenge')
    query = urlencode({'attempt_id': attempt} if attempt else {'challenge_id': challenge})
    request(f"/api/paths/{quote(path, safe='')}/lessons/{quote(lesson, safe='')}/check-discussion?{query}")


@app.command()
@usage(surface="st.learn.predictions", cmd="st learn predictions --path ID --lesson ID --step N", when="read saved prediction answers, Rowan feedback and queued checks for a lesson step", precautions=("latest 20 requests; zero-based step; formative feedback is not mastery evidence",), task_types=("learning", "learn-o-tron"), tier="reference")
def predictions(path: Annotated[str, typer.Option()], lesson: Annotated[str, typer.Option()], step: Annotated[int, typer.Option(min=0, max=6)]):
    from urllib.parse import quote
    request(f"/api/paths/{quote(path, safe='')}/lessons/{quote(lesson, safe='')}/steps/{step}/predictions")


@app.command()
@usage(surface="st.learn.status", cmd="st learn status [--job-id UUID]", when="read job completion or full learning state", precautions=("queued/running is not completion; full state is larger than st learn context",), task_types=("learning", "learn-o-tron"), tier="reference")
def status(job_id: UUID | None = None):
    request(f"/api/jobs/{job_id}" if job_id else "/api/state")


@app.command()
@usage(surface="st.learn.stop", cmd="st learn stop JOB_ID", when="cancel queued work or suppress publication of an in-flight result", precautions=("already submitted provider work may finish; native harness processes remain under harness control",), task_types=("learning", "learn-o-tron"), tier="reference")
def stop(job_id: UUID):
    request(f"/api/jobs/{job_id}/stop", {})


@app.command()
@usage(surface="st.learn.attempt", cmd="st learn attempt --path ID --lesson ID --file attempt.json", when="record a learner's actual explanation, check answers, time and assistance", precautions=("load capabilities first; never label agent-written solutions independent; command ID must be stable for a retry",), task_types=("learning", "learn-o-tron"), tier="reference")
def attempt(path: Annotated[str, typer.Option()], lesson: Annotated[str, typer.Option()], file: Annotated[Path, typer.Option()]):
    from urllib.parse import quote
    request(f"/api/paths/{quote(path, safe='')}/lessons/{quote(lesson, safe='')}/attempts", read_file(file))


@app.command()
@usage(surface="st.learn.lab", cmd="st learn lab --path ID --lesson ID [--file action.json]", when="inspect lab evidence or perform a controlled lab action", precautions=("use capabilities payload; CLI submissions are attributed to agent; no arbitrary host or network execution",), task_types=("learning", "learn-o-tron"), tier="reference")
def lab(path: Annotated[str, typer.Option()], lesson: Annotated[str, typer.Option()], file: Annotated[Path | None, typer.Option()] = None):
    from urllib.parse import quote
    payload = read_file(file) if file else None
    if payload:
        payload["actor"] = "agent"
    request(f"/api/paths/{quote(path, safe='')}/lessons/{quote(lesson, safe='')}/lab", payload)


@app.command()
@usage(surface="st.learn.instructor", cmd="st learn instructor", when="load Rowan's shared teaching voice and evidence-based method", task_types=("learning", "learn-o-tron"), tier="reference")
def instructor():
    request("/api/instructor")


@app.command()
@usage(surface="st.learn.roadmap", cmd="st learn roadmap [--file roadmap.json]", when="read or revise the shared goals, milestones and optional certifications", precautions=("updates require the read revision and a reason; completed milestones need evidence; preserve unrelated goals",), task_types=("learning", "learn-o-tron"), tier="reference")
def roadmap(file: Annotated[Path | None, typer.Option()] = None):
    payload = read_file(file) if file else None
    if payload is not None:
        payload["actor"] = "agent"
    request("/api/roadmap", payload, "PUT")


@app.command()
@usage(surface="st.learn.conversation", cmd="st learn conversation [--before ID] [--file exchange.json]", when="read saved exchanges or preserve an actual native tutor conversation", precautions=("store actual user and instructor messages; no invented learner statements; this does not create mastery evidence",), task_types=("learning", "learn-o-tron"), tier="reference")
def conversation(before: str = "", file: Annotated[Path | None, typer.Option()] = None):
    from urllib.parse import quote
    request("/api/conversation" + (f"?before={quote(before, safe='')}" if before and not file else ""), read_file(file) if file else None)


@app.command()
@usage(surface="st.learn.authoring", cmd="st learn authoring", when="load the canonical source-to-publication workflow, schemas and supported labs", precautions=("read before authoring; primary-source evidence and independent editorial review precede publication",), task_types=("learning", "learn-o-tron"), tier="reference")
def authoring():
    request("/api/authoring")


@app.command()
@usage(surface="st.learn.source", cmd="st learn source [--file source.json]", when="inspect or preserve an actually retrieved primary-source excerpt", precautions=("read the original first; do not manufacture captures or claim the timestamp proves retrieval",), task_types=("learning", "learn-o-tron"), tier="reference")
def source(file: Annotated[Path | None, typer.Option()] = None):
    request("/api/content/sources", read_file(file) if file else None)


@app.command()
@usage(surface="st.learn.draft", cmd="st learn draft --file draft.json | --id ID", when="save an immutable curriculum draft or inspect checks, sources and review", precautions=("revisions use a new command ID; reading a draft includes answer keys intended for authors",), task_types=("learning", "learn-o-tron"), tier="reference")
def draft(file: Annotated[Path | None, typer.Option()] = None, id: Annotated[str | None, typer.Option()] = None):
    from urllib.parse import quote
    if bool(file) == bool(id):
        raise typer.BadParameter("Choose exactly one of --file or --id")
    request(f"/api/content/drafts/{quote(id, safe='')}" if id else "/api/content/drafts", read_file(file) if file else None)


@app.command()
@usage(surface="st.learn.publish", cmd="st learn publish DRAFT_ID", when="publish the exact draft after passing checks and independent content review", precautions=("server rejects unreviewed, changed or blocked drafts; success is idempotent",), task_types=("learning", "learn-o-tron"), tier="reference")
def publish(draft_id: str):
    from urllib.parse import quote
    request(f"/api/content/drafts/{quote(draft_id, safe='')}/publish", {})


@app.command()
@usage(surface="st.learn.challenge", cmd="st learn challenge --path ID --lesson ID", when="load the current question variant and challenge ID before a learning check", precautions=("answer keys are withheld; stale challenges are rejected; finite question sets eventually repeat",), task_types=("learning", "learn-o-tron"), tier="reference")
def challenge(path: Annotated[str, typer.Option()], lesson: Annotated[str, typer.Option()]):
    from urllib.parse import quote
    request(f"/api/paths/{quote(path, safe='')}/lessons/{quote(lesson, safe='')}/challenge")


@app.command()
@usage(surface="st.learn.agent_lab", cmd="st learn agent-lab --path ID --lesson ID --file action.json", when="operate the local agent permission simulator and retain attributed evidence", precautions=("CLI actions are agent-assisted; deterministic policy test only, no live model or external effects",), task_types=("learning", "learn-o-tron"), tier="reference")
def agent_lab(path: Annotated[str, typer.Option()], lesson: Annotated[str, typer.Option()], file: Annotated[Path, typer.Option()]):
    from urllib.parse import quote
    payload = read_file(file)
    payload["actor"] = "agent"
    request(f"/api/paths/{quote(path, safe='')}/lessons/{quote(lesson, safe='')}/agent-lab", payload)


def _native_harness(value: str) -> str:
    if value:
        return value
    configured = os.environ.get("ST_LEARN_HARNESS", "").strip()
    if configured:
        return configured
    if os.environ.get("CLAUDECODE"):
        base = "claude"
    elif os.environ.get("CODEX_THREAD_ID") or os.environ.get("CURSOR_TRACE_ID"):
        base = "codex"
    elif os.environ.get("PI_CODING_AGENT_DIR"):
        base = "pi"
    else:
        base = "terminal"
    native_session_id = _native_session_id()
    if not native_session_id:
        return base
    suffix = hashlib.sha256(native_session_id.encode()).hexdigest()[:12]
    return f"{base}-{suffix}"


def _native_session_id() -> str:
    return next(
        (
            os.environ[name]
            for name in (
                "AICO_SESSION_ID",
                "A_TERM_SESSION_ID",
                "CODEX_THREAD_ID",
                "CURSOR_TRACE_ID",
                "CLAUDE_SESSION_ID",
                "PI_SESSION_ID",
            )
            if os.environ.get(name)
        ),
        "",
    )


def _prepare_study_operator(
    study: dict[str, Any],
    harness: str,
    agent_name: str,
    model: str,
) -> dict[str, Any]:
    participants = study["data"].get("participants", [])
    if not any(item.get("harness") == harness for item in participants):
        study = require_data(
            _study_url(study["id"], "/participants"),
            {
                "command_id": str(uuid4()),
                "expected_revision": study["revision"],
                "harness": harness,
                "agent_name": agent_name,
                "model": model,
                "native_session_id": _native_session_id(),
                "actor": "agent",
            },
        )
    study = require_data(
        _study_url(study["id"], "/operator"),
        {
            "command_id": str(uuid4()),
            "expected_revision": study["revision"],
            "harness": harness,
        },
    )
    if study["data"]["status"] == "paused":
        study = _session_action(study, "resume", harness, note="Native harness resumed the session")
    return study


def _study_url(session_id: str, suffix: str = "") -> str:
    return f"/api/training/sessions/{quote(session_id, safe='')}{suffix}"


def _ssh(
    arguments: list[str],
    *,
    quiet: bool = False,
    capture: bool = False,
) -> subprocess.CompletedProcess[str]:
    command = [
        "ssh",
        "-o",
        "BatchMode=yes",
        "-o",
        "ConnectTimeout=10",
        "pwn-college",
        *arguments,
    ]
    try:
        return subprocess.run(
            command,
            check=False,
            text=True,
            stdin=subprocess.DEVNULL if quiet else None,
            stdout=subprocess.PIPE if capture else subprocess.DEVNULL if quiet else None,
            stderr=subprocess.PIPE if capture else subprocess.DEVNULL if quiet else None,
        )
    except FileNotFoundError:
        output_json({"ok": False, "error": "ssh_unavailable", "detail": "OpenSSH was not found"})
        raise typer.Exit(2) from None


def _upstream_path(study: dict[str, Any]) -> str:
    path = str(study["data"]["activity"]["upstream_path"])
    if not _ACTIVITY_PATH.fullmatch(path):
        raise typer.BadParameter("The synchronized provider path is not safe for SSH execution")
    return path


def _remote_activity_path() -> str:
    result = _ssh([_CURRENT_ACTIVITY_COMMAND], capture=True)
    candidate = (result.stdout or "").strip()
    if result.returncode != 0 or not _ACTIVITY_PATH.fullmatch(candidate):
        return ""
    return candidate


def _session_action(study: dict[str, Any], action: str, harness: str, **values: Any) -> dict[str, Any]:
    return require_data(
        _study_url(study["id"], "/actions"),
        {
            "command_id": str(uuid4()),
            "expected_revision": study["revision"],
            "action": action,
            "harness": harness,
            **values,
        },
    )


def _lease_safe_for_retry(study: dict[str, Any], seconds: int) -> bool:
    try:
        lease_until = datetime.fromisoformat(study["data"]["operator_lease_until"])
        if lease_until.tzinfo is None:
            lease_until = lease_until.replace(tzinfo=UTC)
        return lease_until > datetime.now(UTC) + timedelta(seconds=seconds)
    except (KeyError, TypeError, ValueError):
        return False


def _open_study_terminal(study: dict[str, Any], harness: str):
    path = _upstream_path(study)
    try:
        spool = TranscriptSpool(
            study["id"],
            harness,
            int(study["transcript"]["last_sequence"]) + 1,
        )
    except TranscriptSpoolBusy as exc:
        output_json({"ok": False, "error": "study_terminal_busy", "detail": str(exc)})
        raise typer.Exit(1) from None

    warned = False
    status = 1
    try:
        current_path = _remote_activity_path()
        if current_path != path:
            note = (
                f"Remote workspace belongs to {current_path}"
                if current_path
                else "No active remote challenge was observed"
            )
            study = _session_action(study, "remote_expired", harness, note=note)
            started = _ssh(["dojo", "start", path])
            if started.returncode != 0:
                output_json(
                    {
                        "ok": False,
                        "error": "pwn_start_failed",
                        "detail": f"dojo start exited {started.returncode}",
                    }
                )
                raise typer.Exit(started.returncode)
            study = _session_action(
                study,
                "remote_started",
                harness,
                note="Official dojo CLI started the selected activity",
            )
        elif study["data"].get("remote_state") != "running":
            study = _session_action(
                study,
                "remote_started",
                harness,
                note="Selected challenge identity verified over SSH",
            )

        def upload(record: dict):
            payload = {key: value for key, value in record.items() if key != "session_id"}
            request_data(_study_url(study["id"], "/transcript"), payload)

        if not spool.drain(upload):
            typer.echo(
                "WARN: A sanitized transcript spool is pending; upload will retry when the terminal closes.",
                err=True,
            )
            warned = True

        def save_sanitized(text: str):
            spool.append(text)

        def heartbeat():
            nonlocal study, warned
            try:
                fresh = request_data(_study_url(study["id"]), timeout=3)
                if (
                    fresh["data"].get("status") != "active"
                    or fresh["data"].get("operator_harness") != harness
                ):
                    raise OperatorLeaseLost("The session is no longer active for this harness")
                study = request_data(
                    _study_url(study["id"], "/actions"),
                    {
                        "command_id": str(uuid4()),
                        "expected_revision": fresh["revision"],
                        "action": "heartbeat",
                        "harness": harness,
                        "note": "Native PTY is active",
                    },
                    timeout=3,
                )
            except LearnRequestError as exc:
                if exc.status_code == 409:
                    try:
                        fresh = request_data(_study_url(study["id"]), timeout=3)
                        if (
                            fresh["data"].get("operator_harness") != harness
                            or fresh["data"].get("status") != "active"
                        ):
                            raise OperatorLeaseLost(exc.detail)
                        study = request_data(
                            _study_url(study["id"], "/operator"),
                            {
                                "command_id": str(uuid4()),
                                "expected_revision": fresh["revision"],
                                "harness": harness,
                            },
                            timeout=3,
                        )
                        return
                    except LearnRequestError as reacquire_error:
                        raise OperatorLeaseLost(reacquire_error.detail) from reacquire_error
                if exc.status_code is not None and exc.status_code < 500:
                    raise OperatorLeaseLost(exc.detail) from exc
                if not _lease_safe_for_retry(study, 35):
                    raise OperatorLeaseLost(
                        "The operator lease could not be renewed before its local deadline"
                    ) from exc
                if not warned:
                    typer.echo(
                        "WARN: Session heartbeat failed; the terminal remains active and will retry.",
                        err=True,
                    )
                    warned = True

        try:
            status = run_terminal(
                [
                    "ssh",
                    "-o",
                    "BatchMode=yes",
                    "-o",
                    "ServerAliveInterval=30",
                    "-o",
                    "ServerAliveCountMax=3",
                    "pwn-college",
                ],
                save_sanitized,
                heartbeat,
                heartbeat_seconds=30,
            )
        except OperatorLeaseLost as exc:
            output_json(
                {
                    "ok": False,
                    "error": "operator_lease_lost",
                    "detail": f"The study terminal stopped: {exc}",
                }
            )
            raise typer.Exit(1) from None
        if not spool.drain(upload):
            typer.echo(
                "WARN: Sanitized transcript chunks remain in the private spool for the next resume.",
                err=True,
            )
    finally:
        spool.close()

    try:
        fresh = request_data(_study_url(study["id"]))
        if (
            fresh["data"]["status"] == "active"
            and fresh["data"]["operator_harness"] == harness
        ):
            fresh = request_data(
                _study_url(study["id"], "/actions"),
                {
                    "command_id": str(uuid4()),
                    "expected_revision": fresh["revision"],
                    "action": "pause",
                    "harness": harness,
                    "note": "Native SSH session closed",
                },
            )
        output_json({"ok": status == 0, "schema_version": 2, "data": fresh, "ssh_exit_code": status})
    except LearnRequestError:
        typer.echo("WARN: The sanitized spool and remote workspace were left recoverable; session status could not be updated.", err=True)
    if status:
        raise typer.Exit(status)


@pwn_app.command("sync")
@usage(
    surface="st.learn.pwn.sync",
    cmd="st learn pwn sync [--full] [--username NAME]",
    when="synchronize the supported public pwn.college self-study catalog and solve observations",
    precautions=("read-only provider calls; lifecycle changes use the official SSH dojo CLI",),
    task_types=("learning", "security"),
    tier="reference",
)
def pwn_sync(username: str = "", full: bool = False, dojo: list[str] | None = None):
    request(
        "/api/training/providers/pwn-college/sync",
        {
            "command_id": str(uuid4()),
            "username": username,
            "full": full,
            "dojo_ids": dojo or [],
        },
    )


@pwn_app.command("status")
def pwn_status():
    request("/api/training/providers/pwn-college")


@pwn_app.command("activities")
@usage(
    surface="st.learn.pwn.activities",
    cmd="st learn pwn activities [--dojo ID] [--module ID] [--solved/--unsolved] [--query TEXT]",
    when="choose a synchronized pwn.college activity before starting a study session",
    task_types=("learning", "security"),
    tier="reference",
)
def pwn_activities(
    dojo: str = "",
    module: str = "",
    solved: Annotated[bool | None, typer.Option("--solved/--unsolved")] = None,
    query: str = "",
):
    params: dict[str, str] = {"limit": "1000"}
    if dojo:
        params["dojo"] = dojo
    if module:
        params["module"] = module
    if solved is not None:
        params["solved"] = str(solved).lower()
    if query:
        params["query"] = query
    request(f"/api/training/activities?{urlencode(params)}")


@session_app.command("start")
@usage(
    surface="st.learn.session.start",
    cmd="st learn session start --activity ID [--objective TEXT] [--harness NAME] [--no-open]",
    when="bind and open a private pwn.college study session in the native terminal",
    precautions=("OpenSSH owns the private key; only sanitized output is spooled and uploaded",),
    task_types=("learning", "security"),
    tier="reference",
)
def session_start(
    activity: Annotated[str, typer.Option()],
    objective: str = "",
    harness: str = "",
    agent_name: str = "",
    model: str = "",
    open_shell: Annotated[bool, typer.Option("--open/--no-open")] = True,
    sync_provider: Annotated[bool, typer.Option("--sync/--no-sync")] = True,
):
    harness = _native_harness(harness)
    if sync_provider:
        require_data(
            "/api/training/providers/pwn-college/sync",
            {"command_id": str(uuid4()), "username": "", "full": False, "dojo_ids": []},
        )
    study = require_data(
        "/api/training/sessions",
        {
            "command_id": str(uuid4()),
            "activity_id": activity,
            "objective": objective,
            "harness": harness,
            "agent_name": agent_name,
            "model": model,
            "native_session_id": _native_session_id(),
            "actor": "agent",
        },
    )
    if study.get("admission") == "existing":
        study = _prepare_study_operator(study, harness, agent_name, model)
    output_json({"ok": True, "schema_version": 2, "data": study})
    if open_shell:
        _open_study_terminal(study, harness)


@session_app.command("continue")
@usage(
    surface="st.learn.session.continue",
    cmd="st learn session continue [--activity ID] [--objective TEXT] [--no-open]",
    when="atomically resume the one unfinished pwn.college study or create it when an activity is supplied",
    precautions=(
        "one provider account admits one unfinished study; a different live native operator requires an explicit handoff",
    ),
    task_types=("learning", "security"),
    tier="reference",
)
def session_continue(
    activity: Annotated[str, typer.Option()] = "",
    objective: str = "",
    harness: str = "",
    agent_name: str = "",
    model: str = "",
    open_shell: Annotated[bool, typer.Option("--open/--no-open")] = True,
    sync_provider: Annotated[bool, typer.Option("--sync/--no-sync")] = True,
):
    harness = _native_harness(harness)
    if sync_provider:
        require_data(
            "/api/training/providers/pwn-college/sync",
            {"command_id": str(uuid4()), "username": "", "full": False, "dojo_ids": []},
        )
    study = require_data(
        "/api/training/sessions/continue",
        {
            "command_id": str(uuid4()),
            "activity_id": activity,
            "objective": objective,
            "harness": harness,
            "agent_name": agent_name,
            "model": model,
            "native_session_id": _native_session_id(),
            "actor": "agent",
        },
    )
    if study.get("admission") == "existing":
        study = _prepare_study_operator(study, harness, agent_name, model)
    output_json({"ok": True, "schema_version": 2, "data": study})
    if open_shell:
        _open_study_terminal(study, harness)


@session_app.command("list")
def session_list(status: str = ""):
    request("/api/training/sessions" + (f"?{urlencode({'status': status})}" if status else ""))


@session_app.command("show")
def session_show(session_id: str):
    request(_study_url(session_id))


@session_app.command("attach")
def session_attach(
    session_id: str,
    expected_revision: Annotated[int, typer.Option()],
    harness: str = "",
    agent_name: str = "",
    model: str = "",
):
    request(
        _study_url(session_id, "/participants"),
        {
            "command_id": str(uuid4()),
            "expected_revision": expected_revision,
            "harness": _native_harness(harness),
            "agent_name": agent_name,
            "model": model,
            "native_session_id": _native_session_id(),
            "actor": "agent",
        },
    )


@session_app.command("handoff")
@usage(
    surface="st.learn.session.handoff",
    cmd="st learn session handoff SESSION_ID --to HARNESS --expected-revision N [--from HARNESS]",
    when="explicitly transfer the single live operator lease to an attached harness",
    precautions=("the receiving harness must attach first",),
    task_types=("learning", "security"),
    tier="reference",
)
def session_handoff(
    session_id: str,
    to: Annotated[str, typer.Option()],
    expected_revision: Annotated[int, typer.Option()],
    from_harness: Annotated[str, typer.Option("--from")] = "",
):
    from_harness = _native_harness(from_harness)
    try:
        spool = TranscriptSpool(session_id, from_harness, 0)
    except TranscriptSpoolBusy as exc:
        output_json({"ok": False, "error": "study_terminal_busy", "detail": str(exc)})
        raise typer.Exit(1) from None
    try:
        def upload(record: dict):
            payload = {key: value for key, value in record.items() if key != "session_id"}
            request_data(_study_url(session_id, "/transcript"), payload)

        if not spool.drain(upload):
            output_json(
                {
                    "ok": False,
                    "error": "pending_transcript",
                    "detail": "Upload the private pending transcript before handing off this session",
                }
            )
            raise typer.Exit(1)
    finally:
        spool.close()
    request(
        _study_url(session_id, "/handoff"),
        {
            "command_id": str(uuid4()),
            "expected_revision": expected_revision,
            "from_harness": from_harness,
            "to_harness": to,
        },
    )


@session_app.command("resume")
def session_resume(
    session_id: str,
    harness: str = "",
    agent_name: str = "",
    model: str = "",
    open_shell: Annotated[bool, typer.Option("--open/--no-open")] = True,
):
    harness = _native_harness(harness)
    require_data(
        "/api/training/providers/pwn-college/sync",
        {"command_id": str(uuid4()), "username": "", "full": False, "dojo_ids": []},
    )
    study = require_data(_study_url(session_id))
    study = _prepare_study_operator(study, harness, agent_name, model)
    output_json({"ok": True, "schema_version": 2, "data": study})
    if open_shell:
        _open_study_terminal(study, harness)


@session_app.command("pause")
def session_pause(session_id: str, harness: str = "", note: str = ""):
    study = require_data(_study_url(session_id))
    result = _session_action(study, "pause", _native_harness(harness), note=note)
    output_json({"ok": True, "schema_version": 2, "data": result})


@session_app.command("finish")
@usage(
    surface="st.learn.session.finish",
    cmd="st learn session finish SESSION_ID [--file evidence.json] [--harness NAME]",
    when="sync platform solve state, save final evidence and close a study session",
    precautions=("a platform solve remains separate from human explanation, reproduction and delayed recall",),
    task_types=("learning", "security"),
    tier="reference",
)
def session_finish(
    session_id: str,
    harness: str = "",
    file: Annotated[Path | None, typer.Option()] = None,
):
    harness = _native_harness(harness)
    study = require_data(_study_url(session_id))
    try:
        spool = TranscriptSpool(
            session_id,
            harness,
            int(study["transcript"]["last_sequence"]) + 1,
        )
    except TranscriptSpoolBusy as exc:
        output_json({"ok": False, "error": "study_terminal_busy", "detail": str(exc)})
        raise typer.Exit(1) from None
    try:
        def upload(record: dict):
            payload = {key: value for key, value in record.items() if key != "session_id"}
            request_data(_study_url(session_id, "/transcript"), payload)

        if not spool.drain(upload):
            output_json(
                {
                    "ok": False,
                    "error": "pending_transcript",
                    "detail": "Upload the private pending transcript before finishing this session",
                }
            )
            raise typer.Exit(1)
        if file:
            evidence = read_file(file)
            evidence.setdefault("command_id", str(uuid4()))
            evidence.setdefault("actor", "human")
            evidence.setdefault("harness", harness)
            require_data(_study_url(session_id, "/evidence"), evidence)
        require_data(
            "/api/training/providers/pwn-college/sync",
            {"command_id": str(uuid4()), "username": "", "full": False, "dojo_ids": []},
        )
        activities = require_data("/api/training/activities?limit=1000")["items"]
        current = next((item for item in activities if item["id"] == study["data"]["activity_id"]), None)
        platform_solved = bool(current and current["data"].get("platform_solved"))
        study = require_data(_study_url(session_id))
        result = _session_action(
            study,
            "finish",
            harness,
            note="Final provider reconciliation completed",
            platform_solved=platform_solved,
        )
        output_json({"ok": True, "schema_version": 2, "data": result})
    finally:
        spool.close()


@session_app.command("evidence")
def session_evidence(session_id: str, file: Annotated[Path, typer.Option()]):
    payload = read_file(file)
    payload.setdefault("command_id", str(uuid4()))
    payload.setdefault("actor", "agent")
    payload.setdefault("harness", _native_harness(""))
    request(_study_url(session_id, "/evidence"), payload)


@session_app.command("review")
def session_review(session_id: str, file: Annotated[Path, typer.Option()]):
    payload = read_file(file)
    payload.setdefault("command_id", str(uuid4()))
    payload.setdefault("reviewer_harness", _native_harness(""))
    request(_study_url(session_id, "/reviews"), payload)


@session_app.command("transcript")
def session_transcript(session_id: str):
    request(_study_url(session_id, "/transcript"))


@improvements_app.command("list")
def improvements_list(status: str = "", project: str = ""):
    params = {key: value for key, value in {"status": status, "target_project": project}.items() if value}
    request("/api/training/improvements" + (f"?{urlencode(params)}" if params else ""))


@improvements_app.command("add")
def improvements_add(file: Annotated[Path, typer.Option()]):
    payload = read_file(file)
    payload.setdefault("command_id", str(uuid4()))
    payload.setdefault("actor", "agent")
    request("/api/training/improvements", payload)


@improvements_app.command("triage")
def improvements_triage(
    candidate_id: str,
    status: Annotated[str, typer.Option()],
    expected_revision: Annotated[int, typer.Option()],
    note: str = "",
):
    request(
        f"/api/training/improvements/{quote(candidate_id, safe='')}/triage",
        {
            "command_id": str(uuid4()),
            "expected_revision": expected_revision,
            "status": status,
            "note": note,
            "summitflow_task_id": "",
        },
    )


@improvements_app.command("promote")
@usage(
    surface="st.learn.improvements.promote",
    cmd="st learn improvements promote CANDIDATE_ID [--project PROJECT] [--priority N]",
    when="explicitly promote an accepted learning improvement into a SummitFlow idea task",
    precautions=("promotion is never automatic; task text contains the triaged candidate, not the private transcript",),
    task_types=("learning", "planning"),
    tier="reference",
)
def improvements_promote(candidate_id: str, project: str = "", priority: int = 2):
    listing = require_data("/api/training/improvements")["items"]
    candidate = next((item for item in listing if item["id"] == candidate_id), None)
    if not candidate:
        raise typer.BadParameter("Improvement candidate was not found")
    if candidate["data"]["status"] != "accepted":
        raise typer.BadParameter("Accept the candidate in triage before promotion")
    target = project or candidate["data"].get("target_project", "")
    if not target:
        raise typer.BadParameter("Choose a SummitFlow target project with --project")
    set_project_override(target)
    description = (
        f"Learning observation: {candidate['data']['observation']}\n\n"
        f"Proposed change: {candidate['data'].get('proposed_change') or 'Shape during task planning.'}\n\n"
        f"Learn-o-Tron candidate: {candidate_id}\n"
        f"Study session: {candidate['data']['session_id']}"
    )
    task_data = {
        "title": candidate["data"]["title"],
        "description": description,
        "task_type": "idea",
        "priority": priority,
        "labels": ["pwn-college", "learning-transfer"],
        "execution_mode": "manual_only",
        "auto_dispatch": False,
        "external_origin": "learn-o-tron",
        "external_request_key": candidate_id,
        "done_when": ["The accepted learning observation is assessed in the target product and a bounded change is verified."],
    }
    try:
        task = STClient().create_task(task_data)
    except APIError as exc:
        output_json({"ok": False, "error": "summitflow_task_error", "detail": str(exc.detail)})
        raise typer.Exit(1) from None
    command_id = uuid5(NAMESPACE_URL, f"learn-o-tron:promote:{candidate_id}:{task['id']}")
    receipt = require_data(
        f"/api/training/improvements/{quote(candidate_id, safe='')}/triage",
        {
            "command_id": str(command_id),
            "expected_revision": candidate["revision"],
            "status": "promoted",
            "note": f"Promoted to {target}",
            "summitflow_task_id": task["id"],
        },
    )
    output_json({"ok": True, "schema_version": 2, "task": task, "candidate": receipt})
