"""Backup storage backend management CLI commands."""

from __future__ import annotations

from typing import Annotated, Any

import httpx
import typer

from ..client import APIError, STClient
from ..output import handle_api_error, output_json
from ..output_context import OutputContext

app = typer.Typer(help="Storage backend management")


@app.callback()
def storage_callback(ctx: typer.Context) -> None:
    """Initialize context if not set."""
    if ctx.obj is None:
        ctx.obj = OutputContext()


def _get_base_url() -> str:
    return STClient().base_url


def _api_get(path: str) -> Any:
    url = f"{_get_base_url()}/{path.lstrip('/')}"
    resp = httpx.get(url, timeout=30.0)
    if resp.status_code >= 400:
        raise APIError(resp.status_code, resp.text)
    return resp.json()


def _api_post(path: str, data: dict[str, Any] | None = None) -> Any:
    url = f"{_get_base_url()}/{path.lstrip('/')}"
    resp = httpx.post(url, json=data or {}, timeout=30.0)
    if resp.status_code >= 400:
        raise APIError(resp.status_code, resp.text)
    return resp.json()


def _api_delete(path: str) -> Any:
    url = f"{_get_base_url()}/{path.lstrip('/')}"
    resp = httpx.delete(url, timeout=30.0)
    if resp.status_code >= 400:
        raise APIError(resp.status_code, resp.text)
    return resp.json()


@app.command("list")
def list_backends(ctx: typer.Context) -> None:
    """Show configured storage backends."""
    try:
        backends = _api_get("backup-storage")
        if ctx.obj.is_compact:
            if not backends:
                print("NO_BACKENDS")
                return
            for b in backends:
                default = " [default]" if b.get("is_default") else ""
                test_ok = b.get("last_test_ok")
                test_str = "untested" if test_ok is None else ("OK" if test_ok else "FAIL")
                print(f"{b['id']}|{b['name']}|{b['backend_type']}|{test_str}{default}")
        else:
            output_json(backends)
    except APIError as e:
        handle_api_error(e)


@app.command("add")
def add_backend(
    ctx: typer.Context,
    name: Annotated[str | None, typer.Option("--name", "-n", help="Backend name")] = None,
    host: Annotated[str | None, typer.Option("--host", help="SMB host")] = None,
    share: Annotated[str | None, typer.Option("--share", help="SMB share name")] = None,
    user: Annotated[str | None, typer.Option("--user", "-u", help="SMB username")] = None,
    password: Annotated[str | None, typer.Option("--password", "-p", help="SMB password (or prompted)")] = None,
    path: Annotated[str | None, typer.Option("--path", help="SMB path prefix")] = None,
    default: Annotated[bool, typer.Option("--default/--no-default", help="Set as default backend")] = True,
    interactive: Annotated[bool, typer.Option("--interactive/--no-interactive", "-i", help="Interactive mode")] = True,
) -> None:
    """Add a new storage backend. Interactive by default."""
    try:
        if interactive and not host:
            typer.echo("Configure SMB Storage Backend")
            typer.echo("─" * 35)
            name = name or typer.prompt("Backend name", default="NAS Backup")
            host = typer.prompt("SMB host (IP or hostname)")
            share = share or typer.prompt("Share name", default="backups")
            user = user or typer.prompt("Username", default="backup-svc")
            password = password or typer.prompt("Password", hide_input=True)
            path = path or typer.prompt("Path prefix", default="project-backups")

        if not host or not share:
            typer.echo("Error: --host and --share are required", err=True)
            raise typer.Exit(1)

        config: dict[str, Any] = {"host": host, "share": share}
        if user:
            config["user"] = user
        if password:
            config["password"] = password
        if path:
            config["path"] = path

        result = _api_post("backup-storage", {
            "name": name or f"SMB {host}",
            "backend_type": "smb",
            "config": config,
            "is_default": default,
        })

        if ctx.obj.is_compact:
            print(f"CREATED {result['id']}|{result['name']}")
        else:
            output_json(result)

        # Auto-test
        typer.echo("Testing connection...")
        test_result = _api_post(f"backup-storage/{result['id']}/test")
        if test_result.get("success"):
            typer.echo("Connection: OK")
        else:
            typer.echo(f"Connection: FAILED — {test_result.get('message', 'unknown error')}")
    except APIError as e:
        handle_api_error(e)


@app.command("test")
def test_backend(
    ctx: typer.Context,
    backend_id: Annotated[str | None, typer.Argument(help="Backend ID (tests default if omitted)")] = None,
) -> None:
    """Test storage backend connectivity."""
    try:
        if not backend_id:
            status = _api_get("backup-storage/status")
            backend_id = status.get("default_backend_id")
            if not backend_id:
                typer.echo("No default backend configured. Use 'st backup storage add' to set one up.")
                raise typer.Exit(1)

        result = _api_post(f"backup-storage/{backend_id}/test")
        if ctx.obj.is_compact:
            status = "OK" if result.get("success") else "FAIL"
            print(f"TEST {status}|{result.get('message', '')}")
        else:
            output_json(result)
    except APIError as e:
        handle_api_error(e)


@app.command("remove")
def remove_backend(
    ctx: typer.Context,
    backend_id: Annotated[str, typer.Argument(help="Backend ID to remove")],
    force: Annotated[bool, typer.Option("--force", "-f", help="Skip confirmation")] = False,
) -> None:
    """Remove a storage backend."""
    try:
        if not force:
            backend = _api_get(f"backup-storage/{backend_id}")
            confirm = typer.confirm(f"Remove backend '{backend.get('name', backend_id)}'?")
            if not confirm:
                raise typer.Abort()

        result = _api_delete(f"backup-storage/{backend_id}")
        if ctx.obj.is_compact:
            print(f"REMOVED {backend_id}")
        else:
            output_json(result)
    except APIError as e:
        handle_api_error(e)
