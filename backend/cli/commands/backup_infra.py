"""Infrastructure backup CLI commands."""

from __future__ import annotations

from typing import Annotated

import httpx
import typer

from ..client import APIError, STClient
from ..output import handle_api_error, output_json
from ..output_context import OutputContext
from .backup_formatters import output_backups

app = typer.Typer(help="Infrastructure backup management")


@app.callback()
def infra_callback(ctx: typer.Context) -> None:
    """Initialize context if not set."""
    if ctx.obj is None:
        ctx.obj = OutputContext()


def _get_base_url() -> str:
    return STClient().base_url


def _ensure_infra_source() -> None:
    """Ensure infrastructure backup source exists."""
    url = f"{_get_base_url()}/backup-sources/infrastructure"
    resp = httpx.get(url, timeout=30.0)
    if resp.status_code == 404:
        httpx.post(
            f"{_get_base_url()}/backup-sources",
            json={
                "id": "infrastructure",
                "name": "Infrastructure",
                "path": "/",
                "source_type": "infrastructure",
            },
            timeout=30.0,
        )


@app.command("create")
def create_infra_backup(
    ctx: typer.Context,
    note: Annotated[str | None, typer.Option("--note", "-n", help="Backup note")] = None,
    keep_local: Annotated[bool, typer.Option("--keep-local", help="Keep local copy")] = False,
) -> None:
    """Trigger an infrastructure backup (pg_dumpall + configs)."""
    try:
        _ensure_infra_source()
        url = f"{_get_base_url()}/backup-sources/infrastructure/backups"
        resp = httpx.post(
            url,
            json={"note": note, "keep_local": keep_local},
            timeout=30.0,
        )
        if resp.status_code >= 400:
            raise APIError(resp.status_code, resp.text)
        result = resp.json()

        if ctx.obj.is_compact:
            print(f"QUEUED infrastructure|{result.get('message', 'Backup queued')}")
        else:
            output_json(result)
    except APIError as e:
        handle_api_error(e)


@app.command("list")
def list_infra_backups(
    ctx: typer.Context,
    limit: Annotated[int, typer.Option("--limit", "-l", help="Max results")] = 20,
    status: Annotated[str | None, typer.Option("--status", "-s", help="Filter by status")] = None,
) -> None:
    """List infrastructure backups."""
    try:
        url = f"{_get_base_url()}/backup-sources/infrastructure/backups?limit={limit}"
        if status:
            url += f"&status={status}"
        resp = httpx.get(url, timeout=30.0)
        if resp.status_code == 404:
            if ctx.obj.is_compact:
                print("NO_INFRA_SOURCE — run 'st backup infra create' first")
            else:
                output_json({"error": "No infrastructure source. Run 'st backup infra create' first."})
            return
        if resp.status_code >= 400:
            raise APIError(resp.status_code, resp.text)
        result = resp.json()
        backups = result.get("backups", [])
        total = result.get("total", len(backups))
        output_backups(ctx.obj, backups, total)
    except APIError as e:
        handle_api_error(e)


@app.command("status")
def infra_status(ctx: typer.Context) -> None:
    """Show infrastructure backup health."""
    try:
        url = f"{_get_base_url()}/backups/health"
        resp = httpx.get(url, timeout=30.0)
        if resp.status_code >= 400:
            raise APIError(resp.status_code, resp.text)
        health = resp.json()
        infra_sources = [s for s in health.get("sources", []) if s.get("source_type") == "infrastructure"]

        if ctx.obj.is_compact:
            if not infra_sources:
                print("NO_INFRA_SOURCE")
            else:
                for s in infra_sources:
                    print(
                        f"{s['source_id']}|{s['health_status']}|"
                        f"failures_7d:{s.get('failure_count_7d', 0)}|"
                        f"last_success:{s.get('last_success_at', 'never')}"
                    )
        else:
            output_json(infra_sources if infra_sources else {"status": "no infrastructure source configured"})
    except APIError as e:
        handle_api_error(e)
