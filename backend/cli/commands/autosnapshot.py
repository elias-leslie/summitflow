"""Hidden autosnapshot commands for systemd timer and hook invocation."""

from __future__ import annotations

from typing import Annotated

import typer

from ..config import get_config
from ..lib.autosnapshot import (
    LAST_PRUNE_REPORT,
    LAST_PRUNE_SUMMARY,
    LAST_SWEEP_REPORT,
    ensure_all_baselines,
    ensure_baseline,
    prune_all,
    sweep_periodic,
)
from ..lib.quick_snapshots import SnapshotError

app = typer.Typer(
    help="Internal autosnapshot commands (systemd timer / hooks)",
    no_args_is_help=True,
)


@app.command("ensure-baseline")
def ensure_baseline_command() -> None:
    """Create a baseline snapshot if stale or missing for the current scope."""
    config = get_config()
    try:
        result = ensure_baseline(project_id=config.project_id, source="auto-baseline")
    except SnapshotError as exc:
        typer.echo(f"autosnap: baseline skipped: {exc}", err=True)
        return

    if result:
        print(f"BASELINE {result.id}|source:{result.source}|scope:{result.scope_type}:{result.scope_name}")
    else:
        print("BASELINE skip|recent baseline exists")


@app.command("ensure-all-baselines")
def ensure_all_baselines_command() -> None:
    """Create baseline snapshots for active scopes whose newest snapshot is stale."""
    created = ensure_all_baselines()
    print(f"BASELINES[{len(created)}]")
    for snap in created:
        print(f"  {snap.id}|source:{snap.source}|scope:{snap.scope_type}:{snap.scope_name}")


def _deferred(exc: SnapshotError, step: str) -> None:
    """Another snapshot job holding the shared lock is a skip, not a failure."""
    if not str(exc).startswith("Deferred:"):
        raise exc
    typer.echo(f"autosnap: {step} skipped: {exc}", err=True)


@app.command("sweep")
def sweep_command() -> None:
    """Run periodic snapshot sweep across all active Btrfs-backed scopes."""
    try:
        created = sweep_periodic()
    except SnapshotError as exc:
        _deferred(exc, "sweep")
        return
    print(f"SWEEP[{len(created)}]")
    for record in LAST_SWEEP_REPORT:
        print(f"  {record['project_id']}|{record['status']}|reason:{record['reason']}")
    for snap in created:
        print(f"  {snap.id}|source:{snap.source}|scope:{snap.scope_type}:{snap.scope_name}")


@app.command("prune")
def prune_command(
    pressure: Annotated[bool, typer.Option("--pressure", help="Disk pressure: keep only the newest few points.")] = False,
    max_deletes: Annotated[int | None, typer.Option("--max-deletes", min=0, help="Physical deletions this run (default: policy cap).")] = None,
    dry_run: Annotated[bool, typer.Option("--dry-run", help="Report what would be deleted.")] = False,
) -> None:
    """Delete expired snapshot points (oldest first, capped, paced); exit 1 when a deletion is deferred."""
    try:
        results = prune_all(pressure=pressure, max_deletes=max_deletes, dry_run=dry_run)
    except SnapshotError as exc:
        _deferred(exc, "prune")
        return
    total = sum(len(v) for v in results.values())
    summary = LAST_PRUNE_SUMMARY
    print(f"PRUNE[{total}]|points:{summary['selected']}|deleted:{summary['deleted']}|orphans:{summary['orphans']}|"
          f"deferred:{len(summary['deferred'])}|backlog:{summary['remaining']}|pressure:{'yes' if pressure else 'no'}")
    for record in LAST_PRUNE_REPORT:
        print(f"  recovery-copy:{record['root_path']}|action:{record['action']}|error:{record['error'] or '-'}")
    for scope_key, entries in results.items():
        for entry in entries:
            print(f"  {entry.id}|source:{entry.source}|scope:{scope_key}")
    if summary["deferred"]:
        first = summary["deferred"][0]
        typer.echo(f"autosnap: prune deferred {len(summary['deferred'])} snapshot deletion(s); first: {first['path']}: "
                   f"{first['error'].splitlines()[0] if first['error'] else 'unknown'}", err=True)
        raise typer.Exit(1)
