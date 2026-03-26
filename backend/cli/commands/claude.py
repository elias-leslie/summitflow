"""Claude Code worker dispatch commands."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Annotated, Any

import typer

from ..client import APIError, STClient
from ..output import handle_api_error, output_error
from ._projects_helpers import UNEXPECTED_RESPONSE_MSG, projects_api

app = typer.Typer(help="Claude Code worker dispatch")

_Opt = typer.Option
_Arg = typer.Argument

_AGENT_HUB_PROJECT_ID = "agent-hub"
_DEFAULT_MODEL = "claude-sonnet-4-6"
_DEFAULT_TIMEOUT_SECONDS = 1800
_DEFAULT_SOURCE = "st-cli"


def _fetch_task(task_id: str) -> dict[str, Any]:
    """Fetch task details from SummitFlow."""
    client = STClient(require_project=False)
    try:
        return client.get_task(task_id)
    except APIError as exc:
        handle_api_error(exc)
        raise typer.Exit(1) from None


def _validate_task_readiness(
    *,
    task_id: str,
    project_id: str,
    allow_unready: bool,
) -> None:
    """Ensure the task is ready for worker dispatch unless explicitly overridden."""
    if allow_unready:
        return

    client = STClient(project_id=project_id, require_project=False)
    readiness = client.validate_ready(task_id)
    if readiness.get("ready", False):
        return

    output_error(f"Task {task_id} is not execution-ready for Claude worker dispatch.")
    for issue in readiness.get("issues", [])[:8]:
        output_error(f"  - {issue}")
    for suggestion in readiness.get("suggestions", [])[:5]:
        output_error(f"  hint: {suggestion}")
    raise typer.Exit(1)


def _resolve_project_root(project_id: str) -> Path:
    """Resolve a project root through the projects API."""
    project = projects_api("GET", f"/{project_id}")
    if not isinstance(project, dict):
        output_error(UNEXPECTED_RESPONSE_MSG)
        raise typer.Exit(1)
    root_path = project.get("root_path")
    if not isinstance(root_path, str) or not root_path.strip():
        output_error(f"Project '{project_id}' has no root_path configured")
        raise typer.Exit(1)
    return Path(root_path).resolve()


def _resolve_agent_hub_paths() -> tuple[Path, Path]:
    """Resolve the canonical Agent Hub Python entrypoint for the worker wrapper."""
    agent_hub_root = _resolve_project_root(_AGENT_HUB_PROJECT_ID)
    python_bin = agent_hub_root / "backend" / ".venv" / "bin" / "python"
    script_path = agent_hub_root / "backend" / "scripts" / "run_claude_orchestrated_worker.py"
    if not python_bin.is_file():
        output_error(f"Agent Hub python not found: {python_bin}")
        raise typer.Exit(1)
    if not script_path.is_file():
        output_error(f"Claude worker script not found: {script_path}")
        raise typer.Exit(1)
    return python_bin, script_path


def _resolve_feedback_text(feedback_text: str | None, feedback_file: Path | None) -> str | None:
    """Resolve evaluator feedback from inline text or a file."""
    if feedback_text and feedback_file:
        output_error("Use either --feedback-text or --feedback-file, not both.")
        raise typer.Exit(1)
    if feedback_file is None:
        return feedback_text
    if not feedback_file.is_file():
        output_error(f"Feedback file not found: {feedback_file}")
        raise typer.Exit(1)
    return feedback_file.read_text().strip() or None


def _worker_env() -> dict[str, str]:
    """Return the minimal env overlay needed to execute the Agent Hub worker wrapper."""
    env = os.environ.copy()
    env["PYTHONPATH"] = "backend"
    return env


def _build_worker_command(
    *,
    python_bin: Path,
    script_path: Path,
    task_id: str,
    project_id: str,
    project_root: Path,
    model: str,
    timeout_seconds: int,
    claim_if_needed: bool,
    feedback_text: str | None,
) -> list[str]:
    """Build the canonical Claude worker wrapper command."""
    command = [
        str(python_bin),
        str(script_path),
        "--project-id",
        project_id,
        "--task-id",
        task_id,
        "--task-root",
        str(project_root),
        "--model",
        model,
        "--timeout-seconds",
        str(timeout_seconds),
        "--source",
        _DEFAULT_SOURCE,
    ]
    if claim_if_needed:
        command.append("--claim-if-needed")
    if feedback_text:
        command.extend(["--feedback-text", feedback_text])
    return command


def _run_worker(*, command: list[str], cwd: Path) -> int:
    """Run the worker wrapper and stream output through the current terminal."""
    result = subprocess.run(command, cwd=cwd, env=_worker_env(), check=False)
    return int(result.returncode)


@app.command("task")
def run_task(
    task_id: Annotated[str, _Arg(help="Task ID to dispatch through the Claude worker wrapper")],
    model: Annotated[str, _Opt("--model", help="Claude model override")] = _DEFAULT_MODEL,
    timeout_seconds: Annotated[
        int,
        _Opt("--timeout-seconds", min=1, help="Worker timeout budget in seconds"),
    ] = _DEFAULT_TIMEOUT_SECONDS,
    claim_if_needed: Annotated[
        bool,
        _Opt("--claim-if-needed/--no-claim-if-needed", help="Claim the task if it is not already claimed"),
    ] = True,
    allow_unready: Annotated[
        bool,
        _Opt("--allow-unready", help="Skip execution-readiness validation"),
    ] = False,
    feedback_text: Annotated[
        str | None,
        _Opt("--feedback-text", help="Inline evaluator feedback for a redrive"),
    ] = None,
    feedback_file: Annotated[
        Path | None,
        _Opt("--feedback-file", help="Read evaluator feedback from a file"),
    ] = None,
) -> None:
    """Run a task through the canonical Agent Hub Claude worker wrapper."""
    task = _fetch_task(task_id)
    resolved_task_id = str(task.get("id", task_id))
    project_id = str(task.get("project_id") or "")
    if not project_id:
        output_error(f"Task {resolved_task_id} has no project_id")
        raise typer.Exit(1)

    _validate_task_readiness(
        task_id=resolved_task_id,
        project_id=project_id,
        allow_unready=allow_unready,
    )
    project_root = _resolve_project_root(project_id)
    python_bin, script_path = _resolve_agent_hub_paths()
    feedback = _resolve_feedback_text(feedback_text, feedback_file)
    command = _build_worker_command(
        python_bin=python_bin,
        script_path=script_path,
        task_id=resolved_task_id,
        project_id=project_id,
        project_root=project_root,
        model=model,
        timeout_seconds=timeout_seconds,
        claim_if_needed=claim_if_needed,
        feedback_text=feedback,
    )

    exit_code = _run_worker(command=command, cwd=script_path.parent.parent)
    if exit_code != 0:
        raise typer.Exit(exit_code)
