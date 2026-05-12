"""Database target discovery for the Pgweb workbench."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote, urlsplit, urlunsplit

import psycopg

from ..project_identity import get_project_identity

_DEFAULT_DB_URLS = {
    "summitflow": "postgresql://summitflow_app@localhost:5432/summitflow",
    "agent-hub": "postgresql://agent_hub_app@localhost:5432/agent_hub",
    "portfolio-ai": "postgresql://portfolio_app@localhost:5432/portfolio_ai",
    "a-term": "postgresql://summitflow_app@localhost:5432/summitflow",
    "hatchet": "postgresql://db_admin@localhost:5432/hatchet?sslmode=disable",
}

_GLOBAL_PROJECT_ID = "__global__"
_GLOBAL_DATABASE_NAME = "postgres"
_DATABASE_TARGET_PREFIX = "__db__"


@dataclass(frozen=True)
class DbWorkbenchTarget:
    id: str
    label: str
    database: str | None
    configured: bool
    source: str
    shared_with: str | None = None


def load_env_file(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    values: dict[str, str] = {}
    for raw_line in path.read_text().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in raw_line:
            continue
        key, value = raw_line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def env_values() -> dict[str, str]:
    values: dict[str, str] = {}
    env_paths = (
        Path.home() / ".env.local",
        Path.home() / "summitflow" / "docker" / "compose" / ".env",
    )
    for path in env_paths:
        values.update(load_env_file(path))
    return values


def project_env_var(project_id: str) -> str:
    if project_id == _GLOBAL_PROJECT_ID or database_name_from_target(project_id):
        return "DATABASE_ADMIN_URL"
    if project_id == "summitflow":
        return "DATABASE_URL"
    return f"{project_id.replace('-', '_').upper()}_DB_URL"


def shared_db_project_id(project_id: str) -> str | None:
    if project_id == _GLOBAL_PROJECT_ID or database_name_from_target(project_id):
        return None
    identity = get_project_identity(project_id)
    database = identity.get("database") if identity else None
    if not isinstance(database, dict):
        return None
    shared_with = database.get("shared_with")
    if isinstance(shared_with, str) and shared_with and shared_with != project_id:
        return shared_with
    return None


def safe_database_name(database_name: str) -> bool:
    return bool(database_name) and all(
        char.isalnum() or char in {"_", "-", "."} for char in database_name
    )


def database_target_id(database_name: str) -> str:
    return f"{_DATABASE_TARGET_PREFIX}{database_name}"


def database_name_from_target(project_id: str) -> str | None:
    if not project_id.startswith(_DATABASE_TARGET_PREFIX):
        return None
    database_name = project_id.removeprefix(_DATABASE_TARGET_PREFIX)
    return database_name if safe_database_name(database_name) else None


def database_url_for_database(url: str, database_name: str) -> str:
    parts = urlsplit(url)
    if not parts.scheme or not parts.netloc:
        return url
    return urlunsplit(
        (parts.scheme, parts.netloc, f"/{database_name}", parts.query, parts.fragment)
    )


def global_db_url(database_name: str = _GLOBAL_DATABASE_NAME) -> str | None:
    env_file = env_values()
    admin_url = os.environ.get("DATABASE_ADMIN_URL") or env_file.get(
        "DATABASE_ADMIN_URL"
    )
    if admin_url:
        return database_url_for_database(admin_url, database_name)

    password = os.environ.get("POSTGRES_PASSWORD") or env_file.get("POSTGRES_PASSWORD")
    if not password:
        return None

    user = os.environ.get("POSTGRES_USER") or env_file.get("POSTGRES_USER") or "admin"
    host = (
        os.environ.get("POSTGRES_HOST")
        or env_file.get("POSTGRES_HOST")
        or "localhost"
    )
    port = os.environ.get("POSTGRES_PORT") or env_file.get("POSTGRES_PORT") or "5432"
    user_info = f"{quote(user, safe='')}:{quote(password, safe='')}"
    return f"postgresql://{user_info}@{host}:{port}/{database_name}"


def project_db_url(project_id: str) -> str | None:
    database_name = database_name_from_target(project_id)
    if database_name:
        return global_db_url(database_name)

    if project_id == _GLOBAL_PROJECT_ID:
        return global_db_url()

    env_file = env_values()
    key = project_env_var(project_id)
    shared_project_id = shared_db_project_id(project_id)
    candidates = [
        os.environ.get(key),
        env_file.get(key),
        os.environ.get("DATABASE_URL") if project_id == "summitflow" else None,
        env_file.get("DATABASE_URL") if project_id == "summitflow" else None,
        project_db_url(shared_project_id) if shared_project_id else None,
        _DEFAULT_DB_URLS.get(project_id),
    ]
    return next((candidate for candidate in candidates if candidate), None)


def database_name_from_url(url: str | None) -> str | None:
    if not url:
        return None
    path = urlsplit(url).path.lstrip("/")
    return path or None


def project_ids_from_env(env_file: dict[str, str]) -> set[str]:
    project_ids = set(_DEFAULT_DB_URLS)
    values = {**env_file, **os.environ}
    for key, value in values.items():
        if not value or key.startswith("TEST"):
            continue
        if key == "DATABASE_URL":
            project_ids.add("summitflow")
        elif key.endswith("_DB_URL"):
            project_ids.add(key.removesuffix("_DB_URL").lower().replace("_", "-"))
    return project_ids


def server_database_names() -> list[str]:
    db_url = global_db_url()
    if not db_url:
        return []
    try:
        with psycopg.connect(db_url, connect_timeout=1) as conn, conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT datname
                FROM pg_database
                WHERE datallowconn
                  AND NOT datistemplate
                ORDER BY datname
                """
            )
            return [
                str(row[0])
                for row in cursor.fetchall()
                if safe_database_name(str(row[0]))
            ]
    except psycopg.Error:
        return []


def workbench_targets() -> list[DbWorkbenchTarget]:
    env_file = env_values()
    targets = [
        DbWorkbenchTarget(
            id=_GLOBAL_PROJECT_ID,
            label="Server catalog",
            database=_GLOBAL_DATABASE_NAME,
            configured=global_db_url() is not None,
            source="admin",
        )
    ]

    seen_ids = {_GLOBAL_PROJECT_ID}
    for database_name in server_database_names():
        target_id = database_target_id(database_name)
        targets.append(
            DbWorkbenchTarget(
                id=target_id,
                label=database_name,
                database=database_name,
                configured=project_db_url(target_id) is not None,
                source="database",
            )
        )
        seen_ids.add(target_id)

    for project_id in sorted(project_ids_from_env(env_file)):
        if project_id in seen_ids:
            continue
        db_url = project_db_url(project_id)
        if not db_url:
            continue
        shared_with = shared_db_project_id(project_id)
        database = database_name_from_url(db_url)
        if database and database_target_id(database) in seen_ids and not shared_with:
            continue
        label = project_id
        if shared_with:
            label = f"{project_id} -> {shared_with}"
        targets.append(
            DbWorkbenchTarget(
                id=project_id,
                label=label,
                database=database,
                configured=True,
                source="project",
                shared_with=shared_with,
            )
        )
        seen_ids.add(project_id)

    return targets
