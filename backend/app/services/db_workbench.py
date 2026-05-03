"""On-demand Pgweb process management for project databases."""

from __future__ import annotations

import json
import os
import shutil
import signal
import socket
import time
from contextlib import suppress
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from typing import Any
from urllib import error as urllib_error
from urllib import request as urllib_request
from urllib.parse import quote, urlsplit, urlunsplit

import psutil
import psycopg

from ..project_identity import get_project_identity

_DEFAULT_DB_URLS = {
    "summitflow": "postgresql://summitflow_app@localhost:5432/summitflow",
    "agent-hub": "postgresql://agent_hub_app@localhost:5432/agent_hub",
    "portfolio-ai": "postgresql://portfolio_app@localhost:5432/portfolio_ai",
    "a-term": "postgresql://summitflow_app@localhost:5432/summitflow",
    "hatchet": "postgresql://db_admin@localhost:5432/hatchet?sslmode=disable",
}

_BIND_HOST = "127.0.0.1"
_PORT_BASE = 9081
_START_TIMEOUT_SECONDS = 5.0
_QUERY_TIMEOUT_SECONDS = 60
_GLOBAL_PROJECT_ID = "__global__"
_GLOBAL_DATABASE_NAME = "postgres"
_DATABASE_TARGET_PREFIX = "__db__"


class DbWorkbenchError(RuntimeError):
    """Raised when Pgweb cannot be started or controlled."""


@dataclass(frozen=True)
class DbWorkbenchStatus:
    project_id: str
    running: bool
    installed: bool
    configured: bool
    readonly: bool
    pid: int | None
    port: int | None
    proxy_url: str
    direct_url: str | None
    shared_with: str | None
    started_at: str | None
    message: str | None = None


@dataclass(frozen=True)
class DbWorkbenchTarget:
    id: str
    label: str
    database: str | None
    configured: bool
    source: str
    shared_with: str | None = None


def _safe_project_id(project_id: str) -> str:
    return "".join(
        char if char.isalnum() or char in {"-", "_"} else "-"
        for char in project_id
    )


def _state_dir() -> Path:
    default = Path.home() / ".cache" / "summitflow" / "pgweb"
    return Path(os.environ.get("SUMMITFLOW_PGWEB_STATE_DIR", default))


def _state_path(project_id: str) -> Path:
    return _state_dir() / f"{_safe_project_id(project_id)}.json"


def _log_path(project_id: str) -> Path:
    return _state_dir() / f"{_safe_project_id(project_id)}.log"


def proxy_prefix(project_id: str) -> str:
    return f"/api/projects/{project_id}/db-workbench/proxy"


def _pgweb_prefix(project_id: str) -> str:
    return proxy_prefix(project_id).lstrip("/")


def proxy_url(project_id: str) -> str:
    return f"{proxy_prefix(project_id)}/"


def _load_env_file(path: Path) -> dict[str, str]:
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


def _env_values() -> dict[str, str]:
    values: dict[str, str] = {}
    env_paths = (
        Path.home() / ".env.local",
        Path.home() / "summitflow" / "docker" / "compose" / ".env",
    )
    for path in env_paths:
        values.update(_load_env_file(path))
    return values


def _project_env_var(project_id: str) -> str:
    if project_id == _GLOBAL_PROJECT_ID or _database_name_from_target(project_id):
        return "DATABASE_ADMIN_URL"
    if project_id == "summitflow":
        return "DATABASE_URL"
    return f"{project_id.replace('-', '_').upper()}_DB_URL"


def _shared_db_project_id(project_id: str) -> str | None:
    if project_id == _GLOBAL_PROJECT_ID or _database_name_from_target(project_id):
        return None
    identity = get_project_identity(project_id)
    database = identity.get("database") if identity else None
    if not isinstance(database, dict):
        return None
    shared_with = database.get("shared_with")
    if isinstance(shared_with, str) and shared_with and shared_with != project_id:
        return shared_with
    return None


def _safe_database_name(database_name: str) -> bool:
    return bool(database_name) and all(
        char.isalnum() or char in {"_", "-", "."} for char in database_name
    )


def _database_target_id(database_name: str) -> str:
    return f"{_DATABASE_TARGET_PREFIX}{database_name}"


def _database_name_from_target(project_id: str) -> str | None:
    if not project_id.startswith(_DATABASE_TARGET_PREFIX):
        return None
    database_name = project_id.removeprefix(_DATABASE_TARGET_PREFIX)
    return database_name if _safe_database_name(database_name) else None


def _database_url_for_database(url: str, database_name: str) -> str:
    parts = urlsplit(url)
    if not parts.scheme or not parts.netloc:
        return url
    return urlunsplit(
        (parts.scheme, parts.netloc, f"/{database_name}", parts.query, parts.fragment)
    )


