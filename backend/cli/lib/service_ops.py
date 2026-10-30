"""Native service lifecycle operations for `st service`."""

from __future__ import annotations

import json
import os
import pwd
import re
import socket
import subprocess
import tempfile
import time
import tomllib
import uuid
from collections.abc import Callable, Mapping, Sequence
from contextlib import nullcontext
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

import httpx
import psycopg

from app import runtime_deployment
from app.project_identity import (
    get_project_identity,
    get_project_identity_root,
    get_project_lifecycles,
    list_project_identities,
)
from app.utils.heavy_work import heavy_work
from app.utils.shared_paths import get_repo_root

from ..client import APIError, STClient
from ..details import display_path, emit_result_or_details, summary_hint, write_details
from . import host_monitor_deploy, migration_env, service_release
from .monitor_store_migration import (
    MigrationResult,
    MonitorMigrationDeferred,
    MonitorMigrationFailed,
    migrate_stopped_store,
    retain_restart_interlock,
    update_restart_receipt,
)

HOST_MONITOR_HELPER = Path("/usr/local/sbin/summitflow-host-monitor-deploy")
RUNTIME_USERS = frozenset({"", "svc", "broker", "agent"})
# Shared infrastructure a deploy checks first; runtime.infra in project.identity.json narrows it.
INFRA = ("postgres", "hatchet")


class ServiceError(RuntimeError):
    """Raised for service lifecycle failures."""


@dataclass(frozen=True)
class ProjectServices:
    project_id: str
    root: Path
    backend_service: str
    frontend_service: str
    default_workers: tuple[str, ...]
    optional_workers: tuple[str, ...]
    backend_port: int
    frontend_port: int
    backend_dir: Path
    frontend_dir: Path
    health_endpoint: str
    # Long-lived units the project owns but a normal rebuild never touches;
    # only `--worker <unit>` renders and restarts one.
    manual_workers: tuple[str, ...] = ()
    backend_extras: tuple[str, ...] = ()
    host_config_root: Path | None = None
    durable_data_root: Path | None = None
    release_install: str = ""
    runtime_user: str = ""
    infra: tuple[str, ...] = INFRA
    source_repo: Path | None = None
    source_sha: str = ""
    deployment: runtime_deployment.ProxmoxDeployment | None = None

    @property
    def git_root(self) -> Path:
        """The repository acceptance and release read: a pinned mirror, else the checkout."""
        return self.source_repo or self.root

    @property
    def all_services(self) -> tuple[str, ...]:
        return tuple(
            svc
            for svc in (
                self.backend_service,
                self.frontend_service,
                *self.default_workers,
                *self.optional_workers,
            )
            if svc
        )

    def workers(self, *, include_all: bool) -> tuple[str, ...]:
        if include_all:
            return (*self.default_workers, *self.optional_workers)
        return self.default_workers


def activated_service(unit: str) -> str:
    """The paired ``X.service`` a ``X.socket``/``X.timer`` activates, else ``""``."""
    stem, dot, kind = unit.rpartition(".")
    return f"{stem}.service" if dot and stem and kind in {"socket", "timer"} else ""


def canonical_unit(unit: str) -> str:
    """Apply systemd's implicit service suffix at unit identity boundaries."""
    suffixes = (".service", ".socket", ".device", ".mount", ".automount", ".swap",
                ".target", ".path", ".timer", ".slice", ".scope")
    return f"{unit}.service" if unit and not unit.endswith(suffixes) else unit


def _as_str_list(value: Any) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    return tuple(item for item in value if isinstance(item, str) and item)


