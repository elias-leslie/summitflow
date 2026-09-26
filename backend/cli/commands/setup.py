"""Canonical setup command surface."""

from __future__ import annotations

import fcntl
import json
import os
import re
import shutil
import subprocess
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Annotated
from uuid import uuid4

import typer

from app.project_identity import list_project_identities
from app.utils.shared_paths import get_repo_root

from ..details import emit_result_or_details
from ..lib import browser_policy, browser_support
from ..lib.confirm_token import confirm_gate
from ..lib.service_ops import load_project, sync_systemd_units

app = typer.Typer(
    help=(
        "Host, service, browser, tooling, and test database setup through st. "
        "Use dry-run/confirm gates for host changes. Browser setup defaults to "
        "isolated ST_BROWSER_HOST targets; server-local installs are debug-only."
    )
)

_QUALIFIED_BROWSER_VERSION = "0.38.1"
_QUALIFIED_BROWSER_INTEGRITY = "sha512-k58FCz0yUOCANoNkMiqJe+H2y6r6sUZazqXsWF+MYq1iRC42PjtLcBoag6SSTOD/FRQppvPDvE5HDYEhclvnhw=="


def _browser_release_paths() -> tuple[Path, Path, Path]:
    share = Path.home() / ".local" / "share"
    return share / "agent-browser-managed", share / "agent-browser-releases", share / "agent-browser-releases" / "previous"


def _browser_binary(directory: Path) -> Path:
    return directory / "node_modules" / ".bin" / "agent-browser"


