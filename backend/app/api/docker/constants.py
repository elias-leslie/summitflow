"""Constants and configuration for the runtime management API."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from ...config import (
    AGENT_HUB_BACKEND_PORT,
    AGENT_HUB_FRONTEND_PORT,
    ATERM_BACKEND_PORT,
    ATERM_FRONTEND_PORT,
    HATCHET_GRPC_PORT,
    HATCHET_HEALTH_PORT,
    MONKEY_FIGHT_PORT,
    PORTFOLIO_BACKEND_PORT,
    PORTFOLIO_FRONTEND_PORT,
    POSTGRES_PORT,
    REDIS_PORT,
    SUMMITFLOW_BACKEND_PORT,
    SUMMITFLOW_FRONTEND_PORT,
    TEST1_BACKEND_PORT,
    TEST1_FRONTEND_PORT,
    TEST2_BACKEND_PORT,
    TEST2_FRONTEND_PORT,
    TEST3_BACKEND_PORT,
    TEST3_FRONTEND_PORT,
    VANTAGE_BACKEND_PORT,
    VANTAGE_FRONTEND_PORT,
)
from ...utils.env import float_env as _float_env


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
_INFRA_SERVICES = {"postgres", "redis", "hatchet", "hatchet-migrate", "hatchet-setup-config", "docker-socket-proxy"}
_DOCKER_SOCKET = Path("/var/run/docker.sock")
_DOCKER_GID_RAW = os.environ.get("DOCKER_GID", "")
_DOCKER_GID: int | None = int(_DOCKER_GID_RAW) if _DOCKER_GID_RAW.isdigit() else None
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
        "ports": [str(SUMMITFLOW_BACKEND_PORT)],
        "probe_url": f"http://localhost:{SUMMITFLOW_BACKEND_PORT}/health",
    },
    {
        "service": "summitflow-web",
        "display_name": "summitflow-web",
        "manager": "systemd",
        "category": "app",
        "unit": "summitflow-frontend.service",
        "ports": [str(SUMMITFLOW_FRONTEND_PORT)],
        "probe_url": f"http://localhost:{SUMMITFLOW_FRONTEND_PORT}/",
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
        "ports": [str(AGENT_HUB_BACKEND_PORT)],
        "probe_url": f"http://localhost:{AGENT_HUB_BACKEND_PORT}/health",
    },
    {
        "service": "agent-hub-web",
        "display_name": "agent-hub-web",
        "manager": "systemd",
        "category": "app",
        "unit": "agent-hub-frontend.service",
        "ports": [str(AGENT_HUB_FRONTEND_PORT)],
        "probe_url": f"http://localhost:{AGENT_HUB_FRONTEND_PORT}/",
    },
    {
        "service": "agent-hub-worker",
        "display_name": "agent-hub-worker",
        "manager": "systemd",
        "category": "worker",
        "unit": "agent-hub-hatchet-agent-worker.service",
        "ports": [],
    },
    {
        "service": "agent-hub-ops-worker",
        "display_name": "agent-hub-ops-worker",
        "manager": "systemd",
        "category": "worker",
        "unit": "agent-hub-hatchet-ops-worker.service",
        "ports": [],
    },
    {
        "service": "aterm-api",
        "display_name": "aterm-api",
        "manager": "systemd",
        "category": "app",
        "unit": "aterm-backend.service",
        "ports": [str(ATERM_BACKEND_PORT)],
        "probe_url": f"http://localhost:{ATERM_BACKEND_PORT}/health",
    },
    {
        "service": "aterm-web",
        "display_name": "aterm-web",
        "manager": "systemd",
        "category": "app",
        "unit": "aterm-frontend.service",
        "ports": [str(ATERM_FRONTEND_PORT)],
        "probe_url": f"http://localhost:{ATERM_FRONTEND_PORT}/",
    },
    {
        "service": "portfolio-api",
        "display_name": "portfolio-api",
        "manager": "systemd",
        "category": "app",
        "unit": "portfolio-backend.service",
        "ports": [str(PORTFOLIO_BACKEND_PORT)],
        "probe_url": f"http://localhost:{PORTFOLIO_BACKEND_PORT}/health",
    },
    {
        "service": "portfolio-web",
        "display_name": "portfolio-web",
        "manager": "systemd",
        "category": "app",
        "unit": "portfolio-frontend.service",
        "ports": [str(PORTFOLIO_FRONTEND_PORT)],
        "probe_url": f"http://localhost:{PORTFOLIO_FRONTEND_PORT}/",
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
        "service": "vantage-api",
        "display_name": "vantage-api",
        "manager": "systemd",
        "category": "app",
        "unit": "vantage-backend.service",
        "ports": [str(VANTAGE_BACKEND_PORT)],
        "probe_url": f"http://localhost:{VANTAGE_BACKEND_PORT}/health",
    },
    {
        "service": "vantage-web",
        "display_name": "vantage-web",
        "manager": "systemd",
        "category": "app",
        "unit": "vantage-frontend.service",
        "ports": [str(VANTAGE_FRONTEND_PORT)],
        "probe_url": f"http://localhost:{VANTAGE_FRONTEND_PORT}/",
    },
    {
        "service": "vantage-worker",
        "display_name": "vantage-worker",
        "manager": "systemd",
        "category": "worker",
        "unit": "vantage-hatchet-worker.service",
        "ports": [],
    },
    {
        "service": "monkey-fight",
        "display_name": "monkey-fight",
        "manager": "systemd",
        "category": "app",
        "unit": "monkey-fight.service",
        "ports": [str(MONKEY_FIGHT_PORT)],
        "probe_url": f"http://localhost:{MONKEY_FIGHT_PORT}/",
    },
    {
        "service": "test1-api",
        "display_name": "test1-api",
        "manager": "systemd",
        "category": "app",
        "unit": "test1-backend.service",
        "ports": [str(TEST1_BACKEND_PORT)],
        "probe_url": f"http://localhost:{TEST1_BACKEND_PORT}/health",
    },
    {
        "service": "test1-web",
        "display_name": "test1-web",
        "manager": "systemd",
        "category": "app",
        "unit": "test1-frontend.service",
        "ports": [str(TEST1_FRONTEND_PORT)],
        "probe_url": f"http://localhost:{TEST1_FRONTEND_PORT}/",
    },
    {
        "service": "test2-api",
        "display_name": "test2-api",
        "manager": "systemd",
        "category": "app",
        "unit": "test2-backend.service",
        "ports": [str(TEST2_BACKEND_PORT)],
        "probe_url": f"http://localhost:{TEST2_BACKEND_PORT}/health",
    },
    {
        "service": "test2-web",
        "display_name": "test2-web",
        "manager": "systemd",
        "category": "app",
        "unit": "test2-frontend.service",
        "ports": [str(TEST2_FRONTEND_PORT)],
        "probe_url": f"http://localhost:{TEST2_FRONTEND_PORT}/",
    },
    {
        "service": "test3-api",
        "display_name": "test3-api",
        "manager": "systemd",
        "category": "app",
        "unit": "test3-backend.service",
        "ports": [str(TEST3_BACKEND_PORT)],
        "probe_url": f"http://localhost:{TEST3_BACKEND_PORT}/health",
    },
    {
        "service": "test3-web",
        "display_name": "test3-web",
        "manager": "systemd",
        "category": "app",
        "unit": "test3-frontend.service",
        "ports": [str(TEST3_FRONTEND_PORT)],
        "probe_url": f"http://localhost:{TEST3_FRONTEND_PORT}/",
    },
    {
        "service": "postgres",
        "display_name": "postgres",
        "manager": "docker",
        "category": "infra",
        "container_service": "postgres",
        "ports": [str(POSTGRES_PORT)],
    },
    {
        "service": "redis",
        "display_name": "redis",
        "manager": "docker",
        "category": "infra",
        "container_service": "redis",
        "ports": [str(REDIS_PORT)],
    },
    {
        "service": "hatchet",
        "display_name": "hatchet",
        "manager": "docker",
        "category": "infra",
        "container_service": "hatchet",
        "ports": [str(HATCHET_GRPC_PORT), str(HATCHET_HEALTH_PORT)],
    },
)
_RUNTIME_SERVICE_MAP = {svc["service"]: svc for svc in _RUNTIME_SERVICE_DEFS}