def _dict_value(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def runtime_source_dirs(runtime: Mapping[str, Any], root: Path) -> tuple[Path, Path]:
    """Resolve identity ``runtime.backend_dir``/``frontend_dir`` beneath ``root``."""
    backend_subdir = str(runtime.get("backend_dir") or "backend")
    frontend_subdir = str(runtime.get("frontend_dir") or "frontend")
    return (
        root if backend_subdir == "." else root / backend_subdir,
        root if frontend_subdir == "." else root / frontend_subdir,
    )


def load_project(project_id: str) -> ProjectServices:
    identity = get_project_identity(project_id)
    root_raw = get_project_identity_root(project_id)
    if not identity or not root_raw:
        raise ServiceError(f"Unknown project: {project_id}")
    return _project_from_identity(identity, project_id, Path(root_raw))


def _project_from_identity(identity: Mapping[str, Any], project_id: str, root: Path) -> ProjectServices:
    """Parse runtime metadata independently of mutable workspace discovery."""
    project = _dict_value(identity.get("project"))
    runtime = _dict_value(identity.get("runtime"))
    try:
        deployment = runtime_deployment.parse_deployment(runtime.get("deployment"))
    except runtime_deployment.DeploymentError as exc:
        raise ServiceError(str(exc)) from exc
    services = _dict_value(identity.get("services"))
    extras = runtime.get("backend_extras", [])
    if not isinstance(extras, list) or any(not isinstance(extra, str) or not extra.strip() for extra in extras):
        raise ServiceError("runtime.backend_extras must be a list of nonempty extra names")
    release_install = runtime.get("release_install") or ""
    if not isinstance(release_install, str) or Path(release_install).is_absolute() or ".." in Path(release_install).parts:
        raise ServiceError("runtime.release_install must be a path inside the project")
    runtime_user = runtime.get("runtime_user") or ""
    if runtime_user not in RUNTIME_USERS:
        raise ServiceError("runtime.runtime_user must be svc, broker or agent")
    infra = runtime.get("infra", list(INFRA))
    if not isinstance(infra, list) or any(item not in INFRA for item in infra):
        raise ServiceError(f"runtime.infra must list only {', '.join(INFRA)}")
    canonical_id = str(project.get("id") or project_id)
    backend_dir, frontend_dir = runtime_source_dirs(runtime, root)
    manual_workers = _as_str_list(services.get("manual_workers"))
    managed = {canonical_unit(unit) for unit in (
        str(services.get("backend") or ""), str(services.get("frontend") or ""),
        *_as_str_list(services.get("default_workers")), *_as_str_list(services.get("optional_workers"))) if unit}
    if any(canonical_unit(unit) in managed for unit in manual_workers):
        raise ServiceError("services.manual_workers must not repeat a backend, frontend or rebuild-managed worker")
    return ProjectServices(
        project_id=canonical_id,
        root=root,
        backend_service=str(services.get("backend") or ""),
        frontend_service=str(services.get("frontend") or ""),
        default_workers=_as_str_list(services.get("default_workers")),
        optional_workers=_as_str_list(services.get("optional_workers")),
        manual_workers=manual_workers,
        backend_port=int(runtime.get("backend_port") or 0),
        frontend_port=int(runtime.get("frontend_port") or 0),
        backend_dir=backend_dir,
        frontend_dir=frontend_dir,
        health_endpoint=str(runtime.get("health_endpoint") or "/health"),
        backend_extras=tuple(dict.fromkeys(_as_str_list(extras))),
        host_config_root=root,
        durable_data_root=root / "data",
        release_install=release_install,
        runtime_user=runtime_user,
        infra=tuple(infra),
        deployment=deployment,
    )


def _pinned_project(project: ProjectServices, identity: Any) -> ProjectServices:
    """Bind the candidate identity to the project admitted by the deploy gate."""
    if not isinstance(identity, dict) or not all(isinstance(identity.get(key), dict)
                                               for key in ("project", "runtime", "services")):
        raise ServiceError("Pinned project identity requires project, runtime and services objects")
    runtime, services = identity["runtime"], identity["services"]
    try:
        deployment = runtime_deployment.parse_deployment(runtime.get("deployment"))
    except runtime_deployment.DeploymentError as exc:
        raise ServiceError(f"Invalid pinned project identity: {exc}") from exc
    if deployment != project.deployment:
        raise ServiceError("Pinned project identity deployment does not match the catalog target")
    if identity["project"].get("id") != project.project_id:
        raise ServiceError("Pinned project identity does not match the requested canonical project id")
    user = runtime.get("runtime_user", "")
    if not isinstance(user, str) or user not in RUNTIME_USERS or user != project.runtime_user:
        raise ServiceError("Pinned project identity runtime user does not match the admitted deploy gate")
    for key in ("backend_port", "frontend_port"):
        port = runtime.get(key, 0)
        if type(port) is not int or not 0 <= port <= 65535 or port != getattr(project, key):
            raise ServiceError(f"Pinned project identity {key} does not match the admitted port")
    for key, expected in (("backend", project.backend_service), ("frontend", project.frontend_service),
                          ("default_workers", project.default_workers), ("optional_workers", project.optional_workers),
                          ("manual_workers", project.manual_workers)):
        actual = services.get(key, [] if isinstance(expected, tuple) else "")
        if isinstance(expected, tuple):
            if not isinstance(actual, list) or any(not isinstance(item, str) or not item for item in actual):
                raise ServiceError(f"Pinned project identity services.{key} must list unit names")
            actual = tuple(canonical_unit(unit) for unit in actual)
            expected = tuple(canonical_unit(unit) for unit in expected)
        elif isinstance(actual, str):
            actual, expected = canonical_unit(actual), canonical_unit(expected)
        if actual != expected:
            raise ServiceError(f"Pinned project identity services.{key} does not match the admitted units")
    for key in ("backend_dir", "frontend_dir"):
        directory = runtime.get(key, key.removesuffix("_dir"))
        if not isinstance(directory, str) or Path(directory).is_absolute() or ".." in Path(directory).parts:
            raise ServiceError(f"Pinned project identity runtime.{key} must stay inside the source")
    endpoint = runtime.get("health_endpoint", "/health")
    if not isinstance(endpoint, str) or not endpoint.startswith("/"):
        raise ServiceError("Pinned project identity health endpoint must be an absolute URL path")
    try:
        candidate = _project_from_identity(identity, project.project_id, project.root)
    except (ServiceError, TypeError, ValueError) as exc:
        raise ServiceError(f"Invalid pinned project identity: {exc}") from exc
    return replace(candidate, host_config_root=project.host_config_root or project.root,
                   durable_data_root=project.durable_data_root or project.root / "data")


def use_source_repo(project: ProjectServices, mirror: Path, sha: str) -> ProjectServices:
    """Read the project's git state at ``sha`` from ``mirror`` instead of the owner's checkout.

    The commit is checked out detached and clean in a private clone under the
    service state, so acceptance and release see exactly that commit.
    """
    if not re.fullmatch(r"[0-9a-f]{40}", sha):
        raise ServiceError("--sha must be a full 40-character lowercase commit id")
    clone = service_release.source_checkout_path(project.project_id)
    git = ["git", "-c", "core.fsmonitor=false", "-C", str(clone)]
    steps = [
        *([["git", "init", "-q", str(clone)]] if not (clone / ".git").exists() else []),
        [*git, "fetch", "-q", "--no-tags", "--force", str(mirror), "+refs/heads/*:refs/remotes/mirror/*"],
        [*git, "checkout", "-q", "--force", "--detach", sha],
        [*git, "clean", "-qfd"],
    ]
    clone.parent.mkdir(parents=True, exist_ok=True)
    for step in steps:
        result = subprocess.run(step, capture_output=True, text=True, check=False)
        if result.returncode != 0:
            raise ServiceError(f"could not check out {sha[:12]} from {mirror}: {result.stderr.strip()}")
    # Read the Git object itself: an identity symlink or an ignored file left in
    # the reusable checkout must never supply runtime metadata.
    result = subprocess.run([*git, "show", f"{sha}:project.identity.json"],
                            capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise ServiceError("Pinned project identity is missing from the requested commit")
    try:
        identity = json.loads(result.stdout)
    except ValueError as exc:
        raise ServiceError("Pinned project identity is not valid JSON") from exc
    return replace(_pinned_project(project, identity), source_repo=clone, source_sha=sha)


def install_clone_dependencies(project: ProjectServices) -> int:
    """Install the project's own tools into the pinned clone, so local acceptance can run them.

    A fresh private clone has no venv or node_modules, and acceptance runs the
    project's pytest, type, lint and frontend tools (they are skipped or fail
    as not installed otherwise). The release build installs again, from the
    accepted copy. Ignored directories survive the next ``git clean -qfd``, so
    later deploys only update.
    """
    if project.source_repo is None:
        return 0
    clone = project_at_source(project, project.source_repo)
    if (code := sync_backend(clone)) != 0:
        return code
    plan = frontend_install_plan(clone.frontend_dir, clone.root)
    return release_install(plan.command, plan.manager, clone.root, cwd=plan.cwd) if plan else 0


def project_ids(*, include_inactive: bool = False) -> list[str]:
    ids: list[str] = []
    from app.storage.projects import testing_project_ids

    if include_inactive:
        testing = set()
    else:
        try:
            testing = testing_project_ids()
        except psycopg.OperationalError:
            # Service recovery must remain possible while the database is down.
            testing = set()
    identities = list_project_identities()
    candidate_ids = [project.get("id") for identity in identities
                     if isinstance(project := identity.get("project"), dict)
                     and isinstance(project.get("id"), str) and project.get("id")]
    lifecycles = get_project_lifecycles(candidate_ids, allow_unavailable=True) if not include_inactive else {}
    for identity in identities:
        project = _dict_value(identity.get("project"))
        project_id = project.get("id")
        if (isinstance(project_id, str) and project_id
                and (include_inactive or (lifecycles[project_id] == "active" and project_id not in testing))):
            ids.append(project_id)
    return sorted(set(ids))


def _detail_name(command: list[str]) -> str:
    parts = [Path(part).name for part in command[:3] if part and not part.startswith("-")]
    raw = "-".join(parts) or "command"
    return "service-" + "".join(char if char.isalnum() or char in "-_" else "-" for char in raw).strip("-")


def _command_env(command: list[str], env: dict[str, str] | None = None) -> dict[str, str] | None:
    """Find this user's existing systemd bus in non-login agent shells."""
    if not command or Path(command[0]).name not in {"systemctl", "systemd-run"}:
        return env
    resolved = dict(os.environ if env is None else env)
    runtime = Path(resolved.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}")
    bus = runtime / "bus"
    if runtime.is_dir() and runtime.stat().st_uid == os.getuid() and bus.is_socket():
        resolved.setdefault("XDG_RUNTIME_DIR", str(runtime))
        resolved.setdefault("DBUS_SESSION_BUS_ADDRESS", f"unix:path={bus}")
    return resolved


def run(
    command: list[str],
    *,
    cwd: Path | None = None,
    env: dict[str, str] | None = None,
    quiet_success: bool = False,
    _heavy: bool = False,
) -> int:
    options: dict[str, Any] = dict(cwd=cwd, env=_command_env(command, env), text=True,
                   capture_output=True, encoding="utf-8", errors="replace", check=False)
    if _heavy:
        with heavy_work("managed service build/dependencies") as work:
            result = work.run(command, **options)
    else:
        result = subprocess.run(command, **options)
    if result.returncode != 0 or not quiet_success:
        emit_result_or_details(cwd or get_repo_root(), _detail_name(command), "SERVICE", result)
    return result.returncode


def capture(command: list[str], *, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, cwd=cwd, env=_command_env(command), text=True, capture_output=True, check=False)


def systemctl(*args: str) -> subprocess.CompletedProcess[str]:
    return capture(["systemctl", "--user", *args])


def system_systemctl(*args: str) -> subprocess.CompletedProcess[str]:
    """Read system-manager state without requiring service mutation privileges."""
    return capture(["systemctl", *args])


def _manager(service: str):
    return system_systemctl if canonical_unit(service) == host_monitor_deploy.UNIT else systemctl


def _service_command(service: str, *args: str) -> list[str]:
    service = canonical_unit(service)
    if service == host_monitor_deploy.UNIT:
        return ["sudo", "-n", "/usr/bin/systemctl", *args, service]
    return ["systemctl", "--user", *args, service]


def service_state(service: str) -> str:
    if not service:
        return "missing"
    result = _manager(service)("is-active", service)
    return (result.stdout or result.stderr).strip() or "unknown"


def service_exists(service: str) -> bool:
    return _manager(service)("cat", service).returncode == 0


def observed_service_states(project: ProjectServices) -> dict[str, str]:
    """Observe legacy units missing from this manager through the runtime API.

    An absent caller unit does not prove the runtime is stopped. Installed local
    units and explicit runtime targets keep their existing observation path.
    """
    units = dict.fromkeys(unit for service in project.all_services
                          for unit in (service, activated_service(service)) if unit)
    if project.deployment:
        try:
            rows = runtime_deployment.unit_states(project.deployment, list(units))
        except runtime_deployment.DeploymentError:
            rows = {}
        return {unit: rows.get(unit, {}).get("ActiveState", "unknown") for unit in units}
    states = {unit: service_state(unit) for unit in units}
    if project.runtime_user:
        return states
    missing = [unit for unit, state in states.items()
               if state not in {"active", "failed"} and not service_exists(unit)]
    if not missing:
        return states
    states.update(dict.fromkeys(missing, "unknown"))
    try:
        with STClient(require_project=False, timeout=10.0) as client:
            rows = client.get(client._global_url("/docker/status"))
        if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
            return states
    except (APIError, httpx.HTTPError, ValueError, OSError):
        return states
    for unit in missing:
        matches = [row for row in rows
                   if row.get("manager") == "systemd" and row.get("name") == canonical_unit(unit)]
        if len(matches) == 1:
            states[unit] = _runtime_row_state(matches[0])
    return states


def _runtime_row_state(row: Mapping[str, Any]) -> str:
    """Translate one Runtime API ``/docker/status`` systemd row into an ActiveState."""
    state = row.get("state")
    if not isinstance(state, str):
        return "unknown"
    if state == "stopped":
        status = row.get("status")
        if isinstance(status, str) and status.startswith("systemd "):
            observed = status.removeprefix("systemd ").partition(" ")[0]
            if observed in {"inactive", "failed", "deactivating"}:
                return observed
        return "unknown"
    if state == "running" and row.get("health") == "unhealthy":
        return "unhealthy"
    return {"running": "active", "starting": "activating", "failed": "failed"}.get(state, "unknown")


def _release_references_for_manager(
    releases_root: Path,
    manager: Callable[..., subprocess.CompletedProcess[str]],
) -> set[Path] | None:
    """Return release references for one complete systemd manager inventory.

    ``None`` means the inventory was incomplete and cleanup must be skipped.
    Listing unit files includes inactive services; listing loaded units also covers
    transient services that have no persistent unit file.
    """
    listings = (
        manager(
            "list-unit-files",
            "--type=service",
            "--no-legend",
            "--no-pager",
            "--plain",
        ),
        manager(
            "list-units",
            "--type=service",
            "--all",
            "--no-legend",
            "--no-pager",
            "--plain",
        ),
    )
    if any(result.returncode != 0 for result in listings):
        return None
    units = {
        line.split(maxsplit=1)[0]
        for result in listings
        for line in result.stdout.splitlines()
        if line.strip() and line.split(maxsplit=1)[0].endswith(".service")
    }
    try:
        release_prefix = str(releases_root.resolve(strict=True)) + "/"
    except OSError:
        return None
    build_pattern = re.compile(re.escape(release_prefix) + r'([^/\s"\';]+)')
    references: set[Path] = set()
    templates = {unit for unit in units if "@.service" in unit}
    units -= templates
    if templates:
        template_result = manager("cat", "--no-pager", *sorted(templates))
        if template_result.returncode != 0:
            return None
        if release_prefix in template_result.stdout:
            matches = build_pattern.findall(template_result.stdout)
            if not matches or any(
                not re.fullmatch(r"[0-9a-f]{32}", item) for item in matches
            ):
                return None
            references.update(releases_root / item for item in matches)
    if not units:
        return references
    result = manager(
        "show",
        "--property=Id,Names,LoadState,FragmentPath,DropInPaths,ExecStart,WorkingDirectory,Environment",
        *sorted(units),
    )
    if result.returncode != 0 or not result.stdout.strip():
        return None
    blocks = result.stdout.strip().split("\n\n")
    ordered_units = sorted(units)
    if len(blocks) != len(ordered_units):
        return None
    for requested_unit, block in zip(ordered_units, blocks, strict=True):
        properties = dict(
            line.split("=", 1) for line in block.splitlines() if "=" in line
        )
        unit = properties.get("Id", "")
        names = set(properties.get("Names", "").split())
        if (
            (unit != requested_unit and requested_unit not in names)
            or properties.get("LoadState") is None
        ):
            return None
        if release_prefix not in block:
            continue
        matches = build_pattern.findall(block)
        if not matches or any(not re.fullmatch(r"[0-9a-f]{32}", item) for item in matches):
            return None
        references.update(releases_root / item for item in matches)
    return references


def manual_worker_release_references(project: ProjectServices, releases_root: Path) -> set[Path] | None:
    """Releases running manual workers started from, which may predate ``current``.

    Read from each main process's working directory, since a re-rendered unit
    file no longer names the release its process runs from. ``None`` fails closed.
    """
    references: set[Path] = set()
    if not project.manual_workers:
        return references
    try:
        prefix = releases_root.resolve(strict=True)
    except OSError:
        return None
    for unit in project.manual_workers:
        if not (pid := _service_main_pid(unit)):
            continue
        try:
            cwd = (_PROC_ROOT / str(pid) / "cwd").resolve(strict=True)
        except OSError:
            return None
        if cwd.is_relative_to(prefix) and cwd != prefix:
            references.add(releases_root / cwd.relative_to(prefix).parts[0])
    return references


def release_references_for_services(releases_root: Path) -> set[Path] | None:
    """Return references from both user and system services, or fail closed."""
    user_references = _release_references_for_manager(releases_root, systemctl)
    system_references = _release_references_for_manager(releases_root, system_systemctl)
    if user_references is None or system_references is None:
        return None
    return user_references | system_references


def credstore_root(project: ProjectServices) -> Path:
    if project.runtime_user in {"", "owner"}:
        return Path.home() / ".config" / "credstore"
    return Path(f"/etc/credstore.{project.runtime_user}")


def credstore_units(text: str, project: ProjectServices) -> str:
    """Point a unit at the root-owned credential dir instead of the owner's home secrets."""
    store = credstore_root(project)
    text = text.replace("%h/.config/credstore/", f"{store}/")
    lines: list[str] = []
    for line in text.splitlines(keepends=True):
        if line.startswith("EnvironmentFile=") and line.rstrip().endswith("%h/.env.local"):
            line = f"{line.partition('=')[0]}={'-' if line.startswith('EnvironmentFile=-') else ''}{store}/{project.project_id}/env\n"
        if not line.startswith("EnvironmentFile=") or line not in lines:
            lines.append(line)
    return "".join(lines)


def sync_systemd_units(project: ProjectServices, *, manual: Sequence[str] = ()) -> int:
    """Render the project's rebuild-managed units, or only the named ``manual`` workers."""
    if project.deployment:
        print(f"[service] refusing local unit installation for {project.deployment.label}")
        return 1
    systemd_dir = Path(os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config"))) / "systemd" / "user"
    systemd_dir.mkdir(parents=True, exist_ok=True)
    synced = False
    summitflow_root = str(project.root if project.project_id == "summitflow" else get_repo_root())
    durable_data_root = project.durable_data_root or project.root / "data"
    host_config_root = project.host_config_root or project.root
    units = dict.fromkeys(canonical_unit(name) for unit in (manual or project.all_services)
                          for name in (unit, activated_service(unit)) if name)
    # Required services and manual daemons must come back after a host reboot;
    # optional workers keep whatever enablement the owner chose.
    required = {canonical_unit(unit) for unit in
                manual or (project.backend_service, project.frontend_service, *project.default_workers)}
    boot: list[str] = []
    for service in units:
        if service == host_monitor_deploy.UNIT:
            continue
        template = project.root / "scripts" / "systemd" / service
        if not template.exists():
            continue
        text = template.read_text()
        text = text.replace("__PROJECT_ROOT__", str(project.root))
        text = text.replace("__SUMMITFLOW_ROOT__", summitflow_root)
        text = text.replace("__SUMMITFLOW_DATA_ROOT__", str(durable_data_root))
        text = text.replace("__SUMMITFLOW_HOST_CONFIG_ROOT__", str(host_config_root))
        if project.runtime_user:
            text = credstore_units(text, project)
        (systemd_dir / service).write_text(text)
        print(f"[service] synced {service}")
        synced = True
        if service in required and not activated_service(service) and "[Install]" in text:
            boot.append(service)
    if synced and run(["systemctl", "--user", "daemon-reload"]) != 0:
        return 1
    if boot:
        return run(["systemctl", "--user", "enable", *boot])
    return 0



def run_release_install(project: ProjectServices, *, development_root: Path, source_commit: str) -> int:
    """Run the project's own unprivileged installer from the accepted release source.

    For projects whose units run from a release they install themselves
    (identity ``runtime.release_install``). The installer gets the development
    checkout and the accepted commit so it can export that exact commit.
    """
    if not project.release_install:
        return 0
    root = project.root.resolve()
    script = (root / project.release_install).resolve()
    if not script.is_relative_to(root) or not script.is_file() or not os.access(script, os.X_OK):
        print(f"[service] release installer missing or not executable: {project.release_install}")
        return 1
    print(f"[service] installing release with {project.release_install}")
    env = {**os.environ, "ST_DEVELOPMENT_ROOT": str(development_root), "ST_SOURCE_COMMIT": source_commit}
    return run([str(script)], cwd=root, env=env, _heavy=True)

def _port_open(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.25)
        return sock.connect_ex(("127.0.0.1", port)) == 0


_SS_PID_RE = re.compile(r"pid=(\d+)")
_PROC_ROOT = Path("/proc")
_CGROUP_ROOT = Path("/sys/fs/cgroup")


def _port_listener_pids(port: int) -> set[int]:
    result = capture(["ss", "-ltnp", f"( sport = :{port} )"])
    return {int(match.group(1)) for match in _SS_PID_RE.finditer(result.stdout)}


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def _terminate_pids(pids: set[int], *, timeout: float = 10.0) -> None:
    own_pid = os.getpid()
    targets = {pid for pid in pids if pid > 0 and pid != own_pid}
    for pid in sorted(targets):
        capture(["kill", str(pid)])
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not any(_pid_alive(pid) for pid in targets):
            return
        time.sleep(0.25)
    for pid in sorted(targets):
        if _pid_alive(pid):
            capture(["kill", "-9", str(pid)])


def _kill_port(port: int) -> bool:
    if port <= 0 or not _port_open(port):
        return True
    _terminate_pids(_port_listener_pids(port))
    deadline = time.monotonic() + 10.0
    while time.monotonic() < deadline:
        if not _port_open(port):
            return True
        refreshed = _port_listener_pids(port)
        if refreshed:
            _terminate_pids(refreshed, timeout=0.5)
        time.sleep(0.25)
    return not _port_open(port)


def _systemctl_value(service: str, key: str) -> str:
    return _manager(service)("show", service, "-p", key, "--value").stdout.strip()


def _service_main_pid(service: str) -> int:
    raw = _systemctl_value(service, "MainPID")
    try:
        return int(raw)
    except ValueError:
        return 0


def _runtime_uid(project: ProjectServices) -> int:
    try:
        user = project.runtime_user
        uid = pwd.getpwnam(user).pw_uid if user else os.getuid()
    except (KeyError, OSError, ValueError) as exc:
        raise ServiceError("runtime user is unavailable") from exc
    if os.getuid() != uid:
        raise ServiceError("caller does not own the expected user service manager")
    return uid


def _attest_process(pid: int, uid: int, cgroup: str, source_root: Path | None, *, source_sha: str = "") -> None:
    """Check kernel process identity; a systemd property alone is not evidence."""
    process = _PROC_ROOT / str(pid)
    try:
        status = dict(line.split(":", 1) for line in (process / "status").read_text().splitlines() if ":" in line)
        groups = (process / "cgroup").read_text().splitlines()
        actual_group = next((line[3:] for line in groups if line.startswith("0::")), "")
        if status.get("Uid", "").split() != [str(uid)] * 4:
            raise ServiceError(f"PID {pid} does not belong to the runtime user")
        if actual_group != cgroup and not actual_group.startswith(cgroup + "/"):
            raise ServiceError(f"PID {pid} is outside the expected unit cgroup")
        if source_root is not None and not (process / "cwd").resolve(strict=True).is_relative_to(source_root.resolve(strict=True)):
            raise ServiceError(f"PID {pid} is outside the expected release source")
        if source_sha:
            # Inspect only this protocol field; process environment values are
            # never included in errors or deployment evidence.
            commits = [item for item in (process / "environ").read_bytes().split(b"\0")
                       if item.startswith(b"SUMMITFLOW_SOURCE_SHA=")]
            if commits != [f"SUMMITFLOW_SOURCE_SHA={source_sha}".encode()]:
                raise ServiceError(f"PID {pid} is outside the expected installed release")
    except OSError as exc:
        raise ServiceError(f"cannot attest runtime PID {pid}") from exc


def _desktop_application_cgroup(pid: int, uid: int) -> str:
    """Corroborate GNOME's PID-named scope for a service's reclassified MainPID.

    Electron can move its window owner out of the service cgroup. Admit only
    that PID's active transient application scope in the same user manager;
    release, UID and listener checks still run against its actual cgroup.
    """
    try:
        groups = (_PROC_ROOT / str(pid) / "cgroup").read_text().splitlines()
        group = next((line[3:] for line in groups if line.startswith("0::")), "")
        parent = f"/user.slice/user-{uid}.slice/user@{uid}.service/app.slice/"
        scope = group.removeprefix(parent)
        if not group.startswith(parent) or not re.fullmatch(rf"app-[^/]+-{pid}\.scope", scope):
            raise ServiceError(f"PID {pid} is outside the expected unit cgroup")
        result = systemctl("show", scope, "--property=Id,LoadState,ActiveState,ControlGroup,Transient,InvocationID")
        properties = dict(line.split("=", 1) for line in result.stdout.splitlines() if "=" in line)
        members = (_CGROUP_ROOT / group.lstrip("/") / "cgroup.procs").read_text().splitlines()
        if (result.returncode or properties.get("Id") != scope or properties.get("LoadState") != "loaded"
                or properties.get("ActiveState") != "active" or properties.get("ControlGroup") != group
                or properties.get("Transient") != "yes"
                or not re.fullmatch(r"[0-9a-f]{32}", properties.get("InvocationID", "")) or str(pid) not in members):
            raise ServiceError(f"cannot attest application scope for PID {pid}")
        return group
    except OSError as exc:
        raise ServiceError(f"cannot attest application scope for PID {pid}") from exc


def _unit_runtime(project: ProjectServices, service: str, *, require_source: bool) -> tuple[int, int, str]:
    service = canonical_unit(service)
    uid = _runtime_uid(project)
    try:
        result = systemctl("show", service, "--property=Id,LoadState,ActiveState,MainPID,ControlGroup,WorkingDirectory")
    except OSError as exc:
        raise ServiceError("user service manager is unavailable") from exc
    properties = dict(line.split("=", 1) for line in result.stdout.splitlines() if "=" in line)
    pid = properties.get("MainPID", "")
    cgroup = properties.get("ControlGroup", "")
    manager_group = f"/user.slice/user-{uid}.slice/user@{uid}.service/"
    if (result.returncode or properties.get("Id") != service or properties.get("LoadState") != "loaded"
            or properties.get("ActiveState") != "active" or not pid.isdecimal() or int(pid) <= 0
            or not cgroup.startswith(manager_group) or ".." in Path(cgroup).parts):
        raise ServiceError(f"{service} is not active in the expected user manager")
    source = project.root if require_source and not project.release_install else None
    source_sha = project.source_sha if require_source and project.release_install else ""
    if require_source and project.release_install and not re.fullmatch(r"[0-9a-f]{40}", source_sha):
        raise ServiceError("accepted installed release commit is unavailable")
    if source is not None:
        try:
            working = Path(properties.get("WorkingDirectory", ""))
            if not working.is_absolute() or not working.resolve(strict=True).is_relative_to(source.resolve(strict=True)):
                raise ServiceError(f"{service} working directory is outside the expected release source")
        except OSError as exc:
            raise ServiceError(f"cannot attest {service} release directory") from exc
    # GNOME reclassifies some desktop MainPIDs into app-<name>-<PID>.scope.
    # Retain the canonical unit's MainPID binding and verify the exact scope
    # before using it for this process and all of the service's listeners.
    try:
        groups = (_PROC_ROOT / pid / "cgroup").read_text().splitlines()
    except OSError as exc:
        raise ServiceError(f"cannot attest runtime PID {pid}") from exc
    actual_group = next((line[3:] for line in groups if line.startswith("0::")), "")
    if actual_group != cgroup and not actual_group.startswith(cgroup + "/"):
        cgroup = _desktop_application_cgroup(int(pid), uid)
    _attest_process(int(pid), uid, cgroup, source, source_sha=source_sha)
    return int(pid), uid, cgroup


def _attested_listener_pids(port: int) -> set[int]:
    try:
        result = capture(["ss", "-H", "-ltnp", f"( sport = :{port} )"])
    except OSError as exc:
        raise ServiceError(f"port {port} listener ownership is unavailable") from exc
    listeners = [set(map(int, _SS_PID_RE.findall(line))) for line in result.stdout.splitlines() if line.strip()]
    if result.returncode or not listeners or any(not pids for pids in listeners):
        raise ServiceError(f"port {port} listener ownership is unavailable")
    return set().union(*listeners)


def attest_service_runtime(project: ProjectServices, service: str, *, port: int = 0,
                           require_source: bool = True) -> tuple[int, int, str]:
    """Bind an active unit and every listener to its manager and accepted source."""
    paired = activated_service(service)
    identity = _unit_runtime(project, paired or service, require_source=require_source)
    _pid, uid, cgroup = identity
    for pid in _attested_listener_pids(port) if port else ():
        try:
            _attest_process(pid, uid, cgroup,
                            project.root if require_source and not project.release_install else None,
                            source_sha=project.source_sha if require_source and project.release_install else "")
        except ServiceError:
            # A socket-activated service shares its listening FD with its user
            # manager. Admit that one process only for this socket's Listen.
            if not service.endswith(".socket"):
                raise
            listen = _systemctl_value(service, "Listen")
            if service_state(service) != "active" or not re.search(rf":{port} \(Stream\)(?:\s|$)", listen):
                raise
            manager_group = f"/user.slice/user-{uid}.slice/user@{uid}.service"
            _attest_process(pid, uid, manager_group, None)
            try:
                actual_group = (_PROC_ROOT / str(pid) / "cgroup").read_text().strip()
                executable = (_PROC_ROOT / str(pid) / "exe").resolve(strict=True)
            except OSError as exc:
                raise ServiceError("cannot attest socket manager listener") from exc
            if actual_group != f"0::{manager_group}" or executable.name != "systemd":
                raise ServiceError("socket listener is outside the expected user manager") from None
    return identity


def _backend_process_release_root(pid: int, *, proc_root: Path = Path("/proc")) -> Path:
    """Attest the release from the running service process, not the current symlink."""
    if pid <= 0:
        raise ServiceError("cannot attest the running backend reader release")
    try:
        backend_dir = (proc_root / str(pid) / "cwd").resolve(strict=True)
    except OSError as exc:
        raise ServiceError("cannot attest the running backend reader release") from exc
    if backend_dir.name != "backend":
        raise ServiceError("running backend working directory is unexpected")
    return backend_dir.parent


def _service_active_state(service: str) -> str:
    return _systemctl_value(service, "ActiveState") or "unknown"


def _wait_service_inactive(service: str, *, timeout: float = 8.0, manager=None) -> bool:
    def state():
        return (manager("show", service, "-p", "ActiveState", "--value").stdout.strip()
                if manager is not None else _service_active_state(service))

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if state() in {"inactive", "failed"}:
            return True
        time.sleep(0.25)
    return state() in {"inactive", "failed"}


def _wait_service_active(service: str, *, timeout: float = 8.0, manager=None) -> bool:
    def ready():
        if manager is None:
            return _service_active_state(service) == "active" and _service_main_pid(service) > 0
        state = manager("show", service, "-p", "ActiveState", "--value").stdout.strip()
        pid = manager("show", service, "-p", "MainPID", "--value").stdout.strip()
        return state == "active" and pid.isdecimal() and int(pid) > 0

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if ready():
            time.sleep(0.25)
            return ready()
        time.sleep(0.25)
    return False


def _restart_activation_unit(unit: str, paired: str) -> int:
    """Re-arm a socket/timer; its service loads the new release on next activation.

    systemd owns a socket's listener, so no port-listener cleanup runs here.
    """
    print(f"[service] restarting {unit} ({paired} on activation)")
    errors = run(["systemctl", "--user", "enable", unit]) != 0
    errors += run(["systemctl", "--user", "stop", unit]) != 0
    if service_exists(paired):
        errors += run(["systemctl", "--user", "stop", paired]) != 0 or not _wait_service_inactive(paired)
    errors += run(["systemctl", "--user", "start", unit]) != 0
    result = int(bool(errors)) or int(service_state(unit) != "active")
    print(f"[service] {unit} {'OK' if result == 0 else 'FAIL'}")
    return result


def restart_service(service: str, *, port: int = 0, project: ProjectServices | None = None) -> int:
    service = canonical_unit(service)
    if not service:
        return 0
    if not service_exists(service):
        print(f"[service] {service} FAIL: configured service not found")
        return 1
    if project is not None:
        try:
            _runtime_uid(project)
            if not activated_service(service) and (_service_main_pid(service) or (port and _port_open(port))):
                attest_service_runtime(project, service, port=port if port and _port_open(port) else 0,
                                       require_source=False)
        except ServiceError as exc:
            print(f"[service] {service} FAIL: {exc}")
            return 1
    if paired := activated_service(service):
        return _restart_activation_unit(service, paired)
    current_invocation = os.environ.get("INVOCATION_ID", "")
    if current_invocation:
        unit_invocation = _manager(service)("show", service, "-p", "InvocationID", "--value").stdout.strip()
        if unit_invocation == current_invocation:
            print(f"[service] skipping current unit {service}")
            return 0
    print(f"[service] restarting {service}")
    old_pid = _service_main_pid(service)
    stop_result = run(_service_command(service, "stop"))
    if stop_result != 0 or not _wait_service_inactive(service):
        print(f"[service] {service} did not stop cleanly; killing unit")
        run(_service_command(service, "kill", "--kill-who=all", "-s", "SIGKILL"))
        _wait_service_inactive(service, timeout=3.0)
    if old_pid and _pid_alive(old_pid):
        capture(["kill", "-9", str(old_pid)])  # Every managed service, the collector included, runs as the owner.
        time.sleep(0.25)
    if port and (_port_open(port) if project is not None else not _kill_port(port)):
        print(f"[service] {service} FAIL: port {port} still in use")
        return 1
    if old_pid and _pid_alive(old_pid):
        print(f"[service] {service} FAIL: old PID {old_pid} still alive")
        return 1
    result = run(_service_command(service, "start"))
    if result == 0 and project is not None:
        try:
            if not _wait_service_active(service):
                raise ServiceError("unit did not become active")
            attest_service_runtime(project, service)
        except ServiceError as exc:
            print(f"[service] {service} FAIL: {exc}")
            return 1
    print(f"[service] {service} {'OK' if result == 0 else 'FAIL'}")
    return result


def start_services(project: ProjectServices) -> int:
    if project.deployment:
        return _remote_service_action(project, "start", list(project.all_services))
    errors = 0
    try:
        managed_root = service_release.current_source_root(project.project_id)
        if managed_root is not None:
            project = project_at_source(project, managed_root)
    except service_release.ReleaseError as exc:
        print(f"[service] cannot start invalid managed release: {exc}")
        return 1
    if sync_systemd_units(project) != 0:
        return 1
    for service in project.all_services:
        if service_exists(service):
            if activated_service(service):
                errors += run(["systemctl", "--user", "enable", service]) != 0
            errors += run(_service_command(service, "start")) != 0
    return errors


def stop_services(project: ProjectServices) -> int:
    if project.deployment:
        units = list(dict.fromkeys(unit for service in reversed(project.all_services)
                                   for unit in (service, activated_service(service)) if unit))
        return _remote_service_action(project, "stop", units)
    errors = 0
    for service in reversed(project.all_services):
        for unit in (service, activated_service(service)):
            if unit and service_exists(unit):
                errors += run(_service_command(unit, "stop")) != 0
    return errors


def _remote_service_action(project: ProjectServices, action: str, units: list[str]) -> int:
    assert project.deployment is not None
    try:
        runtime_deployment.control_units(project.deployment, action, units)
    except runtime_deployment.DeploymentError as exc:
        print(f"[service] {exc}")
        return 1
    print(f"[service] {action} on {project.deployment.label}: {', '.join(units)}")
    return 0


_TRANSIENT_UNIT = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.@-]{0,200}\.(?:service|scope)")


def stop_transient_unit(project: ProjectServices, unit: str) -> tuple[int, str]:
    """Stop one transient user unit the project created, refusing anything else.

    Qualifying units are named ``<project>-*.service|.scope``, have no unit file
    (systemd reports Transient=yes) and are outside the managed service set, e.g.
    smoke-test or harness units left by ``systemd-run --user --unit=...``.
    """
    prefix = project.project_id + "-"
    if not _TRANSIENT_UNIT.fullmatch(unit) or not unit.startswith(prefix):
        return 2, f"refused:name_outside_{prefix}*.service|.scope"
    if unit in project.all_services:
        return 2, "refused:managed_service;use_st_service_stop"
    shown = systemctl("show", "--property=LoadState,Transient,ActiveState", "--", unit)
    if shown.returncode:
        return 1, "unavailable:unit_state_unreadable"
    state = dict(line.split("=", 1) for line in shown.stdout.splitlines() if "=" in line)
    if state.get("LoadState") == "not-found":
        return 0, "absent"
    if state.get("Transient") != "yes":
        return 2, "refused:not_transient"
    if state.get("ActiveState") in {"inactive", "failed"}:
        return 0, "already_" + state["ActiveState"]
    return (0, "stopped") if systemctl("stop", "--", unit).returncode == 0 else (1, "stop_failed")


INFRA_RESTART_HINT = (
    "run: nightshift request unit.restart unit=summitflow-stack.service --reason recover --wait"
)


def ensure_infra(project: ProjectServices | None = None) -> int:
    """Check readiness, verifying inconclusive connections from the backend's context."""
    needs = INFRA if project is None else project.infra
    pg_code = capture(["pg_isready", "-h", "localhost", "-p", "5432", "-U", "admin"]).returncode if "postgres" in needs else 0
    pg = pg_code == 0
    down = ["postgres"] if pg_code == 1 else []  # 1 = answering but rejecting; 2 = no response.
    try:
        hatchet = "hatchet" not in needs or httpx.get("http://localhost:8888/ready", timeout=2.0).status_code < 400
        if not hatchet:
            down.append("hatchet")
    except httpx.HTTPError:
        hatchet = False
    if down:
        print(f"[service] infrastructure is down ({', '.join(down)}); {INFRA_RESTART_HINT}")
        return 1
    if pg_code not in (0, 2):
        print(f"[service] infrastructure status unavailable (postgres); pg_isready exited {pg_code}")
        return 1
    if pg and hatchet:
        return 0
    # Agent network policy can block these ports while the stack is healthy.
    # A failed caller-side connection alone is not evidence to restart it.
    failed = [name for name, up in (("postgres", pg), ("hatchet", hatchet)) if not up]
    try:
        with STClient(require_project=False, timeout=10.0) as client:
            rows = client.get(client._global_url("/docker/status"))
        if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
            raise ValueError("expected runtime status rows")
    except (APIError, httpx.HTTPError, ValueError):
        print(f"[service] infrastructure status unavailable ({', '.join(failed)}); could not verify via the runtime status API")
        return 1
    unknown = []
    for name in failed:
        row = next((row for row in rows if row.get("service") == name), {})
        if row.get("health") == "unhealthy" or row.get("state") in {"stopped", "failed", "exited", "dead"}:
            down.append(name)
        elif row.get("state") != "running" or row.get("health") != "healthy":
            unknown.append(name)
    if unknown:
        print(f"[service] infrastructure status unavailable ({', '.join(unknown)}); runtime status API did not confirm health")
    if down:
        print(f"[service] infrastructure is down ({', '.join(down)}); {INFRA_RESTART_HINT}")
    return int(bool(down or unknown))


def backend_optional_dependencies(backend_dir: Path) -> dict[str, Any] | None:
    """Declared optional-dependency groups, or None without pyproject.toml + uv.lock."""
    if not (backend_dir / "pyproject.toml").exists() or not (backend_dir / "uv.lock").exists():
        return None
    manifest = tomllib.loads((backend_dir / "pyproject.toml").read_text())
    declared = manifest.get("project", {}).get("optional-dependencies", {})
    return declared if isinstance(declared, dict) else {}


def locked_backend_sync_command(declared_extras: Mapping[str, Any], extras: Sequence[str]) -> list[str]:
    """`uv sync --locked` with ``dev`` (when declared) plus the requested extras, deduplicated."""
    command = ["uv", "sync", "--locked"]
    selected = dict.fromkeys((*(("dev",) if "dev" in declared_extras else ()), *extras))
    for extra in selected:
        command.extend(["--extra", extra])
    return command


def release_cache_options(manager: str, root: Path) -> list[str]:
    """Install options that let a release under the service state root share unchanged dependencies.

    uv and pnpm reflink from their cache only within one filesystem. The user
    caches (uv's on /srv/scratch, the pnpm store on /srv/workspaces) sit on
    another disk than the state root, so each release got full private copies
    (~1.6 GB per agent-hub rebuild). A cache beside the releases fixes that;
    clone, never hardlink, keeps release files independent of the cache. Paths
    elsewhere (cleanroom snapshots, dev checkouts) keep the user's caches.
    """
    cache = service_release.release_cache_root()
    if not root.resolve().is_relative_to(cache.parent):
        return []
    if manager == "uv":
        return ["--cache-dir", str(cache / "uv"), "--link-mode", "clone"]
    if manager == "pnpm":
        # An existing private clone's node_modules recorded the old store; pnpm
        # must reinstall it instead of aborting for lack of a TTY to confirm.
        return ["--store-dir", str(cache / "pnpm-store"), "--package-import-method", "clone-or-copy",
                "--config.confirm-modules-purge=false"]
    return []  # npm ci always copies from its tarball cache


def release_install(command: Sequence[str], manager: str, root: Path, *, cwd: Path) -> int:
    """Run a dependency install; one under the state root holds the release cache so host retention skips its prune."""
    options = release_cache_options(manager, root)
    with service_release.release_cache_lock() if options else nullcontext():
        return run([*command, *options], cwd=cwd, quiet_success=True, _heavy=True)


def sync_backend(project: ProjectServices) -> int:
    """Install the locked Python environment before migrations or restarts."""
    declared_extras = backend_optional_dependencies(project.backend_dir)
    if declared_extras is None:
        if project.backend_extras:
            print("[service] configured backend extras require pyproject.toml and uv.lock")
            return 1
        return 0
    print("[service] syncing locked backend dependencies")
    # Managed checkouts use this same environment for canonical quality gates.
    unknown = set(project.backend_extras) - set(declared_extras)
    if unknown:
        print("[service] configured backend extras are not declared: " + ", ".join(sorted(unknown)))
        return 1
    command = locked_backend_sync_command(declared_extras, project.backend_extras)
    return release_install(command, "uv", project.root, cwd=project.backend_dir)


def _cargo() -> str:
    """Prefer the rustup toolchain; a caller PATH may resolve an older distro cargo."""
    rustup_cargo = Path(os.environ.get("CARGO_HOME", Path.home() / ".cargo")) / "bin" / "cargo"
    return str(rustup_cargo) if os.access(rustup_cargo, os.X_OK) else "cargo"


def _seed_from_live_release(project: ProjectServices, relative: Path) -> bool:
    """Reflink a build cache from the live release into this new release; True when seeded."""
    target = project.root / relative
    if target.exists():
        return False
    try:
        live = service_release.current_source_root(project.project_id)
    except service_release.ReleaseError:
        return False
    if live is None or live.resolve() == project.root.resolve():
        return False
    prior = live / relative
    if prior.is_symlink() or not prior.is_dir():
        return False
    target.parent.mkdir(parents=True, exist_ok=True)
    copied = subprocess.run(["cp", "-a", "--reflink=auto", str(prior), str(target)], check=False)
    if copied.returncode != 0:
        subprocess.run(["rm", "-rf", "--", str(target)], check=False)
        return False
    return True


def build_host_monitor(project: ProjectServices) -> int:
    """Build the independent host collector in the accepted SummitFlow release."""
    if project.project_id != "summitflow" or "summitflow-host-monitor.service" not in project.default_workers:
        return 0
    source = project.root / "host-monitor"
    if not (source / "Cargo.toml").is_file() or not (source / "Cargo.lock").is_file():
        print("[service] host monitor requires Cargo.toml and Cargo.lock in accepted source")
        return 1
    if _seed_from_live_release(project, Path("host-monitor/target")):
        # Release files carry commit mtimes, so a rollback could look fresh against a newer
        # binary: reuse only the dependency crates and always recompile the collector itself.
        package = tomllib.loads((source / "Cargo.toml").read_text())["package"]["name"]
        if run([_cargo(), "clean", "--release", "-p", package], cwd=source, quiet_success=True) != 0:
            return 1
    print("[service] building locked host monitor")
    code = run([_cargo(), "build", "--locked", "--release"], cwd=source, quiet_success=True, _heavy=True)
    if code == 0:
        host_monitor_deploy.build_helper(project.root)
    return code


def sync_host_monitor_policy(project: ProjectServices) -> int:
    """Snapshot canonical runtime pressure thresholds for the standalone collector."""
    if project.project_id != "summitflow" or "summitflow-host-monitor.service" not in project.default_workers:
        return 0
    from app.tasks.runtime_hygiene_common import (
        CPU_CRIT_PERCENT,
        DISK_CRIT_FREE_GB,
        DISK_CRIT_PERCENT,
    )
    from app.utils.heavy_work import NIGHTSHIFT_ADMISSION

    state_dir = project.root / "host-monitor/target/release"
    state_dir.mkdir(parents=True, exist_ok=True)
    policy = {
        "schema": 1,
        "cpu_critical_pct": CPU_CRIT_PERCENT,
        "memory_status_path": str(NIGHTSHIFT_ADMISSION),  # memory pressure is Nightshift's state, not a threshold here
        "disk_critical_pct": DISK_CRIT_PERCENT,
        "disk_critical_free_bytes": int(DISK_CRIT_FREE_GB * 1024**3),
        "source": "runtime_hygiene_common",
    }
    with tempfile.NamedTemporaryFile("w", dir=state_dir, prefix=".policy-", delete=False) as file:
        temporary = Path(file.name)
        try:
            os.fchmod(file.fileno(), 0o600)
            json.dump(policy, file, separators=(",", ":"), sort_keys=True)
            file.flush()
            os.fsync(file.fileno())
        except Exception:
            temporary.unlink(missing_ok=True)
            raise
    os.replace(temporary, state_dir / "policy.json")
    return 0


def enable_host_monitor(project: ProjectServices) -> int:
    """Enable the installed collector in the system boot target."""
    service = "summitflow-host-monitor.service"
    if project.project_id != "summitflow" or service not in project.default_workers:
        return 0
    return run(_service_command(service, "enable"))


def has_host_monitor(project: ProjectServices) -> bool:
    return project.project_id == "summitflow" and host_monitor_deploy.UNIT in project.default_workers


def preflight_host_monitor(project: ProjectServices) -> int:
    if not has_host_monitor(project):
        return 0
    if os.getuid() == 0:
        print("[service] run rebuild as the owner; only collector installation uses sudo")
        return 1
    result = run(["sudo", "-n", "/usr/bin/true"], quiet_success=True)
    if result:
        print("[service] root collector installation requires available noninteractive sudo; no services changed")
        return result
    # Root runs only the installed, root-owned copy; it must match this release's installer.
    try:
        installed = HOST_MONITOR_HELPER.read_bytes()
    except OSError:
        installed = b""
    if installed != (project.root / "backend/cli/lib/host_monitor_deploy.py").read_bytes():
        print(f"[service] {HOST_MONITOR_HELPER} is missing or differs from this release; "
              "install it with scripts/install-host-infra.sh; no services changed")
        return 1
    return 0


def host_monitor_deployment(project: ProjectServices, transaction: str, action: str) -> int:
    if not has_host_monitor(project):
        return 0
    return run(["sudo", "-n", str(HOST_MONITOR_HELPER), action,
                "--source", str(project.root), "--uid", str(os.getuid()),
                "--gid", str(os.getgid()), "--transaction", transaction], quiet_success=True)


def verify_host_monitor(project: ProjectServices) -> int:
    if not has_host_monitor(project):
        return 0
    from monitor_control import control_request
    from monitor_reader import MonitorReader

    for _ in range(15):
        try:
            status = control_request("status", state_dir=host_monitor_deploy.STATE)
            latest = status.get("latest") or {}
            if (status.get("ok") and not status.get("writer_failure")
                    and latest.get("sampled_at_ns", 0) > time.time_ns() - 30_000_000_000):
                MonitorReader(host_monitor_deploy.STATE).status(max_bytes=4096)
                return 0
        except (OSError, ValueError, RuntimeError):
            pass
        time.sleep(1)
    print("[service] collector control, freshness, or owner history access failed")
    return 1


def migrate_host_monitor_store(project: ProjectServices) -> MigrationResult:
    """Stop the sole writer for an explicitly requested, guarded page conversion."""
    service = "summitflow-host-monitor.service"
    if project.project_id != "summitflow" or service not in project.default_workers:
        raise ServiceError("monitor store migration requires the SummitFlow host monitor")
    if system_systemctl("cat", service).returncode == 0:
        raise ServiceError("page-size conversion is a legacy user-store operation; system store is already managed")
    try:
        live_source = service_release.current_source_root("summitflow")
    except service_release.ReleaseError as exc:
        raise ServiceError("cannot verify the live monitor reader lock release") from exc
    if live_source is None:
        raise ServiceError("deploy the monitor reader lock release before migrating the store")
    try:
        reader_file = live_source / "backend/monitor_reader/reader.py"
        reader_ready = reader_file.is_file() and (
            "MONITOR_MAINTENANCE_LOCK_VERSION = 2" in reader_file.read_text()
        )
    except OSError as exc:
        raise ServiceError("cannot verify the live monitor reader lock release") from exc
    if not reader_ready:
        raise ServiceError("deploy the monitor reader lock release before migrating the store")
    backend_root = _backend_process_release_root(_service_main_pid(project.backend_service))
    if backend_root != live_source.resolve(strict=True):
        raise ServiceError("running backend has not loaded the monitor reader lock release")
    state_dir = Path.home() / ".local/state/summitflow/monitor"
    if (state_dir / "migration.interlock").exists() or (state_dir / "migration.interlock").is_symlink():
        raise ServiceError("existing monitor migration interlock requires manual recovery")
    db = state_dir / "monitor.sqlite3"
    if not db.exists():
        return MigrationResult("absent")
    if systemctl("cat", service).returncode != 0:
        raise ServiceError("host monitor service is not installed")
    if run(["systemctl", "--user", "stop", service]) != 0 or not _wait_service_inactive(service, manager=systemctl):
        raise ServiceError("host monitor did not stop cleanly; conversion refused")
    try:
        result = migrate_stopped_store(state_dir)
    except MonitorMigrationDeferred as exc:
        if run(["systemctl", "--user", "start", service]) != 0 or not _wait_service_active(service, manager=systemctl):
            raise ServiceError(f"monitor migration deferred and collector restart failed: {exc}") from exc
        print(f"[service] monitor store migration deferred: {exc}")
        return MigrationResult("deferred")
    except MonitorMigrationFailed as exc:
        raise ServiceError(str(exc)) from exc
    if run(["systemctl", "--user", "start", service]) != 0 or not _wait_service_active(service, manager=systemctl):
        if result.status == "converted_restart_pending" and result.receipt is not None:
            try:
                retain_restart_interlock(state_dir, result.receipt)
                update_restart_receipt(result.receipt, status="collector_restart_failed")
            except (OSError, ValueError) as exc:
                run(["systemctl", "--user", "stop", service])
                raise ServiceError(f"collector restart failed; recovery interlock/receipt failed: {exc}") from exc
        run(["systemctl", "--user", "stop", service])
        raise ServiceError("collector did not become active after monitor store migration")
    if result.status == "converted_restart_pending" and result.receipt is not None:
        try:
            update_restart_receipt(result.receipt, status="succeeded")
        except (OSError, ValueError) as exc:
            raise ServiceError(f"collector active but migration restart receipt remains pending: {exc}") from exc
        return MigrationResult("migrated", result.receipt)
    return result


def install_st_monitor_launcher(project: ProjectServices) -> int:
    """Atomically adopt the narrow st launcher after a verified SummitFlow release."""
    if project.project_id != "summitflow" or "summitflow-host-monitor.service" not in project.default_workers:
        return 0
    source = project.root / "scripts" / "st"
    legacy = project.root / "backend" / ".venv" / "bin" / "st"
    target = Path.home() / "bin" / "st"
    if not source.is_file() or not os.access(source, os.X_OK):
        print("[service] st monitor launcher is missing or not executable")
        return 1
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.is_symlink():
        if target.resolve(strict=False) not in {source.resolve(), legacy.resolve(strict=False)}:
            print("[service] existing st symlink has a custom target; launcher install refused")
            return 1
    elif target.exists():
        print("[service] existing st executable is not a symlink; launcher install refused")
        return 1
    temporary = target.with_name(".st-monitor-next")
    if temporary.exists() or temporary.is_symlink():
        print("[service] stale st launcher staging link; launcher install refused")
        return 1
    temporary.symlink_to(source)
    os.replace(temporary, target)
    print(f"[service] linked st -> {source}")
    return 0


@dataclass(frozen=True)
class FrontendInstall:
    """Lockfile-selected frontend dependency install."""

    manager: str  # "npm" or "pnpm"
    command: tuple[str, ...]
    cwd: Path
    workspace: bool = False


def frontend_install_plan(frontend_dir: Path, root: Path) -> FrontendInstall | None:
    """Select the locked installer for a frontend, or None without package.json."""
    if not (frontend_dir / "package.json").exists():
        return None
    # Some managed products (including Electron shells) keep an npm lock at the
    # project root. Install inside the accepted release before its service unit
    # starts; the unit must never depend on checkout-local node_modules.
    if (frontend_dir / "package-lock.json").exists() and not (frontend_dir / "pnpm-lock.yaml").exists():
        return FrontendInstall("npm", ("npm", "ci"), frontend_dir)
    # pnpm resolves workspace dependencies at the workspace root. Always verify
    # the frozen lock, even when an existing node_modules directory is present.
    for directory in (frontend_dir, *frontend_dir.parents):
        if not directory.is_relative_to(root):
            break
        if (directory / "pnpm-workspace.yaml").exists():
            return FrontendInstall("pnpm", ("pnpm", "install", "--frozen-lockfile"), directory, workspace=True)
    return FrontendInstall("pnpm", ("pnpm", "install", "--frozen-lockfile"), frontend_dir)


def build_frontend(project: ProjectServices) -> int:
    plan = frontend_install_plan(project.frontend_dir, project.root)
    if plan is None:
        return 0
    # Next's build cache is content-addressed; seeding it only skips recompiling unchanged modules.
    if project.frontend_dir.is_relative_to(project.root):
        _seed_from_live_release(project, project.frontend_dir.relative_to(project.root) / ".next" / "cache")
    print("[service] building frontend")
    install = release_install(plan.command, plan.manager, project.root, cwd=plan.cwd)
    if install != 0:
        return install
    if plan.manager == "npm":
        return run(["npm", "run", "build"], cwd=project.frontend_dir, quiet_success=True, _heavy=True)
    if plan.workspace:
        # Production exports point at dist. pnpm owns dependency selection and
        # build order; build only this frontend's transitive workspace inputs.
        relative = project.frontend_dir.relative_to(plan.cwd).as_posix()
        dependencies = run(["pnpm", "--filter", f"{{./{relative}}}^...", "--if-present", "run", "build"],
                           cwd=plan.cwd, quiet_success=True, _heavy=True)
        if dependencies != 0:
            return dependencies
    return run(["pnpm", "build"], cwd=project.frontend_dir, quiet_success=True, _heavy=True)


def run_migrations(project: ProjectServices) -> int:
    if not project.backend_service or not (project.backend_dir / "alembic.ini").exists():
        return 0
    venv = project.backend_dir / ".venv"
    if not (venv / "bin" / "alembic").exists():
        venv = project.root / ".venv"
    alembic = venv / "bin" / "alembic"
    if not alembic.exists():
        print("[service] configured migrations require an installed Alembic executable")
        return 1
    # Alembic runs from immutable accepted source, which deliberately excludes
    # project env files. Supply only the keys SummitFlow's migration table
    # grants this project, from the host configuration its service uses.
    credstore = credstore_root(project) / project.project_id / "env"
    env = migration_env.migration_env(project.project_id, project.host_config_root or project.root, credstore=credstore)
    print("[service] running migrations")
    return run([str(alembic), "upgrade", "head"], cwd=project.backend_dir, env=env, quiet_success=True)


def sync_seeds(project: ProjectServices) -> int:
    export_script = project.backend_dir / "scripts" / "export_seeds.py"
    python = project.backend_dir / ".venv" / "bin" / "python"
    if not export_script.exists():
        return 0
    if not python.exists():
        print("[service] seed export requires the backend Python environment")
        return 1
    return run([str(python), "-m", "scripts.export_seeds"], cwd=project.backend_dir, quiet_success=True)


API_WAIT_SECONDS = 60


def wait_for_summitflow_api(seconds: float = API_WAIT_SECONDS) -> bool:
    """Give a restarting SummitFlow API up to a minute before a rebuild's first call to it.

    A dependent project's rebuild queued behind SummitFlow's own restart
    otherwise fails at once on connection refused. Any HTTP answer means up.
    """
    from st_sdk.config import get_api_base

    url = get_api_base().rstrip("/").removesuffix("/api") + "/health"
    deadline = time.monotonic() + seconds
    announced = False
    while True:
        try:
            httpx.get(url, timeout=3.0)
            return True
        except httpx.TransportError:
            if time.monotonic() >= deadline:
                print(f"[service] SummitFlow API still unreachable after {int(seconds)}s")
                return False
            if not announced:
                print(f"[service] SummitFlow API unreachable; waiting up to {int(seconds)}s for it to come back")
                announced = True
            time.sleep(2)


def verify_health(project: ProjectServices) -> int:
    errors = 0
    for component, service, port, endpoint, attempts in (
        ("backend", project.backend_service, project.backend_port, project.health_endpoint, 15),
        ("frontend", project.frontend_service, project.frontend_port, "/", 30),
    ):
        if not service or port <= 0:
            continue
        ok = False
        reason = "HTTP health did not succeed"
        for _ in range(attempts):
            try:
                # Socket activation needs a request before its paired service
                # can be attested. Its response still requires full attestation.
                before = None if activated_service(service) else attest_service_runtime(project, service, port=port)
                response = httpx.get(f"http://127.0.0.1:{port}{endpoint}", timeout=3.0)
                after = attest_service_runtime(project, service, port=port)
                ok = 200 <= response.status_code < 400 and (before is None or before == after)
            except (httpx.HTTPError, ServiceError) as exc:
                reason = str(exc)
                ok = False
            if ok:
                break
            time.sleep(1)
        print(f"[service] {component} {'OK' if ok else 'FAIL: ' + reason}")
        errors += not ok
    return int(errors)


def _job_path(job_id: str) -> Path:
    if not re.fullmatch(r"[0-9a-f]{32}", job_id):
        raise ServiceError("Invalid detached job id")
    return service_release.jobs_root() / f"{job_id}.json"


def _acceptance_candidate(
    project: ProjectServices,
    receipt: Path | Mapping[str, Any] | None,
) -> Path | Mapping[str, Any]:
    from . import acceptance
    from .acceptance_coordinator import accept_source, select_materialization

    if receipt is not None:
        return receipt
    try:
        sha = acceptance._git_value(project.git_root, ["rev-parse", "--verify", "HEAD^{commit}"],
                                    "Could not identify current source for local acceptance")
        if (requested_sha := getattr(project, "source_sha", "")) and sha != requested_sha:
            raise acceptance.AcceptanceError("Pinned source checkout no longer matches the requested commit")
        status = acceptance._git(project.git_root, ["status", "--porcelain=v1", "--untracked-files=all"])
        if status.returncode:
            raise acceptance.AcceptanceError("Could not inspect the checkout for local acceptance")
        # An isolated project, or any dirty checkout, accepts the exact commit
        # in a private clone: other agents' uncommitted work never blocks it.
        materialization = select_materialization(project.git_root, dirty=bool(status.stdout))
        print(f"[service] accepting {sha[:12]} " + ("in an isolated clone" if materialization == "isolated" else "in place"))
        return accept_source(project.git_root, sha=sha, materialization=materialization).receipt
    except acceptance.AcceptanceError as exc:
        raise ServiceError(f"Local acceptance failed: {exc}") from exc


def resolve_accepted_source(
    project: ProjectServices,
    receipt: Path | Mapping[str, Any] | None = None,
    *,
    rollback: bool = False,
) -> dict[str, Any]:
    """Validate a full acceptance receipt for detached deployment evidence.

    The forward-deploy check runs here too, so a detached rebuild refuses
    before it queues instead of failing later inside the queued unit.
    """
    from . import acceptance

    candidate = _acceptance_candidate(project, receipt)
    try:
        with acceptance.repo_lock(project.git_root, purpose="deployment", wait_seconds=acceptance.REPO_LOCK_WAIT_SECONDS):
            descriptor = acceptance.validate_acceptance_receipt(
                project.git_root, candidate, sha=getattr(project, "source_sha", "") or None)
            service_release.require_forward_deploy(project.project_id, project.git_root,
                                                   str(descriptor["source_commit"]), rollback=rollback)
    except Exception as exc:
        if isinstance(exc, (ServiceError, service_release.ReleaseError)):
            raise
        raise ServiceError(f"Accepted source validation failed: {exc}") from exc
    if isinstance(receipt, Path) and not descriptor.get("acceptance_artifact"):
        descriptor = {**descriptor, "acceptance_artifact": str(receipt)}
    if not isinstance(candidate, Path):
        descriptor = {
            **descriptor,
            "reused": bool(candidate.get("reused", False)),
            "reuse_lookup_ms": candidate.get("reuse_lookup_ms"),
        }
    service_release.AcceptedSource.from_descriptor(descriptor, require_full=True)
    return descriptor


def prepare_accepted_release(
    project: ProjectServices,
    receipt: Path | Mapping[str, Any] | None = None,
    *,
    rollback: bool = False,
) -> tuple[service_release.PreparedRelease, ProjectServices]:
    """Validate and materialize accepted source while holding the repo mutation lock."""
    candidate = _acceptance_candidate(project, receipt)
    try:
        release = service_release.prepare_release(project.project_id, project.git_root, candidate, rollback=rollback,
                                                  sha=project.source_sha or None)
    except Exception as exc:
        if isinstance(exc, (ServiceError, service_release.ReleaseError)):
            raise
        raise ServiceError(f"Accepted source preparation failed: {exc}") from exc
    return release, project_at_source(project, release.source_root, source_sha=release.source.source_commit)


def project_at_source(project: ProjectServices, source_root: Path, *, source_sha: str | None = None) -> ProjectServices:
    """Retarget one managed service layout without changing services or ports."""
    try:
        backend_relative = project.backend_dir.relative_to(project.root)
        frontend_relative = project.frontend_dir.relative_to(project.root)
    except ValueError as exc:
        raise ServiceError("Managed component directories must be inside the accepted source") from exc
    return replace(
        project,
        root=source_root,
        backend_dir=source_root / backend_relative,
        frontend_dir=source_root / frontend_relative,
        host_config_root=project.host_config_root or project.root,
        durable_data_root=project.durable_data_root or project.root / "data",
        source_sha=project.source_sha if source_sha is None else source_sha,
    )


def _write_job(record: dict[str, Any]) -> None:
    path = _job_path(record["job_id"])
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode="w", dir=path.parent, delete=False) as temporary:
        json.dump(record, temporary)
        temporary.flush()
        os.fsync(temporary.fileno())
    os.replace(temporary.name, path)


def _read_job(job_id: str) -> dict[str, Any]:
    path = _job_path(job_id)
    legacy = get_repo_root() / ".dev-tools" / "service-jobs" / f"{job_id}.json"
    if not path.exists() and legacy.exists():
        path = legacy
    try:
        record = json.loads(path.read_text())
    except (OSError, ValueError) as exc:
        raise ServiceError(f"Detached job result unavailable: {job_id}") from exc
    if not isinstance(record, dict) or record.get("job_id") != job_id:
        raise ServiceError(f"Invalid detached job record: {job_id}")
    return record


def detached_result(job_id: str) -> dict[str, Any]:
    """Read persisted exit status; disappearance alone never proves success."""
    record = _read_job(job_id)
    if record.get("state") in {"succeeded", "failed", "interrupted"}:
        return record
    response = systemctl("show", record["unit"], "--property=LoadState,ActiveState,InvocationID,Description")
    properties = dict(line.split("=", 1) for line in response.stdout.splitlines() if "=" in line)
    if response.returncode != 0 and properties.get("LoadState") != "not-found":
        return {**record, "state": "unknown"}
    same_invocation = not record.get("invocation_id") or record["invocation_id"] == properties.get("InvocationID")
    same_job = job_id in properties.get("Description", "")
    if properties.get("ActiveState") in {"active", "activating", "reloading", "deactivating"} and same_invocation and same_job:
        return record
    # The runner may have atomically committed its result during the systemd query.
    latest = _read_job(job_id)
    if latest.get("state") in {"succeeded", "failed", "interrupted"}:
        return latest
    return {**latest, "state": "interrupted"}


def run_detached_job(job_id: str) -> int:
    record = _read_job(job_id)
    if record.get("state") != "queued":
        raise ServiceError("Detached job has already started or completed")
    record.update(state="running", started_at=time.time(), invocation_id=os.environ.get("INVOCATION_ID", ""))
    _write_job(record)
    log_path = _job_path(job_id).with_suffix(".log")
    deployment_path = _job_path(job_id).with_suffix(".deployment.json")
    try:
        with log_path.open("w") as log:
            env = os.environ.copy()
            env["SUMMITFLOW_DEPLOYMENT_RESULT"] = str(deployment_path)
            result = subprocess.run(
                record["command"],
                stdout=log,
                stderr=subprocess.STDOUT,
                env=env,
                check=False,
            )
        code = result.returncode if result.returncode >= 0 else 128 - result.returncode
        if code == 0 and record.get("source"):
            try:
                deployment = service_release.validate_deployment_receipt(deployment_path)
                queued_source = service_release.AcceptedSource.from_descriptor(record["source"])
                if (
                    deployment["source_commit"] != queued_source.source_commit
                    or deployment["source_tree"] != queued_source.source_tree
                    or deployment["acceptance_id"] != queued_source.acceptance_id
                ):
                    raise service_release.ReleaseError("Detached deployment source mismatch")
                record["deployment"] = deployment
            except service_release.ReleaseError as exc:
                with log_path.open("a") as evidence_log:
                    evidence_log.write(f"Detached deployment evidence invalid: {exc}\n")
                code = 1
    except OSError as exc:
        log_path.write_text(f"Detached command could not start: {exc}\n")
        code = 1
    record.update(state="succeeded" if code == 0 else "failed", exit_code=code, completed_at=time.time(), log_path=str(log_path))
    _write_job(record)
    return code


def _caller_identity_env() -> list[tuple[str, str]]:
    """Env that makes the detached job resolve the queuing agent's coordination identity.

    The job's repo guard must see the caller's own holds as its own and match
    ``--with-ack`` against the requester; outside a harness it would be ``pid:N``.
    """
    from . import leases

    _agent_id, slug, session_id, provider = leases.identify_agent()
    if provider == "st":
        return [("ST_SESSION_ID", session_id)]
    if provider == "claude_code":
        return [("CLAUDE_SESSION_ID", session_id)]
    if provider == "codex_cli":
        return [("CODEX_SESSION_ID", session_id)]
    if provider == "agent_hub_specialist":
        return [("AGENT_HUB_AGENT_SLUG", slug), ("AGENT_HUB_SESSION_ID", session_id)]
    if provider == "pi":
        return [("PI_SESSION_ID", session_id)]
    if provider == "antigravity":
        return [("ANTIGRAVITY_CONVERSATION_ID", session_id)]
    if slug == "tmux":
        return [("TMUX_PANE", session_id)]
    return []


REBUILD_MEMORY_HIGH = "8G"
REBUILD_MEMORY_MAX = "12G"


def queue_detached(
    project: str,
    include_all_workers: bool,
    *,
    scope: str = "full",
    workers: tuple[str, ...] = (),
    accepted_source: Mapping[str, Any] | None = None,
    migrate_monitor_store: bool = False,
    with_ack: str | None = None,
    rollback: bool = False,
) -> int:
    unit = f"sf-rebuild-{project}"
    if systemctl("is-active", f"{unit}.service").stdout.strip() in {"active", "activating", "deactivating", "reloading"}:
        print(f"[service] detached rebuild already active: {unit}.service")
        return 1
    command = ["st", "service", "rebuild"]
    if include_all_workers:
        command.append("--include-all-workers")
    if migrate_monitor_store:
        command.append("--migrate-monitor-store")
    if scope != "full":
        command.extend(["--scope", scope])
    for worker in workers:
        command.extend(["--worker", worker])
    if with_ack:
        command.extend(["--with-ack", with_ack])
    if rollback:
        command.append("--rollback")
    source_evidence = None
    if accepted_source is not None:
        source = service_release.AcceptedSource.from_descriptor(accepted_source)
        if not source.acceptance_artifact:
            raise ServiceError("Accepted source has no durable receipt artifact")
        command.extend(["--acceptance", source.acceptance_artifact])
        source_evidence = source.evidence()
    command.append(project)
    job_id = uuid.uuid4().hex
    record: dict[str, Any] = {
        "job_id": job_id, "project": project, "unit": f"{unit}.service",
        "state": "queued", "exit_code": None, "queued_at": time.time(), "command": command,
    }
    if source_evidence is not None:
        record["source"] = source_evidence
    _write_job(record)
    result = capture(
        [
            "systemd-run", "--user", "--collect", "--unit", unit,
            "--description", f"Detached rebuild for {project} ({job_id})",
            # Observed peaks are 0.6-5 GB. MemoryHigh reclaims a runaway build
            # before it pushes agents into swap; MemoryMax is only a backstop.
            "-p", f"MemoryHigh={REBUILD_MEMORY_HIGH}", "-p", f"MemoryMax={REBUILD_MEMORY_MAX}",
            "--setenv", f"PATH={os.environ.get('PATH', '')}",
            "--setenv", f"HOME={Path.home()}",
            "--setenv", f"SUMMITFLOW_ROOT={get_repo_root()}",
            "--setenv", f"SUMMITFLOW_SERVICE_STATE_ROOT={service_release.service_state_root()}",
            # The documented repair for a broken release must not run it again.
            *(["--setenv", "ST_DEV_CHECKOUT=1"] if os.environ.get("ST_DEV_CHECKOUT") == "1" else []),
            *(arg for name, value in _caller_identity_env() for arg in ("--setenv", f"{name}={value}")),
            "st", "service", "_run-job", job_id,
        ]
    )
    if result.returncode != 0:
        record.update(state="failed", exit_code=result.returncode, completed_at=time.time())
        _write_job(record)
    print(f"[service] detached rebuild job={job_id} submission_rc={result.returncode}")
    print(f"[service] result: st service result {job_id}; wait: st service wait {job_id}")
    output = result.stdout or result.stderr
    if output:
        details = write_details(get_repo_root(), f"service-detached-{job_id}", output)
        print(f"[service] details:{display_path(get_repo_root(), details)}|hint:{summary_hint(output)}")
    return result.returncode
