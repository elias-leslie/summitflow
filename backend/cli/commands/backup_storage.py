"""Backup storage backend management CLI commands."""

from __future__ import annotations

from typing import Annotated, Any

import httpx
import typer

from ..client import APIError, STClient
from ..output import handle_api_error, output_json
from ..output_context import OutputContext

app = typer.Typer(help="Storage backend management")
LONG_RUNNING_TIMEOUT = httpx.Timeout(30.0, read=None)


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


def _api_post(
    path: str, data: dict[str, Any] | None = None, *, timeout: float | httpx.Timeout = 30.0,
) -> Any:
    url = f"{_get_base_url()}/{path.lstrip('/')}"
    resp = httpx.post(url, json=data or {}, timeout=timeout)
    if resp.status_code >= 400:
        raise APIError(resp.status_code, resp.text)
    return resp.json()


def _api_put(path: str, data: dict[str, Any]) -> Any:
    url = f"{_get_base_url()}/{path.lstrip('/')}"
    resp = httpx.put(url, json=data, timeout=30.0)
    if resp.status_code >= 400:
        raise APIError(resp.status_code, resp.text)
    return resp.json()


def _api_delete(path: str) -> Any:
    url = f"{_get_base_url()}/{path.lstrip('/')}"
    resp = httpx.delete(url, timeout=30.0)
    if resp.status_code >= 400:
        raise APIError(resp.status_code, resp.text)
    return resp.json()


def _restic_settings(
    engine: str | None, local_repository: str | None, remote_repository: str | None,
    local_password_file: str | None, remote_password_file: str | None,
    rclone_config: str | None, key_directory: str | None, lock_directory: str | None,
) -> dict[str, Any]:
    """Collect only explicitly supplied repository settings and file references."""
    if engine is not None and engine not in {"native", "restic"}:
        raise typer.BadParameter("--engine must be 'native' or 'restic'")
    values = {
        "engine": engine, "restic_local_repository": local_repository,
        "restic_remote_repository": remote_repository, "restic_local_password_file": local_password_file,
        "restic_remote_password_file": remote_password_file, "restic_rclone_config": rclone_config,
        "restic_key_directory": key_directory, "restic_lock_directory": lock_directory,
    }
    return {key: value for key, value in values.items() if value is not None}


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
                engine = "|engine:restic" if isinstance(b.get("config"), dict) and b["config"].get("engine") == "restic" else ""
                print(f"{b['id']}|{b['name']}|{b['backend_type']}|{test_str}{default}{engine}")
        else:
            output_json(backends)
    except APIError as e:
        handle_api_error(e)


