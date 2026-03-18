"""Constants and configuration for the runtime management API."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any


def _float_env(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        return max(float(raw), 0.1)
    except ValueError:
        return default


def _bool_env(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _detect_repo_root(start_path: Path | None = None) -> Path:
    current = (start_path or Path(__file__).resolve()).parent
    for candidate in (current, *current.parents):
        if (candidate / "scripts" / "rebuild.sh").exists():
            return candidate
    return Path(__file__).resolve().parents[4]


_INTERNAL_SECRET = os.environ.get("INTERNAL_SERVICE_SECRET", "")

_REPO_ROOT = _detect_repo_root()
_HOST_HOME_PATH = Path(os.environ.get("HOST_HOME_PATH", str(Path.home())))
_HOST_REPO_ROOT = Path(os.environ.get("HOST_REPO_ROOT", str(_HOST_HOME_PATH / "summitflow")))
_DEFAULT_STACK_MODE = os.environ.get("SUMMITFLOW_DOCKER_DEFAULT_MODE", "prod")
if _DEFAULT_STACK_MODE not in {"dev", "prod"}:
    _DEFAULT_STACK_MODE = "prod"
_COMPOSE_DIR = Path(os.environ.get("COMPOSE_DIR", str(_REPO_ROOT / "docker" / "compose")))
_COMPOSE_FILE = _COMPOSE_DIR / "docker-compose.yml"
_RUNTIME_MODE_FILE = _COMPOSE_DIR / ".runtime-mode"
_INFRA_SERVICES = {"postgres", "redis", "hatchet", "hatchet-migrate", "hatchet-setup-config"}
_DOCKER_SOCKET = Path("/var/run/docker.sock")
_USER_UID = os.getuid()
_USER_RUNTIME_DIR = Path(os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{_USER_UID}"))
_USER_DBUS_ADDRESS = os.environ.get(
    "DBUS_SESSION_BUS_ADDRESS",
    f"unix:path={_USER_RUNTIME_DIR / 'bus'}",
)
_COMMAND_TIMEOUT_SECONDS = _float_env("SUMMITFLOW_RUNTIME_COMMAND_TIMEOUT", 8.0)
_SYSTEMCTL_TIMEOUT_SECONDS = _float_env("SUMMITFLOW_RUNTIME_SYSTEMCTL_TIMEOUT", 0.75)
_HTTP_PROBE_TIMEOUT_SECONDS = _float_env("SUMMITFLOW_RUNTIME_HTTP_PROBE_TIMEOUT", 0.75)

COMPOSE_PROJECT = os.environ.get("COMPOSE_PROJECT_NAME", "summitflow-stack")
BACKUP_DIR = Path(os.environ.get("BACKUP_DIR", str(Path.home() / "docker-backups")))

_RUNTIME_SERVICE_DEFS: tuple[dict[str, Any], ...] = (
    {
        "service": "summitflow-api",
        "display_name": "summitflow-api",
        "manager": "systemd",
        "category": "app",
        "unit": "summitflow-backend.service",
        "ports": ["8001"],
        "probe_url": "http://localhost:8001/health",
    },
    {
        "service": "summitflow-web",
        "display_name": "summitflow-web",
        "manager": "systemd",
        "category": "app",
        "unit": "summitflow-frontend.service",
        "ports": ["3001"],
        "probe_url": "http://localhost:3001/",
    },
    {
        "service": "summitflow-worker",
        "display_name": "summitflow-worker",
        "manager": "systemd",
        "category": "worker",
        "unit": "summitflow-hatchet-worker.service",
        "ports": [],
    },
    {
        "service": "agent-hub-api",
        "display_name": "agent-hub-api",
        "manager": "systemd",
        "category": "app",
        "unit": "agent-hub-backend.service",
        "ports": ["8003"],
        "probe_url": "http://localhost:8003/health",
    },
    {
        "service": "agent-hub-web",
        "display_name": "agent-hub-web",
        "manager": "systemd",
        "category": "app",
        "unit": "agent-hub-frontend.service",
        "ports": ["3003"],
        "probe_url": "http://localhost:3003/",
    },
    {
        "service": "agent-hub-worker",
        "display_name": "agent-hub-worker",
        "manager": "systemd",
        "category": "worker",
        "unit": "agent-hub-hatchet-worker.service",
        "ports": [],
    },
    {
        "service": "terminal-api",
        "display_name": "terminal-api",
        "manager": "systemd",
        "category": "app",
        "unit": "summitflow-terminal.service",
        "ports": ["8002"],
        "probe_url": "http://localhost:8002/health",
    },
    {
        "service": "terminal-web",
        "display_name": "terminal-web",
        "manager": "systemd",
        "category": "app",
        "unit": "summitflow-terminal-frontend.service",
        "ports": ["3002"],
        "probe_url": "http://localhost:3002/",
    },
    {
        "service": "portfolio-api",
        "display_name": "portfolio-api",
        "manager": "systemd",
        "category": "app",
        "unit": "portfolio-backend.service",
        "ports": ["8000"],
        "probe_url": "http://localhost:8000/health",
    },
    {
        "service": "portfolio-web",
        "display_name": "portfolio-web",
        "manager": "systemd",
        "category": "app",
        "unit": "portfolio-frontend.service",
        "ports": ["3000"],
        "probe_url": "http://localhost:3000/",
    },
    {
        "service": "portfolio-worker",
        "display_name": "portfolio-worker",
        "manager": "systemd",
        "category": "worker",
        "unit": "portfolio-hatchet-worker.service",
        "ports": [],
    },
    {
        "service": "monkey-fight",
        "display_name": "monkey-fight",
        "manager": "systemd",
        "category": "app",
        "unit": "monkey-fight.service",
        "ports": ["4001"],
        "probe_url": "http://localhost:4001/",
    },
    {
        "service": "postgres",
        "display_name": "postgres",
        "manager": "docker",
        "category": "infra",
        "container_service": "postgres",
        "ports": ["5432"],
    },
    {
        "service": "redis",
        "display_name": "redis",
        "manager": "docker",
        "category": "infra",
        "container_service": "redis",
        "ports": ["6379"],
    },
    {
        "service": "hatchet",
        "display_name": "hatchet",
        "manager": "docker",
        "category": "infra",
        "container_service": "hatchet",
        "ports": ["7070", "8888"],
    },
)
_RUNTIME_SERVICE_MAP = {svc["service"]: svc for svc in _RUNTIME_SERVICE_DEFS}
