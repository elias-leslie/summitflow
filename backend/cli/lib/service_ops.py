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
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

import httpx
from dotenv import dotenv_values

from app.project_identity import (
    get_project_identity,
    get_project_identity_root,
    identity_lifecycle,
    list_project_identities,
)
from app.utils.env_files import project_env_files
from app.utils.shared_paths import get_repo_root

from ..details import display_path, emit_result_or_details, summary_hint, write_details
from . import service_release
from .neri_runner_deploy import RunnerAdapter


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
    runner_adapter: RunnerAdapter | None = None
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
    adapter_raw = services.get("runner_adapter")
    try:
        adapter = RunnerAdapter(adapter_raw) if adapter_raw is not None else None
    except (ValueError, TypeError):
        raise ServiceError("services.runner_adapter must be the fixed neri-runner-v1 identifier") from None
    if adapter is not None and canonical_id != "neri":
        raise ServiceError("The neri-runner-v1 adapter is restricted to Neri")
    root = Path(root_raw)
    backend_subdir = str(runtime.get("backend_dir") or "backend")
    frontend_subdir = str(runtime.get("frontend_dir") or "frontend")
    return ProjectServices(
        project_id=canonical_id,
        root=root,
        backend_service=str(services.get("backend") or ""),
        frontend_service=str(services.get("frontend") or ""),
        default_workers=_as_str_list(services.get("default_workers")),
        optional_workers=_as_str_list(services.get("optional_workers")),
        backend_port=int(runtime.get("backend_port") or 0),
        frontend_port=int(runtime.get("frontend_port") or 0),
        backend_dir=root if backend_subdir == "." else root / backend_subdir,
        frontend_dir=root if frontend_subdir == "." else root / frontend_subdir,
        health_endpoint=str(runtime.get("health_endpoint") or "/health"),
        backend_extras=tuple(dict.fromkeys(_as_str_list(extras))),
        runner_adapter=adapter,
        host_config_root=root,
        durable_data_root=root / "data",
    )


