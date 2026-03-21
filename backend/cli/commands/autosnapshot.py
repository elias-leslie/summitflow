"""Hidden autosnapshot commands for systemd timer and hook invocation."""

from __future__ import annotations

import typer

from ..config import get_config
from ..lib.autosnapshot import ensure_all_baselines, ensure_baseline, prune_all, sweep_periodic
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


@app.command("sweep")
def sweep_command() -> None:
    """Run periodic snapshot sweep across all active Btrfs-backed scopes."""
    created = sweep_periodic()
    print(f"SWEEP[{len(created)}]")
    for snap in created:
        print(f"  {snap.id}|source:{snap.source}|scope:{snap.scope_type}:{snap.scope_name}")


@app.command("prune")
def prune_command() -> None:
    """Run retention cleanup across all active Btrfs-backed scopes."""
    results = prune_all()
    total = sum(len(v) for v in results.values())
    print(f"PRUNE[{total}]")
    for scope_key, entries in results.items():
        for entry in entries:
            print(f"  {entry.id}|source:{entry.source}|scope:{scope_key}")
