"""Native service lifecycle operations for `st service`."""

from __future__ import annotations

import json
import os
import re
import socket
import subprocess
import tempfile
import time
import tomllib
import uuid
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

import httpx
import psycopg
from dotenv import dotenv_values

from app.project_identity import (
    get_project_identity,
    get_project_identity_root,
    get_project_lifecycles,
    list_project_identities,
)
from app.utils.env_files import project_env_files
from app.utils.heavy_work import heavy_work
from app.utils.shared_paths import get_repo_root

from ..details import display_path, emit_result_or_details, summary_hint, write_details
from . import host_monitor_deploy, service_release
from .monitor_store_migration import (
    MigrationResult,
    MonitorMigrationDeferred,
    MonitorMigrationFailed,
    migrate_stopped_store,
    retain_restart_interlock,
    update_restart_receipt,
)


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
    backend_extras: tuple[str, ...] = ()
    host_config_root: Path | None = None
    durable_data_root: Path | None = None

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
    project = _dict_value(identity.get("project"))
    runtime = _dict_value(identity.get("runtime"))
    services = _dict_value(identity.get("services"))
    extras = runtime.get("backend_extras", [])
    if not isinstance(extras, list) or any(not isinstance(extra, str) or not extra.strip() for extra in extras):
        raise ServiceError("runtime.backend_extras must be a list of nonempty extra names")
    canonical_id = str(project.get("id") or project_id)
    root = Path(root_raw)
    backend_dir, frontend_dir = runtime_source_dirs(runtime, root)
    return ProjectServices(
        project_id=canonical_id,
        root=root,
        backend_service=str(services.get("backend") or ""),
        frontend_service=str(services.get("frontend") or ""),
        default_workers=_as_str_list(services.get("default_workers")),
        optional_workers=_as_str_list(services.get("optional_workers")),
        backend_port=int(runtime.get("backend_port") or 0),
        frontend_port=int(runtime.get("frontend_port") or 0),
        backend_dir=backend_dir,
        frontend_dir=frontend_dir,
        health_endpoint=str(runtime.get("health_endpoint") or "/health"),
        backend_extras=tuple(dict.fromkeys(_as_str_list(extras))),
        host_config_root=root,
        durable_data_root=root / "data",
    )


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
    return system_systemctl if service == host_monitor_deploy.UNIT else systemctl


def _service_command(service: str, *args: str) -> list[str]:
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


def release_references_for_services(releases_root: Path) -> set[Path] | None:
    """Return references from both user and system services, or fail closed."""
    user_references = _release_references_for_manager(releases_root, systemctl)
    system_references = _release_references_for_manager(releases_root, system_systemctl)
    if user_references is None or system_references is None:
        return None
    return user_references | system_references


