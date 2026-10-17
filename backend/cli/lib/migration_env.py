"""Environment for a managed project's Alembic run.

Which secret keys a project's migrations receive, and from which env files,
comes from SummitFlow's own table (scripts/lib/migration-env.json), never from
the project's repo. The migration env starts from a small set of non-secret
process variables, so nothing else the operator shell holds (PVE tokens,
internal secrets, other projects' database URLs) reaches it.
"""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from dotenv import dotenv_values

from app.utils.env_files import project_env_files

_TABLE_PATH = Path(__file__).resolve().parents[3] / "scripts" / "lib" / "migration-env.json"

# Secrets that never reach a migration through the process env, whatever the
# table says. Applied to st db's os.environ copy as well.
STRIP_FLOOR = frozenset({
    "DATABASE_URL", "POSTGRES_ADMIN_URL", "DATABASE_ADMIN_URL",
    "REDIS_URL", "AGENT_HUB_REDIS_URL", "HATCHET_CLIENT_TOKEN",
    "INTERNAL_SERVICE_SECRET", "AGENT_HUB_INTERNAL_SECRET",
})
# Non-secret process variables a migration may inherit.
_BASE_KEYS = frozenset({
    "PATH", "HOME", "USER", "LOGNAME", "SHELL", "LANG", "LANGUAGE", "TZ", "TMPDIR", "TERM",
    "XDG_RUNTIME_DIR", "XDG_CONFIG_HOME", "XDG_CACHE_HOME", "XDG_DATA_HOME", "XDG_STATE_HOME",
})
_SOURCES = ("shared", "project", "backend/.env")  # later sources win
_DEFAULT = ("DATABASE_URL", frozenset({"DATABASE_URL"}), ("project",))


@dataclass(frozen=True)
class MigrationGrant:
    database_key: str
    keys: frozenset[str]
    sources: tuple[str, ...]


@lru_cache(maxsize=4)
def _load(path: Path = _TABLE_PATH) -> dict[str, MigrationGrant]:
    raw = json.loads(path.read_text(encoding="utf-8")).get("projects")
    if not isinstance(raw, dict):
        raise ValueError(f"{path}: projects must be an object")
    grants: dict[str, MigrationGrant] = {}
    owners: dict[str, str] = {}
    for project_id, entry in raw.items():
        keys = entry.get("keys") if isinstance(entry, dict) else None
        sources = entry.get("sources") if isinstance(entry, dict) else None
        database_key = entry.get("database_key") if isinstance(entry, dict) else None
        if (not isinstance(keys, list) or not keys or not all(isinstance(key, str) and key for key in keys)
                or not isinstance(sources, list) or not sources or not set(sources) <= set(_SOURCES)
                or database_key not in keys):
            raise ValueError(f"{path}: invalid migration grant for {project_id}")
        for key in keys:
            if key in owners:
                raise ValueError(f"{path}: {key} is granted to both {owners[key]} and {project_id}")
            owners[key] = project_id
        grants[project_id] = MigrationGrant(str(database_key), frozenset(str(key) for key in keys),
                                            tuple(s for s in _SOURCES if s in sources))
    return grants


def grant_for(project_id: str) -> MigrationGrant:
    """The project's granted keys; unlisted projects get DATABASE_URL from their own env files."""
    return _load().get(project_id) or MigrationGrant(*_DEFAULT)


def strip_keys() -> frozenset[str]:
    """Every key the table grants to any project, plus the code floor."""
    return STRIP_FLOOR.union(*(grant.keys for grant in _load().values()))


def migration_env(project_id: str, host_root: Path, *, environ: Mapping[str, str] | None = None) -> dict[str, str]:
    source = os.environ if environ is None else environ
    env = {key: value for key, value in source.items() if key in _BASE_KEYS or key.startswith("LC_")}
    for key in strip_keys():
        env.pop(key, None)
    grant = grant_for(project_id)
    files = {
        "shared": [Path.home() / ".env.local"],
        "project": project_env_files(host_root),
        "backend/.env": [host_root / "backend" / ".env"],
    }
    for name in grant.sources:
        for path in files[name]:
            if path.name == ".env.example" or not path.is_file():
                continue
            for key, value in dotenv_values(path, interpolate=False).items():
                if key in grant.keys and value is not None:
                    env[key] = value
    return env
