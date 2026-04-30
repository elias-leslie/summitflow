"""Graphify CLI wrappers for agent topology work."""

from __future__ import annotations

import shutil
import subprocess
import sys
import time
from dataclasses import asdict
from pathlib import Path
from typing import Annotated, Any

import typer

from app.services.graphify_tools import (
    GraphifyCommandResult,
    explain_graph,
    graphify_status,
    path_graph,
    query_graph,
    refresh_graph,
)

from ..config import get_config
from ..output import output_json
from ._projects_helpers import projects_api

app = typer.Typer(help="Graphify topology and profiling helpers")


def _project_payload(project_id: str) -> dict[str, Any]:
    project = projects_api("GET", f"/{project_id}")
    if not isinstance(project, dict):
        raise typer.BadParameter(f"Project '{project_id}' not found")
    return project


def _all_projects() -> list[dict[str, Any]]:
    projects = projects_api("GET")
    if not isinstance(projects, list):
        return []
    return projects


def _project_id(value: str | None) -> str:
    return value or get_config().project_id


def _root_for_project(project_id: str) -> Path:
    project = _project_payload(project_id)
    root_path = project.get("root_path")
    if not root_path:
        raise typer.BadParameter(f"Project '{project_id}' has no root_path configured")
    return Path(str(root_path)).expanduser().resolve()


def _status_for_project(project_id: str) -> dict[str, Any]:
    return graphify_status(project_id, _root_for_project(project_id))


def _command_payload(result: GraphifyCommandResult) -> dict[str, Any]:
    return asdict(result)


def _issue_count(status: dict[str, Any]) -> int:
    return len(status.get("diagnostics", []))


@app.command("status")
def status(
    project: Annotated[str | None, typer.Option("--project", "-p", help="Project id. Defaults to current project.")] = None,
    all_projects: Annotated[bool, typer.Option("--all", help="Show every registered project.")] = False,
) -> None:
    """Show Graphify status and diagnostics."""
    if all_projects:
        output_json([_status_for_project(str(item["id"])) for item in _all_projects() if item.get("id")])
        return
    output_json(_status_for_project(_project_id(project)))


@app.command("doctor")
def doctor(
    project: Annotated[str | None, typer.Option("--project", "-p", help="Project id. Defaults to every project.")] = None,
) -> None:
    """Report Graphify issues that affect agent usefulness."""
    project_ids = [_project_id(project)] if project else [str(item["id"]) for item in _all_projects() if item.get("id")]
    statuses = [_status_for_project(project_id) for project_id in project_ids]
    issues = [
        {
            "project_id": item["project_id"],
            "diagnostics": item["diagnostics"],
            "changed_files_since_graph": item["changed_files_since_graph"],
        }
        for item in statuses
        if _issue_count(item)
    ]
    payload = {
        "status": "ISSUES" if issues else "OK",
        "projects": len(statuses),
        "issues": issues,
        "issue_count": sum(_issue_count(item) for item in statuses),
    }
    output_json(payload)
    if issues:
        raise typer.Exit(2)


@app.command("refresh")
def refresh(
    project: Annotated[str | None, typer.Option("--project", "-p", help="Project id. Defaults to current project.")] = None,
) -> None:
    """Refresh a project's code-only Graphify graph."""
    project_id = _project_id(project)
    result = refresh_graph(_root_for_project(project_id))
    output_json({"project_id": project_id, **_command_payload(result), "status": _status_for_project(project_id)})


@app.command("query")
def query(
    question: Annotated[str, typer.Argument(help="Topology question.")],
    project: Annotated[str | None, typer.Option("--project", "-p", help="Project id. Defaults to current project.")] = None,
    budget: Annotated[int, typer.Option("--budget", min=100, max=8000, help="Graphify token budget.")] = 1200,
    dfs: Annotated[bool, typer.Option("--dfs", help="Use depth-first traversal.")] = False,
) -> None:
    """Run Graphify query against a project graph."""
    result = query_graph(_root_for_project(_project_id(project)), question, budget=budget, dfs=dfs)
    output_json(_command_payload(result))