@app.command("add")
def add_backend(
    ctx: typer.Context,
    name: Annotated[str | None, typer.Option("--name", "-n", help="Backend name")] = None,
    backend_type: Annotated[str, typer.Option("--type", help="Backend type: smb or local")] = "smb",
    host: Annotated[str | None, typer.Option("--host", help="SMB host")] = None,
    share: Annotated[str | None, typer.Option("--share", help="SMB share name")] = None,
    user: Annotated[str | None, typer.Option("--user", "-u", help="SMB username")] = None,
    password: Annotated[str | None, typer.Option("--password", "-p", help="SMB password (or prompted)")] = None,
    root_path: Annotated[str | None, typer.Option("--root-path", help="Local storage root path")] = None,
    path: Annotated[str | None, typer.Option("--path", help="SMB path prefix")] = None,
    default: Annotated[bool | None, typer.Option("--default/--no-default", help="Set as default backend (Restic defaults to nondefault)")] = None,
    interactive: Annotated[bool, typer.Option("--interactive/--no-interactive", "-i", help="Interactive mode")] = True,
    engine: Annotated[str | None, typer.Option("--engine", help="Backup engine: native or restic")] = None,
    local_repository: Annotated[str | None, typer.Option("--local-repository", help="Absolute Restic local repository path")] = None,
    remote_repository: Annotated[str | None, typer.Option("--remote-repository", help="Bounded independent Restic remote reference")] = None,
    local_password_file: Annotated[str | None, typer.Option("--local-password-file", help="Private local password-file reference")] = None,
    remote_password_file: Annotated[str | None, typer.Option("--remote-password-file", help="Private remote password-file reference")] = None,
    rclone_config: Annotated[str | None, typer.Option("--rclone-config", help="Private rclone config-file reference")] = None,
    key_directory: Annotated[str | None, typer.Option("--key-directory", help="Approved private credential directory")] = None,
    lock_directory: Annotated[str | None, typer.Option("--lock-directory", help="Absolute repository lock directory")] = None,
) -> None:
    """Add a new storage backend. Interactive by default."""
    try:
        backend_type = backend_type.lower()
        if backend_type not in {"smb", "local"}:
            typer.echo("Error: --type must be 'smb' or 'local'", err=True)
            raise typer.Exit(1)
        if engine == "restic" and key_directory is None:
            from app.services.backup_keys import backup_key_directory

            key_directory = str(backup_key_directory())
        restic = _restic_settings(
            engine, local_repository, remote_repository, local_password_file,
            remote_password_file, rclone_config, key_directory, lock_directory,
        )
        if engine == "restic":
            if backend_type != "local" or password is not None:
                raise typer.BadParameter("Restic requires --type local and password-file references")
            if not local_repository or not local_password_file or not key_directory:
                raise typer.BadParameter("Restic requires --local-repository, --local-password-file and --key-directory")
        elif any(key.startswith("restic_") for key in restic):
            raise typer.BadParameter("Restic settings require --engine restic")

        if engine != "restic" and interactive and ((backend_type == "smb" and not host) or (backend_type == "local" and not root_path)):
            typer.echo(f"Configure {backend_type.upper()} Storage Backend")
            typer.echo("─" * 35)
            name = name or typer.prompt(
                "Backend name", default="Local Backup" if backend_type == "local" else "NAS Backup"
            )
            if backend_type == "local":
                root_path = typer.prompt("Local root path")
            else:
                host = typer.prompt("SMB host (IP or hostname)")
                share = share or typer.prompt("Share name", default="backups")
                user = user or typer.prompt("Username", default="backup-svc")
                password = password or typer.prompt("Password", hide_input=True)
            path = path or typer.prompt("Path prefix", default="project-backups")

        if backend_type == "smb" and (not host or not share):
            typer.echo("Error: --host and --share are required", err=True)
            raise typer.Exit(1)
        if backend_type == "local" and not root_path and engine != "restic":
            typer.echo("Error: --root-path is required for local storage", err=True)
            raise typer.Exit(1)

        config: dict[str, Any]
        if engine == "restic":
            config = restic
            if root_path:
                config["root_path"] = root_path
        elif backend_type == "local":
            config = {"root_path": root_path}
        else:
            config = {"host": host, "share": share}
            if user:
                config["user"] = user
            if password:
                config["password"] = password
        if path:
            config["path"] = path
        if engine == "native":
            config["engine"] = engine

        result = _api_post("backup-storage", {
            "name": name or (f"Restic {local_repository}" if engine == "restic" else f"Local {root_path}" if backend_type == "local" else f"SMB {host}"),
            "backend_type": backend_type,
            "config": config,
            "is_default": default if default is not None else engine != "restic",
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
        if not result.get("success"):
            raise typer.Exit(1)
    except APIError as e:
        handle_api_error(e)


@app.command("update")
def update_backend(
    ctx: typer.Context,
    backend_id: Annotated[str, typer.Argument(help="Existing backend ID")],
    offsite_gio_uri: Annotated[
        str | None,
        typer.Option("--offsite-gio-uri", help="Existing GIO destination URI"),
    ] = None,
    offsite_transport: Annotated[str | None, typer.Option("--offsite-transport", help="Native offsite transport: gio or rclone")] = None,
    offsite_rclone_remote: Annotated[str | None, typer.Option("--offsite-rclone-remote", help="Bounded Drive folder, REMOTE:FOLDER")] = None,
    offsite_rclone_config: Annotated[str | None, typer.Option("--offsite-rclone-config", help="Private managed rclone config-file reference")] = None,
    offsite_rclone_root_id: Annotated[str | None, typer.Option("--offsite-rclone-root-id", help="Pin the approved Drive destination folder ID")] = None,
    offsite_rclone_permanent_expiry: Annotated[bool | None, typer.Option("--offsite-permanent-expiry/--offsite-trash-expiry", help="Permanently expire aged managed archives only in the pinned native Drive folder")] = None,
    engine: Annotated[str | None, typer.Option("--engine", help="Backup engine: native or restic")] = None,
    local_repository: Annotated[str | None, typer.Option("--local-repository", help="Absolute Restic local repository path")] = None,
    remote_repository: Annotated[str | None, typer.Option("--remote-repository", help="Bounded independent Restic remote reference")] = None,
    local_password_file: Annotated[str | None, typer.Option("--local-password-file", help="Private local password-file reference")] = None,
    remote_password_file: Annotated[str | None, typer.Option("--remote-password-file", help="Private remote password-file reference")] = None,
    rclone_config: Annotated[str | None, typer.Option("--rclone-config", help="Private rclone config-file reference")] = None,
    key_directory: Annotated[str | None, typer.Option("--key-directory", help="Approved private credential directory")] = None,
    lock_directory: Annotated[str | None, typer.Option("--lock-directory", help="Absolute repository lock directory")] = None,
    default: Annotated[bool | None, typer.Option("--default/--no-default", help="Change the default backend selection")] = None,
) -> None:
    """Update offsite or pilot repository settings on an existing backend."""
    settings = _restic_settings(
        engine, local_repository, remote_repository, local_password_file,
        remote_password_file, rclone_config, key_directory, lock_directory,
    )
    if offsite_transport is not None and offsite_transport not in {"gio", "rclone"}:
        raise typer.BadParameter("--offsite-transport must be 'gio' or 'rclone'")
    for key, value in (("offsite_transport", offsite_transport), ("offsite_rclone_remote", offsite_rclone_remote), ("offsite_rclone_config", offsite_rclone_config), ("offsite_rclone_root_id", offsite_rclone_root_id), ("offsite_rclone_permanent_expiry", offsite_rclone_permanent_expiry)):
        if value is not None:
            settings[key] = value
    if offsite_gio_uri is None and not settings and default is None:
        typer.echo("Error: provide storage settings to update", err=True)
        raise typer.Exit(1)
    try:
        existing = _api_get(f"backup-storage/{backend_id}")
        config = existing.get("config")
        merged = dict(config) if isinstance(config, dict) else {}
        merged.update(settings)
        if offsite_gio_uri is not None:
            merged["offsite_gio_uri"] = offsite_gio_uri
        fields: dict[str, Any] = {"config": merged}
        if default is not None:
            fields["is_default"] = default
        result = _api_put(f"backup-storage/{backend_id}", fields)
        if ctx.obj.is_compact:
            restic = merged.get("engine") == "restic"
            offsite = merged.get("restic_remote_repository") if restic else merged.get("offsite_rclone_remote") if merged.get("offsite_transport") == "rclone" else merged.get("offsite_gio_uri")
            engine_label = "|engine:restic" if restic else ""
            print(f"UPDATED {result['id']}{engine_label}|offsite:{'configured' if offsite else 'unconfigured'}")
        else:
            output_json(result)
    except APIError as e:
        handle_api_error(e)


@app.command("initialize")
def initialize_repository(
    ctx: typer.Context,
    backend_id: Annotated[str, typer.Argument(help="Restic backend ID")],
    local_only: Annotated[bool, typer.Option("--local-only", help="Initialize only the configured local repository")] = False,
) -> None:
    """Explicitly initialize a configured pilot repository."""
    try:
        result = _api_post(
            f"backup-storage/{backend_id}/initialize?local_only={str(local_only).lower()}",
            timeout=LONG_RUNNING_TIMEOUT,
        )
        output_json(result)
    except APIError as e:
        handle_api_error(e)


@app.command("status")
def repository_status(
    ctx: typer.Context,
    backend_id: Annotated[str, typer.Argument(help="Restic backend ID")],
) -> None:
    """Read repository readiness and durable verification status."""
    try:
        output_json(_api_get(f"backup-storage/{backend_id}/repository"))
    except APIError as e:
        handle_api_error(e)


@app.command("maintenance")
def repository_maintenance(
    ctx: typer.Context,
    backend_id: Annotated[str, typer.Argument(help="Restic backend ID")],
    preview: Annotated[bool, typer.Option("--preview/--apply", help="Preview maintenance by default; --apply executes it")] = True,
) -> None:
    """Preview or explicitly apply repository-scoped maintenance."""
    try:
        result = _api_post(
            f"backup-storage/{backend_id}/maintenance?dry_run={str(preview).lower()}",
            timeout=LONG_RUNNING_TIMEOUT,
        )
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
