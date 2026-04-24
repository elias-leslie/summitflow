"""Canonical setup command surface."""

from __future__ import annotations

from typing import Annotated

import typer

from ..lib.confirm_token import confirm_gate
from .operator_forward import run_forwarded

app = typer.Typer(help="Host, service, browser, tooling, and test database setup")


def _preview(command: str, lines: list[str], dry_run: bool, confirm: str | None) -> None:
    if dry_run:
        print("\n".join(lines))
        return
    confirm_gate(command.replace(" ", "-"), confirm, lines, command)


@app.command()
def services(
    dry_run: Annotated[bool, typer.Option("--dry-run", help="Preview setup without running")] = False,
    confirm: Annotated[str | None, typer.Option("--confirm", help="Confirm token from preview run")] = None,
) -> None:
    """Configure systemd services and canonical CLI entrypoints."""
    lines = [
        "SETUP SERVICES",
        "Renders user systemd units, refreshes managed repo cache, and installs canonical CLI links.",
        "Legacy public wrapper links are not part of the st clean-break contract.",
    ]
    _preview("st setup services", lines, dry_run, confirm)
    if dry_run:
        return
    run_forwarded("setup-services.sh", [])


@app.command()
def browser(
    version: Annotated[str | None, typer.Argument(help="Optional agent-browser npm version")] = None,
    dry_run: Annotated[bool, typer.Option("--dry-run", help="Preview setup without running")] = False,
    confirm: Annotated[str | None, typer.Option("--confirm", help="Confirm token from preview run")] = None,
) -> None:
    """Install or update the managed browser runner."""
    lines = [
        "SETUP BROWSER",
        f"Version: {version or 'latest'}",
        "Installs agent-browser and the managed browser wrapper.",
    ]
    _preview("st setup browser", lines, dry_run, confirm)
    if dry_run:
        return
    args = [version] if version else []
    run_forwarded("setup-agent-browser.sh", args)


@app.command("agent-tooling")
def agent_tooling(
    dry_run: Annotated[bool, typer.Option("--dry-run", help="Preview setup without running")] = False,
    confirm: Annotated[str | None, typer.Option("--confirm", help="Confirm token from preview run")] = None,
) -> None:
    """Install shared Codex/Claude operator tooling."""
    lines = [
        "SETUP AGENT TOOLING",
        "Refreshes shared agent config repositories and installs agent CLI wrappers.",
    ]
    _preview("st setup agent-tooling", lines, dry_run, confirm)
    if dry_run:
        return
    run_forwarded("setup-agent-tooling.sh", [])


@app.command("test-dbs")
def test_dbs(
    dry_run: Annotated[bool, typer.Option("--dry-run", help="Preview setup without running")] = False,
    confirm: Annotated[str | None, typer.Option("--confirm", help="Confirm token from preview run")] = None,
) -> None:
    """Create or refresh test databases."""
    lines = [
        "SETUP TEST DATABASES",
        "Creates or refreshes configured test databases.",
    ]
    _preview("st setup test-dbs", lines, dry_run, confirm)
    if dry_run:
        return
    run_forwarded("setup-test-dbs.sh", [])
