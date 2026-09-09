"""Thin CLI for Neri's canonical investigation API; no duplicate execution logic."""
from __future__ import annotations

from enum import StrEnum
from uuid import UUID

import typer

from .._client_base import APIError
from .._project_client import ProjectApi, ProjectApiClient, ProjectApiConnectError, resolve_api_url
from ..lib.usage import usage
from ..output import output_json

app = typer.Typer(help="Run and inspect Neri's isolated discovery labs")
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


def request(path: str, body: dict | None = None) -> None:
    resolved = resolve_api_url(NERI_API)
    try:
        with ProjectApiClient(resolved.url) as client:
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
def start(variant: Variant = Variant.benchmark, advanced: bool = False) -> None:
    """Start actual agent-led discovery. Guidance mode does not change permissions."""
    request("/api/runs", {"variant": variant.value, "guidance": "advanced" if advanced else "helper"})


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
