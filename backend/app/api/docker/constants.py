"""Constants and configuration for the runtime management API."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from ...config import HATCHET_GRPC_PORT, HATCHET_HEALTH_PORT, POSTGRES_PORT, REDIS_PORT
from ...utils.env import float_env as _float_env


def _detect_repo_root(start_path: Path | None = None) -> Path:
    current = (start_path or Path(__file__).resolve()).parent
    for candidate in (current, *current.parents):
        if (candidate / "backend" / "cli").exists() and (candidate / "backend" / "app").exists():
            return candidate
    return Path(__file__).resolve().parents[4]


_INTERNAL_SECRET = os.environ.get("INTERNAL_SERVICE_SECRET", "")

_REPO_ROOT = _detect_repo_root()
_DEFAULT_STACK_MODE = os.environ.get("SUMMITFLOW_DOCKER_DEFAULT_MODE", "prod")
if _DEFAULT_STACK_MODE not in {"dev", "prod"}:
    _DEFAULT_STACK_MODE = "prod"
_COMPOSE_DIR = Path(os.environ.get("COMPOSE_DIR", str(_REPO_ROOT / "docker" / "compose")))
_COMPOSE_FILE = _COMPOSE_DIR / "docker-compose.yml"
_RUNTIME_MODE_FILE = _COMPOSE_DIR / ".runtime-mode"
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

# SummitFlow's own infra containers. Project services come from each
# project's project.identity.json (see runtime_service_definitions).
_RUNTIME_SERVICE_DEFS: tuple[dict[str, Any], ...] = (
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

def runtime_service_definitions() -> tuple[dict[str, Any], ...]:
    """Infra containers plus the services each active project declares in its identity."""
    from ...project_identity import get_project_lifecycles, list_project_identities
    from ...runtime_deployment import parse_deployment

    identities = [
        identity for identity in list_project_identities()
        if isinstance(identity.get("project"), dict) and isinstance(identity["project"].get("id"), str)
    ]
    lifecycles = get_project_lifecycles(
        sorted({identity["project"]["id"] for identity in identities}), allow_unavailable=True,
    )
    definitions = {svc["service"]: dict(svc) for svc in _RUNTIME_SERVICE_DEFS}
    for identity in identities:
        project_id = identity["project"]["id"]
        if lifecycles.get(project_id) != "active":
            continue
        services = identity.get("services") or {}
        runtime = identity.get("runtime") or {}
        deployment = parse_deployment(runtime.get("deployment"))
        roles = [
            (services.get("backend"), "api", runtime.get("backend_port"), runtime.get("health_endpoint", "/health")),
            (services.get("frontend"), "web", runtime.get("frontend_port"), "/"),
            *((unit, "worker", None, None) for unit in (
                *services.get("default_workers", []), *services.get("optional_workers", []),
                *services.get("manual_workers", []),
            )),
        ]
        seen: set[str] = set()
        for unit, role, port, health_path in roles:
            if not unit or unit in seen:
                continue
            seen.add(unit)
            service = unit.removesuffix(".service") if role == "worker" else f"{project_id}-{role}"
            definition = {
                "service": service, "display_name": service, "manager": "systemd",
                "category": "worker" if role == "worker" else "app", "unit": unit,
                "ports": [str(port)] if port else [], "project_id": project_id,
            }
            if port and health_path:
                definition["probe_url"] = f"http://localhost:{port}{health_path}"
            if deployment:
                definition["deployment"] = deployment.as_dict()
            definitions[service] = definition
    return tuple(definitions.values())