@app.command("path")
def path(
    source: Annotated[str, typer.Argument(help="Source node label.")],
    target: Annotated[str, typer.Argument(help="Target node label.")],
    project: Annotated[str | None, typer.Option("--project", "-p", help="Project id. Defaults to current project.")] = None,
) -> None:
    """Find shortest Graphify path between two nodes."""
    result = path_graph(_root_for_project(_project_id(project)), source, target)
    output_json(_command_payload(result))


@app.command("explain")
def explain(
    node: Annotated[str, typer.Argument(help="Node label.")],
    project: Annotated[str | None, typer.Option("--project", "-p", help="Project id. Defaults to current project.")] = None,
) -> None:
    """Explain one graph node and its neighbors."""
    result = explain_graph(_root_for_project(_project_id(project)), node)
    output_json(_command_payload(result))


def _run_measured(command: list[str], *, cwd: Path, timeout: int = 180) -> dict[str, Any]:
    start = time.perf_counter()
    try:
        result = subprocess.run(
            command,
            cwd=cwd,
            text=True,
            capture_output=True,
            timeout=timeout,
            check=False,
        )
        output = "\n".join(
            part for part in ((result.stdout or "").strip(), (result.stderr or "").strip()) if part
        )
        exit_code = result.returncode
    except (OSError, subprocess.SubprocessError) as exc:
        output = str(exc)
        exit_code = 1
    elapsed_ms = round((time.perf_counter() - start) * 1000)
    return {
        "command": command,
        "exit_code": exit_code,
        "elapsed_ms": elapsed_ms,
        "output_chars": len(output),
        "estimated_tokens": (len(output) + 3) // 4 if output else 0,
        "output_preview": output[:1200],
    }


@app.command("profile")
def profile(
    question: Annotated[
        str,
        typer.Option("--question", "-q", help="Architecture question to profile."),
    ] = "What are the central modules and relationship patterns in this project?",
    project: Annotated[str | None, typer.Option("--project", "-p", help="Project id. Defaults to current project.")] = None,
    budget: Annotated[int, typer.Option("--budget", min=100, max=8000, help="Graphify token budget.")] = 1200,
    codex: Annotated[bool, typer.Option("--codex", help="Probe Codex CLI availability and startup cost.")] = False,
    agent_hub: Annotated[bool, typer.Option("--agent-hub", help="Probe Agent Hub completion CLI availability.")] = False,
) -> None:
    """Profile st search vs Graphify command shapes for agent work."""
    project_id = _project_id(project)
    root = _root_for_project(project_id)
    st_bin = shutil.which("st") or sys.argv[0]
    runs = [
        _run_measured([st_bin, "-P", project_id, "search", question], cwd=root),
        _command_payload(query_graph(root, question, budget=budget)),
    ]
    tool_probes: list[dict[str, Any]] = []
    if codex:
        codex_bin = shutil.which("codex")
        if codex_bin:
            tool_probes.append(_run_measured([codex_bin, "--version"], cwd=root, timeout=30))
            tool_probes.append(_run_measured([codex_bin, "exec", "--help"], cwd=root, timeout=30))
        else:
            tool_probes.append({"tool": "codex", "available": False})
    if agent_hub:
        tool_probes.append(
            _run_measured(
                [
                    st_bin,
                    "-P",
                    "agent-hub",
                    "agents",
                    "preview",
                    "explorer",
                    "-P",
                    project_id,
                    "--input",
                    question,
                    "--json",
                ],
                cwd=root,
                timeout=90,
            )
        )
    output_json(
        {
            "project_id": project_id,
            "question": question,
            "runs": runs,
            "tool_probes": tool_probes,
            "recommendation": "Use st search for exact symbols/files; use st graph query/path/explain for topology and impact-radius questions.",
        }
    )
