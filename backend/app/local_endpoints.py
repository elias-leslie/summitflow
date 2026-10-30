"""Local ports and service URLs, without app.config's validated settings.

Every st start needs DEFAULT_API_BASE and AGENT_HUB_URL; building Settings
(pydantic-settings) and importing psycopg would add about 70 ms to each one.
app.config re-exports these names for the backend.
"""

from __future__ import annotations

import json
import os

from .utils.shared_paths import get_repo_root


# Project ports live in each project's project.identity.json (runtime
# backend_port/frontend_port). SummitFlow reads its own from its identity; the
# infra ports below belong to SummitFlow's own stack.
def _own_runtime_port(key: str) -> int:
    identity = json.loads((get_repo_root() / "project.identity.json").read_text(encoding="utf-8"))
    return int(identity["runtime"][key])


SUMMITFLOW_BACKEND_PORT = _own_runtime_port("backend_port")
SUMMITFLOW_FRONTEND_PORT = _own_runtime_port("frontend_port")


def local_url(project_id: str, key: str) -> str:
    """http://localhost:<port> from another project's identity, or "" when it is not on this host."""
    from .project_identity import get_runtime_port

    try:
        port = get_runtime_port(project_id, key)
    except (OSError, ValueError):  # another project's unreadable identity must not break SummitFlow
        return ""
    return f"http://localhost:{port}" if port else ""


POSTGRES_PORT = 5432
REDIS_PORT = 6379
HATCHET_GRPC_PORT = 7070
HATCHET_HEALTH_PORT = 8888
# Tether (Aico's per-user session daemon) has no TCP port: it serves
# its API on $XDG_RUNTIME_DIR/tether/<instance>/control.sock under
# tether@<instance>.service. TETHER_SOCKET overrides the socket path.
TETHER_DEFAULT_INSTANCE = "default"


def env_or_default(name: str, default: str) -> str:
    """Return stripped env value or default when unset/blank."""
    value = os.getenv(name)
    if value is None:
        return default
    value = value.strip()
    return value or default


DEFAULT_API_BASE = env_or_default("ST_API_BASE", f"http://localhost:{SUMMITFLOW_BACKEND_PORT}/api")
AGENT_HUB_URL = env_or_default("AGENT_HUB_URL", local_url("agent-hub", "backend_port"))
