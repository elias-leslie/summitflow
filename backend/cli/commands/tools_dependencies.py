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
    project: Annotated[str | None, typer.Option("--project", "-P", help="Project ID; defaults to the detected project.")] = None,
    ecosystem: Annotated[str | None, typer.Option("--ecosystem", help="Filter by package ecosystem.")] = None,
    status: Annotated[str | None, typer.Option("--status", help="Review decision: unreviewed, update, hold, or investigate.")] = None,
    query: Annotated[str | None, typer.Option("--query", help="Case-insensitive package name filter.")] = None,
    limit: Annotated[int, typer.Option("--limit", min=1, max=500, help="Maximum entries per page.")] = 50,
    offset: Annotated[int, typer.Option("--offset", min=0, help="Skip this many matching entries.")] = 0,
    json_output: Annotated[bool, typer.Option("--json", help="Include full inventory and review records as JSON.")] = False,
) -> None:
    """List package evidence and review decisions; use review on an entry path next."""
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
    project: Annotated[str | None, typer.Option("--project", "-P", help="Project ID; defaults to the detected project.")] = None,
    refresh: Annotated[bool, typer.Option("--refresh", help="Refresh the Explorer dependency scan first")] = False,
) -> None:
    """Build a decision packet for one dependency; use record with record.revision."""
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
    revision: Annotated[int, typer.Option("--revision", min=1, help="Current record.revision from st tools dependencies review; stale revisions fail.")],
    reason: Annotated[str, typer.Option("--reason", help="Rationale for this decision.")],
    project: Annotated[str | None, typer.Option("--project", "-P", help="Project ID; defaults to the detected project.")] = None,
    version: Annotated[str | None, typer.Option("--version", help="Recommended version for an update decision.")] = None,
    queue: Annotated[bool, typer.Option("--queue", help="Queue a deduplicated update task for an update decision.")] = False,
) -> None:
    """Record a decision against a reviewed evidence revision."""
    from app.services.dependency_management import record_decision

    try:
        _emit({"record": record_decision(
            _project(project), entry_path, decision=decision, rationale=reason,
            expected_revision=revision, recommended_version=version, queue_task=queue,
        )}, compact=True)
    except ValueError as exc:
        output_error(str(exc))
        raise typer.Exit(2) from exc