def _browser_version(binary: Path) -> str | None:
    try:
        result = subprocess.run([str(binary), "--version"], text=True, capture_output=True, timeout=8, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return None
    match = re.fullmatch(r"agent-browser (\d+\.\d+\.\d+)\s*", result.stdout) if result.returncode == 0 else None
    return match.group(1) if match else None


def _verified_release(directory: Path, version: str) -> bool:
    try:
        lock = json.loads((directory / "package-lock.json").read_text(encoding="utf-8"))
        package = lock["packages"]["node_modules/agent-browser"]
    except (OSError, ValueError, KeyError, TypeError):
        return False
    return (
        package.get("version") == version
        and package.get("integrity") == _QUALIFIED_BROWSER_INTEGRITY
        and _browser_version(_browser_binary(directory)) == version
    )


def _stage_browser_release(root: Path, version: str) -> Path:
    release = root / version
    if release.exists():
        if not _verified_release(release, version):
            raise RuntimeError(f"Existing browser release failed integrity/version verification: {release}")
        return release
    staging = root / f".staging-{uuid4().hex}"
    staging.mkdir()
    try:
        if _run(["npm", "install", "--prefix", str(staging), "--save-exact", "--no-audit", "--no-fund", f"agent-browser@{version}"], cwd=staging):
            raise RuntimeError("Pinned npm install failed")
        if not _verified_release(staging, version):
            raise RuntimeError("Staged browser release failed integrity/version verification")
        os.replace(staging, release)
        return release
    finally:
        if staging.exists():
            shutil.rmtree(staging)


def _atomic_link(link: Path, target: Path) -> None:
    candidate = link.with_name(f".{link.name}-{uuid4().hex}")
    candidate.symlink_to(target)
    try:
        os.replace(candidate, link)
    finally:
        candidate.unlink(missing_ok=True)


def _switch_browser_release(stable_binary: Path, release_binary: Path) -> Path | None:
    """Atomically change the ST executable while retaining the old package."""
    if stable_binary.exists() or stable_binary.is_symlink():
        if not stable_binary.is_symlink():
            raise RuntimeError("Current browser executable is not a symlink; preserve it before promotion")
        previous = stable_binary.resolve(strict=True)
        if not previous.is_file():
            raise RuntimeError("Current browser executable is unavailable")
    else:
        previous = None
    stable_binary.parent.mkdir(parents=True, exist_ok=True)
    _atomic_link(stable_binary, release_binary)
    return previous


def _restore_browser_release(stable_binary: Path, previous: Path | None) -> None:
    if previous is not None:
        _atomic_link(stable_binary, previous)
    else:
        stable_binary.unlink(missing_ok=True)


@contextmanager
def _browser_release_lock(root: Path):
    root.mkdir(parents=True, exist_ok=True)
    with (root / ".promotion.lock").open("a+") as handle:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeError("Another managed browser promotion is in progress") from exc
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _default_local_ai_session_active() -> bool:
    runtime = Path(os.environ.get("XDG_RUNTIME_DIR", "").strip() or f"/tmp/st-browser-{os.getuid()}")
    directory = runtime / "agent-browser"
    session = browser_policy.DEFAULT_LOCAL_AI_SESSION
    socket = directory / f"{session}.sock"
    pid_file = directory / f"{session}.pid"
    if not socket.exists():
        return False
    try:
        pid = int(pid_file.read_text(encoding="utf-8").strip())
        command = (Path("/proc") / str(pid) / "cmdline").read_bytes()
    except (OSError, ValueError):
        return True  # A live socket with unreadable ownership is not safe to replace.
    return b"agent-browser" in command


def _verify_managed_browser(version: str) -> str:
    """Use the real ST route, isolated from the default AI browser session."""
    with tempfile.TemporaryDirectory(prefix="st-browser-release-") as temp:
        directory = Path(temp)
        env = os.environ.copy()
        for key in ("AGENT_BROWSER_BIN", "AGENT_BROWSER_PROFILE", "AGENT_BROWSER_SESSION", "AGENT_BROWSER_SOCKET_DIR", "AGENT_BROWSER_CONFIG", "ST_BROWSER_LOCAL_AI_VISIBLE", "ST_BROWSER_LOCAL_AI_MINIMIZED"):
            env.pop(key, None)
        env.update(
            ST_BROWSER_TARGET="local-ai",
            ST_BROWSER_LOCAL_AI_SESSION=f"st-release-{uuid4().hex[:12]}",
            ST_BROWSER_LOCAL_AI_PROFILE=str(directory / "profile"),
            AGENT_BROWSER_SOCKET_DIR=str(directory / "sockets"),
            ST_BROWSER_CHECK_RESPONSIVE="0",
        )
        inventory = subprocess.run(["st", "browser", "inventory", "--json"], env=env, text=True, capture_output=True, timeout=15, check=False)
        if inventory.returncode:
            raise RuntimeError("Managed browser inventory failed after switch")
        try:
            rows = json.loads(inventory.stdout)["runtimes"]
        except (ValueError, KeyError, TypeError) as exc:
            raise RuntimeError("Managed browser inventory returned invalid evidence") from exc
        if not any(row.get("id") == "agent-browser" and row.get("installed_version") == version and row.get("installed_status") == "observed" for row in rows if isinstance(row, dict)):
            raise RuntimeError("ST still resolves a different agent-browser version")
        try:
            check = subprocess.run(
                ["st", "browser", "check", "data:text/html,<title>managed-browser-release</title><p>ready</p>", str(directory / "check.png")],
                env=env, text=True, capture_output=True, timeout=45, check=False,
            )
            if check.returncode or "BROWSER_CHECK:OK" not in check.stdout or not (directory / "check.png").is_file():
                raise RuntimeError(f"Managed browser check failed after switch (rc={check.returncode})")
        finally:
            subprocess.run(["st", "browser", "close"], env=env, text=True, capture_output=True, timeout=15, check=False)
        return check.stdout.strip()


def _browser_release_receipt(root: Path, *, version: str, previous: Path | None, check: str, rollback: bool) -> Path:
    receipt = root / f"promotion-{uuid4().hex}.json"
    candidate = receipt.with_suffix(".tmp")
    try:
        candidate.write_text(json.dumps({
            "schema_version": 1,
            "action": "rollback" if rollback else "promote",
            "version": version,
            "previous_executable": str(previous) if previous else None,
            "qualified_integrity": None if rollback else _QUALIFIED_BROWSER_INTEGRITY,
            "managed_check": check,
        }, indent=2) + "\n", encoding="utf-8")
        os.replace(candidate, receipt)
    finally:
        candidate.unlink(missing_ok=True)
    return receipt


def _promote_local_browser(version: str, *, rollback: bool) -> None:
    managed, root, previous_link = _browser_release_paths()
    if root.is_symlink() or managed.is_symlink():
        raise RuntimeError("Managed browser roots must be directories, not symlinks")
    with _browser_release_lock(root):
        for key in ("AGENT_BROWSER_BIN", "AGENT_BROWSER_SOCKET_DIR", "ST_BROWSER_LOCAL_AI_SESSION"):
            if os.environ.get(key, "").strip():
                raise RuntimeError(f"Unset {key} before managed promotion; it overrides the default ST session")
        if _default_local_ai_session_active():
            raise RuntimeError("Default local-AI browser session is active; close it through `st browser close` before promotion")
        selected = browser_support.agent_browser_bin("")
        current_binary = _browser_binary(managed)
        if selected:
            selected_path = Path(selected).absolute()
            if selected_path != current_binary.absolute():
                linked = selected_path.readlink() if selected_path.is_symlink() else None
                link_target = (selected_path.parent / linked).absolute() if linked is not None and not linked.is_absolute() else linked
                if link_target != current_binary.absolute():
                    raise RuntimeError(f"ST resolves an external browser executable: {selected}")
        if rollback:
            if not previous_link.is_symlink():
                raise RuntimeError("No previous managed browser release is recorded")
            release_binary = previous_link.resolve(strict=True)
            if not release_binary.is_file() or not any(parent in release_binary.parents for parent in (root, managed)):
                raise RuntimeError("Previous browser executable is outside managed roots or unavailable")
            version = _browser_version(release_binary) or ""
            if not version:
                raise RuntimeError("Previous browser release has no verified version")
        else:
            release = _stage_browser_release(root, version)
            release_binary = _browser_binary(release).resolve(strict=True)
        if current_binary.is_file() and current_binary.resolve() == release_binary:
            _verify_managed_browser(version)
            print(f"managed agent-browser already current: {version}")
            return
        old = _switch_browser_release(current_binary, release_binary)
        try:
            check = _verify_managed_browser(version)
            if old is not None:
                _atomic_link(previous_link, old)
            receipt = _browser_release_receipt(root, version=version, previous=old, check=check, rollback=rollback)
        except Exception:
            _restore_browser_release(current_binary, old)
            raise
        print(f"managed agent-browser: {version}; previous executable: {old or 'none'}; receipt: {receipt}")


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
    legacy_browser = Path.home() / ".local" / "bin" / ("sf" + "-" + "browser")
    if legacy_browser.is_symlink() and str(legacy_browser.resolve()).startswith(str(summitflow_scripts)):
        legacy_browser.unlink()
        print(f"removed legacy link {legacy_browser}")


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
    st_source = get_repo_root() / "scripts" / "st"
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
    promote_local_ai: Annotated[
        bool,
        typer.Option("--promote-local-ai", help="Promote the qualified exact version for managed local-AI use"),
    ] = False,
    rollback_local_ai: Annotated[
        bool,
        typer.Option("--rollback-local-ai", help="Restore the previous managed local-AI browser release"),
    ] = False,
) -> None:
    """Configure browser tooling without silently installing server-local browsers."""
    if promote_local_ai or rollback_local_ai:
        if (promote_local_ai and rollback_local_ai) or allow_server_install:
            raise typer.BadParameter("Choose one managed promotion/rollback action without --allow-server-install")
        if promote_local_ai and version != _QUALIFIED_BROWSER_VERSION:
            raise typer.BadParameter(f"Managed promotion requires qualified exact version {_QUALIFIED_BROWSER_VERSION}")
        if rollback_local_ai and version is not None:
            raise typer.BadParameter("Rollback uses the recorded previous release; omit VERSION")
        managed, root, previous = _browser_release_paths()
        command = f"st setup browser {version} --promote-local-ai" if promote_local_ai else "st setup browser --rollback-local-ai"
        action_line = (
            "Stage exact npm package and verify registry integrity and binary version."
            if promote_local_ai else "Use the recorded previous release after verifying its binary version."
        )
        lines = [
            "MANAGED LOCAL-AI BROWSER RELEASE",
            f"Action: {'promote ' + str(version) if promote_local_ai else 'rollback to recorded previous release'}",
            f"Stable ST executable: {_browser_binary(managed)}",
            f"Versioned releases: {root}",
            f"Previous release pointer: {previous}",
            action_line,
            "Switch the stable path, then verify through isolated st browser inventory/check; restore the prior path on failure.",
            "The executable symlink switch is atomic; the prior package remains available for rollback.",
            "The default local-AI session must be closed first; this command never closes it automatically.",
        ]
        _preview(command, lines, dry_run, confirm)
        if dry_run:
            return
        try:
            _promote_local_browser(version or "", rollback=rollback_local_ai)
        except (OSError, RuntimeError, subprocess.TimeoutExpired) as exc:
            typer.echo(f"Managed browser release failed: {exc}", err=True)
            raise typer.Exit(1) from None
        return
    lines = [
        "SETUP BROWSER",
        f"Version: {version or 'latest'}",
        "Default path: configure ST_BROWSER_HOST to an isolated VM or connector endpoint.",
        "Server-local agent-browser install is debug-only and requires --allow-server-install.",
    ]
    _preview("st setup browser", lines, dry_run, confirm)
    if dry_run:
        return
    if not allow_server_install and os.environ.get("ST_SETUP_BROWSER_ALLOW_SERVER_INSTALL", "").strip() != "1":
        typer.echo(
            "Refusing server-local browser install. Set ST_BROWSER_HOST to an isolated browser VM/connector, "
            "or rerun with --allow-server-install for explicit debug-only use.",
            err=True,
        )
        raise typer.Exit(2)
    managed_dir = Path.home() / ".local" / "share" / "agent-browser-managed"
    _, release_root, previous = _browser_release_paths()
    current = _browser_binary(managed_dir)
    if previous.is_symlink() or (current.is_symlink() and release_root in current.resolve().parents):
        typer.echo("Refusing debug install over a managed local-AI release; use --promote-local-ai or --rollback-local-ai.", err=True)
        raise typer.Exit(2)
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
    project: Annotated[str | None, typer.Option("--project", help="Set up only this project's test database")] = None,
) -> None:
    """Create or refresh test databases."""
    targets = {
        "summitflow": ("summitflow_test", "summitflow_app"),
        "agent-hub": ("agent_hub_test", "agent_hub_app"),
        "portfolio-ai": ("portfolio_ai_test", "portfolio_app"),
        "jobinator-4000": ("jobinator_test", "jobinator_app"),
    }
    if project and project not in targets:
        raise typer.BadParameter("No test database configured for this project")
    selected = [targets[project]] if project else list(targets.values())[:3]
    lines = [
        "SETUP TEST DATABASES",
        *(f"Create test database {name}, owned by {owner}" for name, owner in selected),
    ]
    _preview("st setup test-dbs", lines, dry_run, confirm)
    if dry_run:
        return
    from app.tasks.backup_native_infra import _find_compose_container
    container = _find_compose_container("postgres")
    use_docker = container is not None
    base = ["docker", "exec", "-i", container] if container else ["sudo", "-u", "postgres"]
    for db_name, owner in selected:
        _run([*base, "createdb", "-U", "admin", "-O", owner, db_name] if use_docker else [*base, "createdb", "-O", owner, db_name])
        _run([*base, "psql", "-U", "admin", "-c", f"GRANT ALL PRIVILEGES ON DATABASE {db_name} TO {owner};"] if use_docker else [*base, "psql", "-c", f"GRANT ALL PRIVILEGES ON DATABASE {db_name} TO {owner};"])
        _run([*base, "psql", "-U", "admin", "-d", db_name, "-c", f"GRANT ALL ON SCHEMA public TO {owner};"] if use_docker else [*base, "psql", "-d", db_name, "-c", f"GRANT ALL ON SCHEMA public TO {owner};"])
    print("test databases ready")
