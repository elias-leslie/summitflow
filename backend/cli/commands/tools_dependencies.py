"""Dependency inventory and evidence-linked review commands."""

from __future__ import annotations

import json
from typing import Annotated, Any

import typer

from ..config import get_config_optional
from ..lib.usage import usage
from ..output import output_error

app = typer.Typer(help="Inventory and review package dependencies; st deps manages task blockers.")


def _project(explicit: str | None) -> str:
    config = get_config_optional()
    project = explicit or (config.project_id if config else None)
    if not project:
        output_error("No project detected. Pass --project or run inside a registered project.")
        raise typer.Exit(2)
    return project


def _emit(payload: dict[str, Any], compact: bool) -> None:
    print(json.dumps(payload, sort_keys=True, default=str, separators=(",", ":") if compact else None))


@app.command("list")
@usage(
    surface="st.tools.dependencies",
    cmd="st tools dependencies list [--project ID] [--ecosystem NAME]",
    when="inspect declared, locked, installed, latest, and reviewed dependency evidence",
    precautions=("Unknown checks remain unknown; listing never installs packages or runs update engines.",),
)
def list_dependencies(
    project: Annotated[str | None, typer.Option("--project", "-P")] = None,
    ecosystem: Annotated[str | None, typer.Option("--ecosystem")] = None,
    status: Annotated[str | None, typer.Option("--status")] = None,
    query: Annotated[str | None, typer.Option("--query")] = None,
    limit: Annotated[int, typer.Option("--limit", min=1, max=500)] = 50,
    offset: Annotated[int, typer.Option("--offset", min=0)] = 0,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    from app.services.dependency_management import list_inventory

    result = list_inventory(_project(project), ecosystem=ecosystem, status=status, query=query, limit=limit, offset=offset)
    if json_output:
        _emit(result, compact=True)
        return
    print(f"DEPENDENCIES:{result['project_id']}|total={result['total']}|shown={len(result['items'])}")
    for item in result["items"]:
        decision = (item["review"] or {}).get("decision", "unreviewed")
        print(
            f"{item['entry_path']}|declared={item['declared_version'] or '?'}|"
            f"locked={item['locked_version'] or '?'}|installed={item['installed_version'] or '?'}|"
            f"latest={item['latest_version'] or '?'}|recommended={item['recommended_version'] or '?'}|"
            f"review={decision}"
        )


@app.command("review")
def review(
    entry_path: Annotated[str, typer.Argument(help="Explorer dependency entry path")],
    project: Annotated[str | None, typer.Option("--project", "-P")] = None,
    refresh: Annotated[bool, typer.Option("--refresh", help="Refresh the Explorer dependency scan first")] = False,
) -> None:
    from app.services.dependency_management import review_dependency

    try:
        _emit(review_dependency(_project(project), entry_path, refresh=refresh), compact=True)
    except ValueError as exc:
        output_error(str(exc))
        raise typer.Exit(2) from exc


@app.command("record")
def record(
    entry_path: Annotated[str, typer.Argument(help="Explorer dependency entry path")],
    decision: Annotated[str, typer.Argument(help="update, hold, or investigate")],
    revision: Annotated[int, typer.Option("--revision", min=1)],
    reason: Annotated[str, typer.Option("--reason")],
    project: Annotated[str | None, typer.Option("--project", "-P")] = None,
    version: Annotated[str | None, typer.Option("--version")] = None,
    queue: Annotated[bool, typer.Option("--queue", help="Queue a deduplicated update task")] = False,
) -> None:
    from app.services.dependency_management import record_decision

    try:
        _emit({"record": record_decision(
            _project(project), entry_path, decision=decision, rationale=reason,
            expected_revision=revision, recommended_version=version, queue_task=queue,
        )}, compact=True)
    except ValueError as exc:
        output_error(str(exc))
        raise typer.Exit(2) from exc