def sync_systemd_units(project: ProjectServices) -> int:
    systemd_dir = Path(os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config"))) / "systemd" / "user"
    systemd_dir.mkdir(parents=True, exist_ok=True)
    synced = False
    summitflow_root = str(project.root if project.project_id == "summitflow" else get_repo_root())
    durable_data_root = project.durable_data_root or project.root / "data"
    host_config_root = project.host_config_root or project.root
    for service in project.all_services:
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
        (systemd_dir / service).write_text(text)
        print(f"[service] synced {service}")
        synced = True
    if synced:
        return run(["systemctl", "--user", "daemon-reload"])
    return 0


def _port_open(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.25)
        return sock.connect_ex(("127.0.0.1", port)) == 0


_SS_PID_RE = re.compile(r"pid=(\d+)")


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


def restart_service(service: str, *, port: int = 0) -> int:
    if not service:
        return 0
    if not service_exists(service):
        print(f"[service] {service} FAIL: configured service not found")
        return 1
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
        capture((["sudo", "-n", "/usr/bin/kill"] if service == host_monitor_deploy.UNIT else ["kill"]) + ["-9", str(old_pid)])
        time.sleep(0.25)
    if port and not _kill_port(port):
        print(f"[service] {service} FAIL: port {port} still in use")
        return 1
    if old_pid and _pid_alive(old_pid):
        print(f"[service] {service} FAIL: old PID {old_pid} still alive")
        return 1
    result = run(_service_command(service, "start"))
    print(f"[service] {service} {'OK' if result == 0 else 'FAIL'}")
    return result


def start_services(project: ProjectServices) -> int:
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
            errors += run(_service_command(service, "start")) != 0
    return errors


def stop_services(project: ProjectServices) -> int:
    errors = 0
    for service in reversed(project.all_services):
        if service_exists(service):
            errors += run(_service_command(service, "stop")) != 0
    return errors


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


def ensure_infra(project: ProjectServices | None = None) -> int:
    compose_root = project.root if project is not None else get_repo_root()
    config_root = (
        project.host_config_root
        if project is not None and project.host_config_root is not None
        else compose_root
    )
    compose_dir = compose_root / "docker" / "compose"
    compose_file = compose_dir / "docker-compose.yml"
    env_file = config_root / "docker" / "compose" / ".env"
    if not compose_file.exists():
        return 0
    missing = False
    for service in ("postgres", "redis", "hatchet"):
        result = capture(
            [
                "docker",
                "ps",
                "--filter",
                "label=com.docker.compose.project=summitflow-stack",
                "--filter",
                f"label=com.docker.compose.service={service}",
                "--format",
                "{{.ID}}",
            ]
        )
        if not result.stdout.strip():
            missing = True
            break
    if not missing:
        return 0
    if not env_file.is_file():
        print(
            "[service] infrastructure is down and the host compose environment "
            f"is unavailable: {env_file}"
        )
        return 1
    print("[service] starting Docker infra")
    env = os.environ.copy()
    for key in (
        "PORT",
        "HATCHET_CLIENT_TOKEN",
        "HATCHET_COOKIE_SECRET",
        "DATABASE_URL",
        "REDIS_URL",
        "AGENT_HUB_DB_URL",
        "AGENT_HUB_REDIS_URL",
        "PORTFOLIO_DB_URL",
        "INTERNAL_SERVICE_SECRET",
        "AGENT_HUB_SECRET_KEY",
    ):
        env.pop(key, None)
    code = run(
        [
            "docker",
            "compose",
            "--env-file",
            str(env_file),
            "-f",
            str(compose_file),
            "up",
            "-d",
            "postgres",
            "redis",
            "hatchet-migrate",
            "hatchet-setup-config",
            "hatchet",
        ],
        env=env,
    )
    if code != 0:
        return code
    for _ in range(45):
        pg = capture(["pg_isready", "-h", "localhost", "-p", "5432", "-U", "admin"])
        ready = None
        if pg.returncode == 0:
            try:
                ready = httpx.get("http://localhost:8888/ready", timeout=2.0)
            except httpx.HTTPError:
                ready = None
        if pg.returncode == 0 and ready is not None and ready.status_code < 400:
            print("[service] Docker infra ready")
            return 0
        time.sleep(2)
    print("[service] Docker infra not ready after 90s")
    return 1


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
    return run(command, cwd=project.backend_dir, quiet_success=True, _heavy=True)


def _cargo() -> str:
    """Prefer the rustup toolchain; a caller PATH may resolve an older distro cargo."""
    rustup_cargo = Path(os.environ.get("CARGO_HOME", Path.home() / ".cargo")) / "bin" / "cargo"
    return str(rustup_cargo) if os.access(rustup_cargo, os.X_OK) else "cargo"


def build_host_monitor(project: ProjectServices) -> int:
    """Build the independent host collector in the accepted SummitFlow release."""
    if project.project_id != "summitflow" or "summitflow-host-monitor.service" not in project.default_workers:
        return 0
    source = project.root / "host-monitor"
    if not (source / "Cargo.toml").is_file() or not (source / "Cargo.lock").is_file():
        print("[service] host monitor requires Cargo.toml and Cargo.lock in accepted source")
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
        MEMORY_CRIT_PERCENT,
    )

    state_dir = project.root / "host-monitor/target/release"
    state_dir.mkdir(parents=True, exist_ok=True)
    policy = {
        "schema": 1,
        "cpu_critical_pct": CPU_CRIT_PERCENT,
        "memory_critical_pct": MEMORY_CRIT_PERCENT,
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


def host_monitor_deployment(project: ProjectServices, transaction: str, action: str) -> int:
    if not has_host_monitor(project):
        return 0
    script = project.root / "backend/cli/lib/host_monitor_deploy.py"
    return run(["sudo", "-n", "/usr/bin/python3", "-I", str(script), action,
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
    print("[service] building frontend")
    install = run(list(plan.command), cwd=plan.cwd, quiet_success=True, _heavy=True)
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
    env = os.environ.copy()
    database_keys = {
        "DATABASE_URL",
        "AGENT_HUB_DB_URL",
        "PORTFOLIO_DB_URL",
        "PORTFOLIO_AI_DB_URL",
        "NERI_DB_URL",
        "LEARN_DB_URL",
        "JOBINATOR_DB_URL",
        "POSTGRES_ADMIN_URL",
        "DATABASE_ADMIN_URL",
    }
    for key in database_keys | {
        "REDIS_URL", "AGENT_HUB_REDIS_URL", "HATCHET_CLIENT_TOKEN",
        "INTERNAL_SERVICE_SECRET", "AGENT_HUB_INTERNAL_SECRET",
    }:
        env.pop(key, None)
    # Alembic runs from immutable accepted source, which deliberately excludes
    # project env files. Supply only the owning project's database credentials
    # from the same stable host configuration used by its systemd service.
    owner_database_keys = {
        "summitflow": {"DATABASE_URL"},
        "agent-hub": {"AGENT_HUB_DB_URL"},
        "portfolio-ai": {"PORTFOLIO_DB_URL"},
        "neri": {"NERI_DB_URL", "POSTGRES_ADMIN_URL", "DATABASE_ADMIN_URL"},
        "learn-o-tron": {"LEARN_DB_URL"},
        "jobinator-4000": {"JOBINATOR_DB_URL"},
    }.get(project.project_id, {"DATABASE_URL"})
    host_root = project.host_config_root or project.root
    # Neri and Jobinator read their database URLs from the operator's shared
    # env; Alembic needs that source when running from an accepted release.
    shared_env = [Path.home() / ".env.local"] if project.project_id in {"neri", "jobinator-4000"} else []
    project_env = project_env_files(host_root)
    if project.project_id == "learn-o-tron":
        project_env.append(host_root / "backend" / ".env")
    for path in [*shared_env, *project_env]:
        if path.name == ".env.example" or not path.is_file():
            continue
        for key, value in dotenv_values(path, interpolate=False).items():
            if key in owner_database_keys and value is not None:
                env[key] = value
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


def verify_health(project: ProjectServices) -> int:
    errors = 0
    if project.backend_service and project.backend_port > 0:
        ok = False
        for _ in range(15):
            try:
                response = httpx.get(f"http://localhost:{project.backend_port}{project.health_endpoint}", timeout=3.0)
                ok = response.status_code < 400
            except httpx.HTTPError:
                ok = False
            if ok:
                break
            time.sleep(1)
        print(f"[service] backend {'OK' if ok else 'FAIL'}")
        errors += not ok
    if project.frontend_service and project.frontend_port > 0:
        ok = False
        for _ in range(30):
            try:
                response = httpx.get(f"http://localhost:{project.frontend_port}/", timeout=3.0)
                ok = 200 <= response.status_code < 400
            except httpx.HTTPError:
                ok = False
            if ok:
                break
            time.sleep(1)
        print(f"[service] frontend {'OK' if ok else 'FAIL'}")
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

    if receipt is not None:
        return receipt
    identity = acceptance.source_identity(project.root)
    sha = str(identity.get("source_commit") or identity.get("commit") or "")
    if not sha:
        raise ServiceError("Could not identify current source for local acceptance")
    try:
        return acceptance.accept_revision(project.root, sha=sha, reuse=True)
    except acceptance.AcceptanceError as exc:
        raise ServiceError(f"Local acceptance failed: {exc}") from exc


def resolve_accepted_source(
    project: ProjectServices,
    receipt: Path | Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Validate a full acceptance receipt for detached deployment evidence."""
    from . import acceptance

    candidate = _acceptance_candidate(project, receipt)
    try:
        with acceptance.repo_lock(project.root, purpose="deployment", wait_seconds=acceptance.REPO_LOCK_WAIT_SECONDS):
            descriptor = acceptance.validate_acceptance_receipt(project.root, candidate)
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
) -> tuple[service_release.PreparedRelease, ProjectServices]:
    """Validate and materialize accepted source while holding the repo mutation lock."""
    candidate = _acceptance_candidate(project, receipt)
    try:
        release = service_release.prepare_release(project.project_id, project.root, candidate)
    except Exception as exc:
        if isinstance(exc, (ServiceError, service_release.ReleaseError)):
            raise
        raise ServiceError(f"Accepted source preparation failed: {exc}") from exc
    return release, project_at_source(project, release.source_root)


def project_at_source(project: ProjectServices, source_root: Path) -> ProjectServices:
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


def queue_detached(
    project: str,
    include_all_workers: bool,
    *,
    scope: str = "full",
    workers: tuple[str, ...] = (),
    accepted_source: Mapping[str, Any] | None = None,
    migrate_monitor_store: bool = False,
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
            "--setenv", f"PATH={os.environ.get('PATH', '')}",
            "--setenv", f"HOME={Path.home()}",
            "--setenv", f"SUMMITFLOW_ROOT={get_repo_root()}",
            "--setenv", f"SUMMITFLOW_SERVICE_STATE_ROOT={service_release.service_state_root()}",
            # The documented repair for a broken release must not run it again.
            *(["--setenv", "ST_DEV_CHECKOUT=1"] if os.environ.get("ST_DEV_CHECKOUT") == "1" else []),
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