def project_ids(*, include_inactive: bool = False) -> list[str]:
    ids: list[str] = []
    from app.storage.projects import testing_project_ids

    testing = set() if include_inactive else testing_project_ids()
    for identity in list_project_identities():
        project = _dict_value(identity.get("project"))
        project_id = project.get("id")
        if (isinstance(project_id, str) and project_id
                and (include_inactive or (identity_lifecycle(identity) == "active" and project_id not in testing))):
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
) -> int:
    result = subprocess.run(
        command,
        cwd=cwd,
        env=_command_env(command, env),
        text=True,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
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


def service_state(service: str) -> str:
    if not service:
        return "missing"
    result = systemctl("is-active", service)
    return (result.stdout or result.stderr).strip() or "unknown"


def service_exists(service: str) -> bool:
    return systemctl("cat", service).returncode == 0


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
    return systemctl("show", service, "-p", key, "--value").stdout.strip()


def _service_main_pid(service: str) -> int:
    raw = _systemctl_value(service, "MainPID")
    try:
        return int(raw)
    except ValueError:
        return 0


def _service_active_state(service: str) -> str:
    return _systemctl_value(service, "ActiveState") or "unknown"


def _wait_service_inactive(service: str, *, timeout: float = 8.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if _service_active_state(service) in {"inactive", "failed"}:
            return True
        time.sleep(0.25)
    return _service_active_state(service) in {"inactive", "failed"}


def restart_service(service: str, *, port: int = 0) -> int:
    if not service:
        return 0
    if not service_exists(service):
        print(f"[service] {service} FAIL: configured service not found")
        return 1
    current_invocation = os.environ.get("INVOCATION_ID", "")
    if current_invocation:
        unit_invocation = systemctl("show", service, "-p", "InvocationID", "--value").stdout.strip()
        if unit_invocation == current_invocation:
            print(f"[service] skipping current unit {service}")
            return 0
    print(f"[service] restarting {service}")
    old_pid = _service_main_pid(service)
    stop_result = run(["systemctl", "--user", "stop", service])
    if stop_result != 0 or not _wait_service_inactive(service):
        print(f"[service] {service} did not stop cleanly; killing unit")
        run(["systemctl", "--user", "kill", "--kill-who=all", "-s", "SIGKILL", service])
        _wait_service_inactive(service, timeout=3.0)
    if old_pid and _pid_alive(old_pid):
        capture(["kill", "-9", str(old_pid)])
        time.sleep(0.25)
    if port and not _kill_port(port):
        print(f"[service] {service} FAIL: port {port} still in use")
        return 1
    if old_pid and _pid_alive(old_pid):
        print(f"[service] {service} FAIL: old PID {old_pid} still alive")
        return 1
    result = run(["systemctl", "--user", "start", service])
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
            errors += run(["systemctl", "--user", "start", service]) != 0
    return errors


def stop_services(project: ProjectServices) -> int:
    errors = 0
    for service in reversed(project.all_services):
        if service_exists(service):
            errors += run(["systemctl", "--user", "stop", service]) != 0
    return errors


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


def sync_backend(project: ProjectServices) -> int:
    """Install the locked Python environment before migrations or restarts."""
    if not (project.backend_dir / "pyproject.toml").exists() or not (project.backend_dir / "uv.lock").exists():
        if project.backend_extras:
            print("[service] configured backend extras require pyproject.toml and uv.lock")
            return 1
        return 0
    print("[service] syncing locked backend dependencies")
    manifest = tomllib.loads((project.backend_dir / "pyproject.toml").read_text())
    command = ["uv", "sync", "--locked"]
    # Managed checkouts use this same environment for canonical quality gates.
    declared_extras = manifest.get("project", {}).get("optional-dependencies", {})
    unknown = set(project.backend_extras) - set(declared_extras)
    if unknown:
        print("[service] configured backend extras are not declared: " + ", ".join(sorted(unknown)))
        return 1
    extras = dict.fromkeys((*(("dev",) if "dev" in declared_extras else ()), *project.backend_extras))
    for extra in extras:
        command.extend(["--extra", extra])
    return run(command, cwd=project.backend_dir, quiet_success=True)


def build_frontend(project: ProjectServices) -> int:
    if not (project.frontend_dir / "package.json").exists():
        return 0
    print("[service] building frontend")
    # pnpm resolves workspace dependencies at the workspace root. Always verify
    # the frozen lock, even when an existing node_modules directory is present.
    install_dir = project.frontend_dir
    workspace = False
    for directory in (project.frontend_dir, *project.frontend_dir.parents):
        if not directory.is_relative_to(project.root):
            break
        if (directory / "pnpm-workspace.yaml").exists():
            install_dir = directory
            workspace = True
            break
    install = run(["pnpm", "install", "--frozen-lockfile"], cwd=install_dir, quiet_success=True)
    if install != 0:
        return install
    if workspace:
        # Production exports point at dist. pnpm owns dependency selection and
        # build order; build only this frontend's transitive workspace inputs.
        relative = project.frontend_dir.relative_to(install_dir).as_posix()
        dependencies = run(["pnpm", "--filter", f"{{./{relative}}}^...", "--if-present", "run", "build"],
                           cwd=install_dir, quiet_success=True)
        if dependencies != 0:
            return dependencies
    return run(["pnpm", "build"], cwd=project.frontend_dir, quiet_success=True)


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
        "jobinator-4000": {"JOBINATOR_DB_URL"},
    }.get(project.project_id, {"DATABASE_URL"})
    host_root = project.host_config_root or project.root
    # Neri's service unit reads the operator's shared env before its own
    # backend env; Alembic needs the same source when running from a release.
    shared_env = [Path.home() / ".env.local"] if project.project_id == "neri" else []
    for path in [*shared_env, *project_env_files(host_root)]:
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
    return acceptance.accept_revision(project.root, sha=sha, reuse=True)


def resolve_accepted_source(
    project: ProjectServices,
    receipt: Path | Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Validate a full acceptance receipt for detached deployment evidence."""
    from . import acceptance

    candidate = _acceptance_candidate(project, receipt)
    try:
        with acceptance.repo_lock(project.root, purpose="deployment"):
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
    service_release.AcceptedSource.from_descriptor(descriptor)
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
) -> int:
    unit = f"sf-rebuild-{project}"
    if systemctl("is-active", f"{unit}.service").stdout.strip() in {"active", "activating", "deactivating", "reloading"}:
        print(f"[service] detached rebuild already active: {unit}.service")
        return 1
    command = ["st", "service", "rebuild"]
    if include_all_workers:
        command.append("--include-all-workers")
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
