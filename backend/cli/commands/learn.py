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


@app.command()
@usage(surface="st.learn.work", cmd="st learn work recommend|curriculum|tutor|review|audio [--message TEXT] [--record ID] [--lesson ID] [--command-id UUID]", when="request bounded subscription-only Agent Hub learning work or local audio", precautions=("returns a durable job; inspect status before retrying; preserve command ID only for identical payloads; review record is an attempt ID",), task_types=("learning", "learn-o-tron"), tier="reference")
def work(kind: WorkKind, message: str = "", record: str = "", lesson: str = "", command_id: UUID | None = None):
    request("/api/jobs", {"command_id": str(command_id or uuid4()), "kind": kind.value, "message": message,
                          "record_id": record, "lesson_id": lesson, "actor": "agent"})


@app.command()
@usage(surface="st.learn.status", cmd="st learn status [JOB_ID]", when="read job completion or full learning state", precautions=("queued/running is not completion; full state is larger than st learn context",), task_types=("learning", "learn-o-tron"), tier="reference")
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
