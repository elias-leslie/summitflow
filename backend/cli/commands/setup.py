"""Canonical setup command surface."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from typing import Annotated

import typer

from app.project_identity import list_project_identities
from app.utils.shared_paths import get_repo_root

from ..details import emit_result_or_details
from ..lib.confirm_token import confirm_gate
from ..lib.service_ops import load_project, sync_systemd_units

app = typer.Typer(
    help=(
        "Host, service, browser, tooling, and test database setup through st. "
        "Use dry-run/confirm gates for host changes. Browser setup defaults to "
        "isolated SF_BROWSER_HOST targets; server-local installs are debug-only."
    )
)


def _preview(command: str, lines: list[str], dry_run: bool, confirm: str | None) -> None:
    if dry_run:
        print("\n".join(lines))
        return
    confirm_gate(command.replace(" ", "-"), confirm, lines, command)


def _bin_dir() -> Path:
    return Path(os.environ.get("BIN_DIR", str(Path.home() / "bin"))).expanduser()


def _remove_legacy_links() -> None:
    summitflow_scripts = get_repo_root() / "scripts"
    forced_legacy = {"web-research", "dt", "db", "a-term-start.sh", "a-term-stop.sh"}
    for name in (
        "rebuild.sh",
        "commit.sh",
        "start.sh",
        "status.sh",
        "stop.sh",
        "shutdown.sh",
        "backup.sh",
        "backup-all.sh",
        "restore.sh",
        "setup-services.sh",
        "update-gh.sh",
        "web-research",
        "dt",
        "db",
        "a-term-start.sh",
        "a-term-stop.sh",
    ):
        path = _bin_dir() / name
        if not path.exists() and not path.is_symlink():
            continue
        target = path.resolve() if path.is_symlink() else path
        remove_regular = name in forced_legacy and path.is_file()
        remove_symlink = path.is_symlink() and (str(target).startswith(str(summitflow_scripts)) or name in forced_legacy)
        if remove_regular or remove_symlink:
            path.unlink()
            print(f"removed legacy link {path}")
    sf_browser = Path.home() / ".local" / "bin" / "sf-browser"
    if sf_browser.is_symlink() and str(sf_browser.resolve()).startswith(str(summitflow_scripts)):
        sf_browser.unlink()
        print(f"removed legacy link {sf_browser}")


def _remove_scripts_path_from_rc() -> None:
    marker = str(get_repo_root() / "scripts")
    for rc_path in (Path.home() / ".bashrc", Path.home() / ".zshrc", Path.home() / ".profile"):
        if not rc_path.exists():
            continue
        lines = rc_path.read_text().splitlines()
        filtered = [line for line in lines if marker not in line]
        if filtered != lines:
            rc_path.write_text("\n".join(filtered) + "\n")
            print(f"removed legacy scripts PATH from {rc_path}")


def _link_st() -> None:
    _bin_dir().mkdir(parents=True, exist_ok=True)
    st_source = get_repo_root() / "backend" / ".venv" / "bin" / "st"
    if st_source.exists():
        target = _bin_dir() / "st"
        if target.exists() or target.is_symlink():
            target.unlink()
        target.symlink_to(st_source)
        print(f"linked st -> {st_source}")


def _project_ids() -> list[str]:
    ids: list[str] = []
    for identity in list_project_identities():
        project = identity.get("project")
        if not isinstance(project, dict):
            continue
        project_id = project.get("id")
        if isinstance(project_id, str) and project_id:
            ids.append(project_id)
    return sorted(set(ids))


def _run(command: list[str], *, cwd: Path | None = None) -> int:
    result = subprocess.run(
        command,
        cwd=cwd,
        text=True,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    name = "setup-" + "-".join(Path(part).name for part in command[:3] if part and not part.startswith("-"))
    emit_result_or_details(cwd or get_repo_root(), name, "SETUP", result)
    return result.returncode


def _ensure_repo(repo_url: str, target_dir: Path, *, update_existing: bool) -> None:
    if (target_dir / ".git").exists():
        if update_existing:
            if _run(["git", "fetch", "--all", "--tags"], cwd=target_dir) != 0:
                raise typer.Exit(1)
            if _run(["git", "pull", "--ff-only"], cwd=target_dir) != 0:
                raise typer.Exit(1)
        print(f"config repo present: {target_dir}")
        return
    if target_dir.exists():
        typer.echo(f"Target exists but is not a git repo: {target_dir}", err=True)
        raise typer.Exit(1)
    if _run(["git", "clone", repo_url, str(target_dir)]) != 0:
        raise typer.Exit(1)
    print(f"cloned {repo_url} -> {target_dir}")


def _install_global_cli(package_name: str, command_name: str) -> None:
    if _run(["npm", "install", "-g", package_name]) != 0:
        raise typer.Exit(1)
    if not shutil.which(command_name):
        typer.echo(f"Installed {package_name} but {command_name} is not on PATH", err=True)
        raise typer.Exit(1)


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
    _link_st()
    _remove_legacy_links()
    _remove_scripts_path_from_rc()
    for project_id in _project_ids():
        sync_systemd_units(load_project(project_id))


@app.command()
def browser(
    version: Annotated[str | None, typer.Argument(help="Optional agent-browser npm version")] = None,
    dry_run: Annotated[bool, typer.Option("--dry-run", help="Preview setup without running")] = False,
    confirm: Annotated[str | None, typer.Option("--confirm", help="Confirm token from preview run")] = None,
    allow_server_install: Annotated[
        bool,
        typer.Option("--allow-server-install", help="Install local browser tooling on this server for explicit debug-only use"),
    ] = False,
) -> None:
    """Configure browser tooling without silently installing server-local browsers."""
    lines = [
        "SETUP BROWSER",
        f"Version: {version or 'latest'}",
        "Default path: configure SF_BROWSER_HOST to an isolated VM or connector endpoint.",
        "Server-local agent-browser install is debug-only and requires --allow-server-install.",
    ]
    _preview("st setup browser", lines, dry_run, confirm)
    if dry_run:
        return
    if not allow_server_install and os.environ.get("ST_SETUP_BROWSER_ALLOW_SERVER_INSTALL", "").strip() != "1":
        typer.echo(
            "Refusing server-local browser install. Set SF_BROWSER_HOST to an isolated browser VM/connector, "
            "or rerun with --allow-server-install for explicit debug-only use.",
            err=True,
        )
        raise typer.Exit(2)
    managed_dir = Path.home() / ".local" / "share" / "agent-browser-managed"
    managed_dir.mkdir(parents=True, exist_ok=True)
    package = f"agent-browser@{version}" if version else "agent-browser@latest"
    code = _run(["npm", "install", package], cwd=managed_dir)
    if code != 0:
        raise typer.Exit(code)
    target = Path.home() / ".local" / "bin" / "agent-browser"
    target.parent.mkdir(parents=True, exist_ok=True)
    source = managed_dir / "node_modules" / ".bin" / "agent-browser"
    if target.exists() or target.is_symlink():
        target.unlink()
    target.symlink_to(source)
    _remove_legacy_links()
    print(f"browser command: st browser (agent-browser -> {source})")


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
    for command in ("git", "node", "npm", "python3", "curl", "jq", "tmux"):
        if not shutil.which(command):
            typer.echo(f"Missing required command: {command}", err=True)
            raise typer.Exit(1)
    claude_repo = os.environ.get("CLAUDE_CONFIG_REPO", "git@github.com:elias-leslie/claude-config.git")
    codex_repo = os.environ.get("CODEX_CONFIG_REPO", "git@github.com:elias-leslie/codex-config.git")
    claude_home = Path(os.environ.get("CLAUDE_HOME_DIR", str(Path.home() / ".claude"))).expanduser()
    codex_home = Path(os.environ.get("CODEX_HOME_DIR", str(Path.home() / ".codex"))).expanduser()
    update_existing = os.environ.get("UPDATE_EXISTING_CONFIGS") == "1"
    _ensure_repo(claude_repo, claude_home, update_existing=update_existing)
    _ensure_repo(codex_repo, codex_home, update_existing=update_existing)
    codex_wrapper = Path(os.environ.get("CODEX_WRAPPER_SOURCE", str(codex_home / "bin" / "codex"))).expanduser()
    if not codex_wrapper.exists():
        typer.echo(f"Expected Codex wrapper: {codex_wrapper}", err=True)
        raise typer.Exit(1)
    _bin_dir().mkdir(parents=True, exist_ok=True)
    codex_target = _bin_dir() / "codex"
    if codex_target.exists() or codex_target.is_symlink():
        codex_target.unlink()
    codex_target.symlink_to(codex_wrapper)
    if os.environ.get("INSTALL_CLAUDE_CLI", "1") == "1":
        _install_global_cli("@anthropic-ai/claude-code", "claude")
    if os.environ.get("INSTALL_CODEX_CLI", "1") == "1":
        _install_global_cli("@openai/codex", "codex")
    _link_st()
    _remove_legacy_links()
    print("agent tooling prerequisites present; st is canonical operator CLI")


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
    use_docker = _run(["docker", "compose", "-p", "summitflow-stack", "ps", "--status", "running", "-q"]) == 0
    base = ["docker", "compose", "-p", "summitflow-stack", "exec", "-T", "postgres"] if use_docker else ["sudo", "-u", "postgres"]
    for db_name, owner in (
        ("summitflow_test", "summitflow_app"),
        ("agent_hub_test", "agent_hub_app"),
        ("portfolio_ai_test", "portfolio_app"),
    ):
        _run([*base, "createdb", "-U", "admin", db_name] if use_docker else [*base, "createdb", db_name])
        _run([*base, "psql", "-U", "admin", "-c", f"GRANT ALL PRIVILEGES ON DATABASE {db_name} TO {owner};"] if use_docker else [*base, "psql", "-c", f"GRANT ALL PRIVILEGES ON DATABASE {db_name} TO {owner};"])
        _run([*base, "psql", "-U", "admin", "-d", db_name, "-c", f"GRANT ALL ON SCHEMA public TO {owner};"] if use_docker else [*base, "psql", "-d", db_name, "-c", f"GRANT ALL ON SCHEMA public TO {owner};"])
    print("test databases ready")
