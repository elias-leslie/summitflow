"""Native host recovery through the qualified local btrbk adapter."""

from typing import Annotated

import typer

from app.tasks.backup_btrbk import native_host_status, run_native_host_backup

from ..lib.usage import usage
from ..output import output_json

app = typer.Typer(help="Linux native Btrfs host recovery; Windows uses Veeam")


@app.command("status")
@usage(surface="st.backup.host", cmd="st backup host status", when="inspect Linux native host recovery coverage, capacity and evidence", precautions=("Windows backups remain Veeam-managed", "unconfigured or unverified coverage is not a recoverable host backup"), tier="reference")
def status() -> None:
    """Inspect the actual host configuration and latest recovery receipt."""
    output_json(native_host_status())


@app.command("run")
def run(dry_run: Annotated[bool, typer.Option("--dry-run", help="Inspect coverage and admission without creating a backup")] = False) -> None:
    """Run only an enabled, configured, admitted native host capture."""
    result = run_native_host_backup(dry_run=dry_run)
    output_json(result)
    if result["status"] in {"failed", "blocked", "partial", "cancelled", "error"}:
        raise typer.Exit(1)