def _global_db_url(database_name: str = _GLOBAL_DATABASE_NAME) -> str | None:
    env_file = _env_values()
    admin_url = os.environ.get("DATABASE_ADMIN_URL") or env_file.get(
        "DATABASE_ADMIN_URL"
    )
    if admin_url:
        return _database_url_for_database(admin_url, database_name)

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
    database_name = _database_name_from_target(project_id)
    if database_name:
        return _global_db_url(database_name)

    if project_id == _GLOBAL_PROJECT_ID:
        return _global_db_url()

    env_file = _env_values()
    key = _project_env_var(project_id)
    shared_project_id = _shared_db_project_id(project_id)
    candidates = [
        os.environ.get(key),
        env_file.get(key),
        os.environ.get("DATABASE_URL") if project_id == "summitflow" else None,
        env_file.get("DATABASE_URL") if project_id == "summitflow" else None,
        project_db_url(shared_project_id) if shared_project_id else None,
        _DEFAULT_DB_URLS.get(project_id),
    ]
    return next((candidate for candidate in candidates if candidate), None)


def _database_name_from_url(url: str | None) -> str | None:
    if not url:
        return None
    path = urlsplit(url).path.lstrip("/")
    return path or None


def _project_ids_from_env(env_file: dict[str, str]) -> set[str]:
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


def _server_database_names() -> list[str]:
    db_url = _global_db_url()
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
                if _safe_database_name(str(row[0]))
            ]
    except psycopg.Error:
        return []


def workbench_targets() -> list[DbWorkbenchTarget]:
    env_file = _env_values()
    targets = [
        DbWorkbenchTarget(
            id=_GLOBAL_PROJECT_ID,
            label="Server catalog",
            database=_GLOBAL_DATABASE_NAME,
            configured=_global_db_url() is not None,
            source="admin",
        )
    ]

    seen_ids = {_GLOBAL_PROJECT_ID}
    for database_name in _server_database_names():
        target_id = _database_target_id(database_name)
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

    for project_id in sorted(_project_ids_from_env(env_file)):
        if project_id in seen_ids:
            continue
        db_url = project_db_url(project_id)
        if not db_url:
            continue
        shared_with = _shared_db_project_id(project_id)
        database = _database_name_from_url(db_url)
        if database and _database_target_id(database) in seen_ids and not shared_with:
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


def _pgweb_binary() -> str | None:
    configured = os.environ.get("PGWEB_BIN", "pgweb")
    if Path(configured).is_absolute() and Path(configured).exists():
        return configured
    return shutil.which(configured)


def _spawn_pgweb(args: list[str], env: dict[str, str], log_path: Path) -> int:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_WRONLY | os.O_CREAT | os.O_APPEND
    cloexec = getattr(os, "O_CLOEXEC", 0)
    log_fd = os.open(log_path, flags | cloexec, 0o644)
    stdin_fd = os.open(os.devnull, os.O_RDONLY | cloexec)
    try:
        file_actions = [
            (os.POSIX_SPAWN_DUP2, stdin_fd, 0),
            (os.POSIX_SPAWN_DUP2, log_fd, 1),
            (os.POSIX_SPAWN_DUP2, log_fd, 2),
            (os.POSIX_SPAWN_CLOSE, stdin_fd),
            (os.POSIX_SPAWN_CLOSE, log_fd),
        ]
        try:
            return os.posix_spawn(
                args[0],
                args,
                env,
                file_actions=file_actions,
                setsid=True,
            )
        except NotImplementedError:
            return os.posix_spawn(
                args[0],
                args,
                env,
                file_actions=file_actions,
                setsid=False,
            )
    except OSError as exc:
        raise DbWorkbenchError(f"Failed to launch pgweb: {exc}") from exc
    finally:
        os.close(stdin_fd)
        os.close(log_fd)


def _read_state(project_id: str) -> dict[str, Any] | None:
    path = _state_path(project_id)
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _optional_int(value: object) -> int | None:
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return None
    return None


def _write_state(project_id: str, payload: dict[str, Any]) -> None:
    path = _state_path(project_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, sort_keys=True, indent=2))


def _remove_state(project_id: str) -> None:
    _state_path(project_id).unlink(missing_ok=True)


def _pid_is_pgweb(pid: int | None) -> bool:
    if not pid:
        return False
    try:
        proc = psutil.Process(pid)
        if not proc.is_running() or proc.status() == psutil.STATUS_ZOMBIE:
            return False
        cmdline = " ".join(proc.cmdline()).lower()
        return "pgweb" in proc.name().lower() or "pgweb" in cmdline
    except (psutil.Error, OSError):
        return False


def _reap_process(pid: int | None, timeout: float = 0.3) -> None:
    if not pid:
        return
    with suppress(ChildProcessError, psutil.Error, OSError):
        psutil.Process(pid).wait(timeout=timeout)


def _port_is_available(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.2)
        return sock.connect_ex((_BIND_HOST, port)) != 0


def _port_from_env(project_id: str) -> int | None:
    specific = f"PGWEB_PORT_{project_id.replace('-', '_').upper()}"
    raw = os.environ.get(specific) or os.environ.get("PGWEB_PORT")
    if not raw:
        return None
    try:
        return int(raw)
    except ValueError:
        raise DbWorkbenchError(f"{specific}/PGWEB_PORT must be an integer") from None


