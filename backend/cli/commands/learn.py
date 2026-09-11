"""Agent-facing Learn-o-Tron operations; the project API owns all learning state."""
from __future__ import annotations

import json
import sys
from enum import StrEnum
from pathlib import Path
from typing import Annotated
from uuid import UUID, uuid4

import typer

from .._client_base import APIError
from .._project_client import ProjectApi, ProjectApiClient, ProjectApiConnectError, resolve_api_url
from ..lib.usage import usage
from ..output import output_json

app = typer.Typer(help="Learn, research and review through Learn-o-Tron's canonical API")
API = ProjectApi(project_id="learn-o-tron", env_var="ST_LEARN_API_URL", default_url="http://127.0.0.1:8018")


def request(path: str, body: dict | None = None, method: str = "POST"):
    try:
        with ProjectApiClient(resolve_api_url(API).url) as client:
            if body is None:
                result = client.get(path)
            elif method == "PATCH":
                result = client.patch(path, json_body=body)
            elif method == "PUT":
                result = client.put(path, json_body=body)
            else:
                result = client.post(path, json_body=body)
        output_json({"ok": True, "schema_version": 1, "data": result})
    except ProjectApiConnectError:
        output_json({"ok": False, "error": "learn_unreachable", "hint": "Check st service status learn-o-tron or ST_LEARN_API_URL"})
        raise typer.Exit(2) from None
    except APIError as exc:
        output_json({"ok": False, "error": "learn_api_error", "detail": exc.detail})
        raise typer.Exit(1) from None


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
