"""Native service lifecycle operations for `st service`."""

from __future__ import annotations

import os
import shutil
import socket
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from app.project_identity import (
    get_project_identity,
    get_project_identity_root,
    list_project_identities,
)
from app.utils.shared_paths import get_repo_root

from ..details import display_path, emit_result_or_details, summary_hint, write_details


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
    canonical_id = str(project.get("id") or project_id)
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
    )


def project_ids() -> list[str]:
    ids: list[str] = []
    for identity in list_project_identities():
        project = _dict_value(identity.get("project"))
        project_id = project.get("id")
        if isinstance(project_id, str) and project_id:
            ids.append(project_id)
    return sorted(set(ids))


def _detail_name(command: list[str]) -> str:
    parts = [Path(part).name for part in command[:3] if part and not part.startswith("-")]
    raw = "-".join(parts) or "command"
    return "service-" + "".join(char if char.isalnum() or char in "-_" else "-" for char in raw).strip("-")


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
        env=env,
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
    return subprocess.run(command, cwd=cwd, text=True, capture_output=True, check=False)


def systemctl(*args: str) -> subprocess.CompletedProcess[str]:
    return capture(["systemctl", "--user", *args])


def service_state(service: str) -> str:
    if not service:
        return "missing"
    result = systemctl("is-active", service)
    return (result.stdout or result.stderr).strip() or "unknown"


def service_exists(service: str) -> bool:
    return systemctl("cat", service).returncode == 0


def sync_systemd_units(project: ProjectServices) -> None:
    systemd_dir = Path(os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config"))) / "systemd" / "user"
    systemd_dir.mkdir(parents=True, exist_ok=True)
    synced = False
    summitflow_root = str(get_repo_root())
    for service in project.all_services:
        template = project.root / "scripts" / "systemd" / service
        if not template.exists():
            continue
        text = template.read_text()
        text = text.replace("__PROJECT_ROOT__", str(project.root))
        text = text.replace("__SUMMITFLOW_ROOT__", summitflow_root)
        (systemd_dir / service).write_text(text)
        print(f"[service] synced {service}")
        synced = True
    if synced:
        run(["systemctl", "--user", "daemon-reload"])


def _port_open(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.25)
        return sock.connect_ex(("127.0.0.1", port)) == 0


def _kill_port(port: int) -> None:
    if port <= 0 or not _port_open(port):
        return
    result = capture(["ss", "-ltnp", f"( sport = :{port} )"])
    pids: set[str] = set()
    for part in result.stdout.replace(",", " ").split():
        if part.startswith("pid="):
            pids.add(part.removeprefix("pid="))
    for pid in pids:
        run(["kill", pid])
    for _ in range(10):
        if not _port_open(port):
            return
        time.sleep(1)
    for pid in pids:
        run(["kill", "-9", pid])


def restart_service(service: str, *, port: int = 0) -> int:
    if not service:
        return 0
    if not service_exists(service):
        print(f"[service] {service} not found, skipping")
        return 0
    current_invocation = os.environ.get("INVOCATION_ID", "")
    if current_invocation:
        unit_invocation = systemctl("show", service, "-p", "InvocationID", "--value").stdout.strip()
        if unit_invocation == current_invocation:
            print(f"[service] skipping current unit {service}")
            return 0
    print(f"[service] restarting {service}")
    run(["systemctl", "--user", "stop", service])
    _kill_port(port)
    result = run(["systemctl", "--user", "start", service])
    print(f"[service] {service} {'OK' if result == 0 else 'FAIL'}")
    return result


def start_services(project: ProjectServices) -> int:
    errors = 0
    sync_systemd_units(project)
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


def ensure_infra() -> int:
    compose_dir = get_repo_root() / "docker" / "compose"
    compose_file = compose_dir / "docker-compose.yml"
    env_file = compose_dir / ".env"
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


def build_frontend(project: ProjectServices) -> int:
    if not (project.frontend_dir / "package.json").exists():
        return 0
    print("[service] building frontend")
    for path in (project.frontend_dir / ".next", project.frontend_dir / "dist"):
        if path.exists():
            shutil.rmtree(path)
    if not (project.frontend_dir / "node_modules").exists():
        install = run(["pnpm", "install"], cwd=project.frontend_dir, quiet_success=True)
        if install != 0:
            return install
    return run(["pnpm", "build"], cwd=project.frontend_dir, quiet_success=True)


def run_migrations(project: ProjectServices) -> int:
    if not project.backend_service or not (project.backend_dir / "alembic.ini").exists():
        return 0
    venv = project.backend_dir / ".venv"
    if not (venv / "bin" / "alembic").exists():
        venv = project.root / ".venv"
    alembic = venv / "bin" / "alembic"
    if not alembic.exists():
        return 0
    env = os.environ.copy()
    for key in (
        "DATABASE_URL",
        "REDIS_URL",
        "AGENT_HUB_DB_URL",
        "AGENT_HUB_REDIS_URL",
        "PORTFOLIO_DB_URL",
        "PORTFOLIO_AI_DB_URL",
        "HATCHET_CLIENT_TOKEN",
    ):
        env.pop(key, None)
    print("[service] running migrations")
    return run([str(alembic), "upgrade", "head"], cwd=project.backend_dir, env=env, quiet_success=True)


def sync_seeds(project: ProjectServices) -> None:
    export_script = project.backend_dir / "scripts" / "export_seeds.py"
    python = project.backend_dir / ".venv" / "bin" / "python"
    if export_script.exists() and python.exists():
        run([str(python), "-m", "scripts.export_seeds"], cwd=project.backend_dir, quiet_success=True)


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


def queue_detached(project: str, include_all_workers: bool) -> int:
    unit = f"sf-rebuild-{project}"
    if systemctl("is-active", f"{unit}.service").stdout.strip() == "active":
        print(f"[service] detached rebuild already active: {unit}.service")
        return 1
    command = ["st", "service", "rebuild"]
    if include_all_workers:
        command.append("--include-all-workers")
    command.append(project)
    result = capture(
        [
            "systemd-run",
            "--user",
            "--collect",
            "--unit",
            unit,
            "--description",
            f"Detached rebuild for {project}",
            "--setenv",
            f"PATH={os.environ.get('PATH', '')}",
            "--setenv",
            f"HOME={Path.home()}",
            *command,
        ]
    )
    output = result.stdout or result.stderr
    if output:
        details = write_details(get_repo_root(), f"service-detached-{project}", output)
        print(
            f"[service] detached rebuild queued rc={result.returncode}|"
            f"details:{display_path(get_repo_root(), details)}|hint:{summary_hint(output)}"
        )
    return result.returncode