def _choose_port(project_id: str) -> int:
    configured = _port_from_env(project_id)
    if configured is not None:
        if _port_is_available(configured):
            return configured
        raise DbWorkbenchError(f"Pgweb port {configured} is already in use")

    digest = int(sha256(project_id.encode("utf-8")).hexdigest()[:8], 16)
    start = _PORT_BASE + (digest % 200)
    for port in [*range(start, start + 100), *range(_PORT_BASE, _PORT_BASE + 300)]:
        if _port_is_available(port):
            return port
    raise DbWorkbenchError("No free Pgweb port found")


def _tail_log(project_id: str, max_chars: int = 1000) -> str:
    path = _log_path(project_id)
    if not path.exists():
        return ""
    try:
        return path.read_text(errors="replace")[-max_chars:].strip()
    except OSError:
        return ""


def _probe_http(url: str) -> bool:
    try:
        with urllib_request.urlopen(url, timeout=0.35) as response:
            return 200 <= response.status < 500
    except urllib_error.HTTPError as exc:
        return 200 <= exc.code < 500
    except (OSError, urllib_error.URLError):
        return False


def _wait_until_ready(project_id: str, direct_url: str) -> bool:
    deadline = time.monotonic() + _START_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        if _probe_http(direct_url):
            return True
        state = _read_state(project_id)
        pid = _optional_int(state.get("pid") if state else None)
        if pid and not _pid_is_pgweb(pid):
            return False
        time.sleep(0.15)
    return False


def status_workbench(project_id: str, *, message: str | None = None) -> DbWorkbenchStatus:
    state = _read_state(project_id) or {}
    pid = _optional_int(state.get("pid"))
    running = _pid_is_pgweb(pid)
    if state and not running:
        _remove_state(project_id)
    port = _optional_int(state.get("port")) if running else None
    direct_url = f"http://{_BIND_HOST}:{port}/{_pgweb_prefix(project_id)}/" if port else None
    db_url = project_db_url(project_id)
    shared_with = _shared_db_project_id(project_id)
    return DbWorkbenchStatus(
        project_id=project_id,
        running=running,
        installed=_pgweb_binary() is not None,
        configured=db_url is not None,
        readonly=bool(state.get("readonly", True)),
        pid=pid if running else None,
        port=port,
        proxy_url=proxy_url(project_id),
        direct_url=direct_url,
        shared_with=shared_with,
        started_at=str(state.get("started_at")) if running and state.get("started_at") else None,
        message=message,
    )


def start_workbench(project_id: str, *, readonly: bool = True) -> DbWorkbenchStatus:
    current = status_workbench(project_id)
    if current.running:
        return current

    binary = _pgweb_binary()
    if not binary:
        raise DbWorkbenchError("pgweb binary not found; install pgweb or set PGWEB_BIN")

    db_url = project_db_url(project_id)
    if not db_url:
        raise DbWorkbenchError(
            f"No database URL configured for {project_id}; set {_project_env_var(project_id)}"
        )

    port = _choose_port(project_id)
    prefix = _pgweb_prefix(project_id)
    direct_url = f"http://{_BIND_HOST}:{port}/{prefix}/"
    args = [
        binary,
        f"--bind={_BIND_HOST}",
        f"--listen={port}",
        "--skip-open",
        "--lock-session",
        "--no-ssh",
        f"--query-timeout={_QUERY_TIMEOUT_SECONDS}",
        f"--prefix={prefix}",
    ]
    if readonly:
        args.append("--readonly")

    env = os.environ.copy()
    env["PGWEB_DATABASE_URL"] = db_url
    env["PGWEB_URL_PREFIX"] = prefix
    env["PGWEB_LOCK_SESSION"] = "1"

    pid = _spawn_pgweb(args, env, _log_path(project_id))

    state = {
        "project_id": project_id,
        "pid": pid,
        "port": port,
        "readonly": readonly,
        "prefix": prefix,
        "started_at": datetime.now(UTC).isoformat(),
    }
    _write_state(project_id, state)

    if not _wait_until_ready(project_id, direct_url):
        stop_workbench(project_id)
        detail = _tail_log(project_id)
        suffix = f": {detail}" if detail else ""
        raise DbWorkbenchError(f"Pgweb failed to start{suffix}")

    return status_workbench(project_id, message="Pgweb started")


def stop_workbench(project_id: str) -> DbWorkbenchStatus:
    state = _read_state(project_id) or {}
    pid = _optional_int(state.get("pid"))
    if pid and _pid_is_pgweb(pid):
        with suppress(OSError):
            os.kill(pid, signal.SIGTERM)
        deadline = time.monotonic() + 3.0
        while time.monotonic() < deadline and _pid_is_pgweb(pid):
            time.sleep(0.1)
        _reap_process(pid)
        if _pid_is_pgweb(pid):
            with suppress(OSError):
                os.kill(pid, signal.SIGKILL)
            _reap_process(pid)
    _remove_state(project_id)
    return status_workbench(project_id, message="Pgweb stopped")


def status_payload(status: DbWorkbenchStatus) -> dict[str, Any]:
    return asdict(status)
