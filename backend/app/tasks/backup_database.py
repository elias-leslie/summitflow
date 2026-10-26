"""Commands that stream the shared stack's databases to stdout, for the off-site job to pipe straight into restic.

Nothing here writes a file: the dump goes from the database client into the
repository, so a backup never needs disk space for its own copy.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from urllib.parse import unquote, urlsplit

from ..utils import nightshift_stack
from ..utils.pg_client import pg_client
from ..utils.shared_paths import get_compose_env_file

POSTGRES_DUMP_NAME = "postgres-dumpall.sql"
POSTGRES_DUMP_TRAILER = "PostgreSQL database cluster dump complete"
REDIS_DUMP_NAME = "redis-dump.rdb"


def _read_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for raw_line in path.read_text(errors="ignore").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def _compose_container(service: str) -> str | None:
    """Pre-install fallback: the docker CLI is only used while the Nightshift stack unit is missing."""
    if nightshift_stack.stack_installed() or not Path("/var/run/docker.sock").exists():
        return None
    for command in (
        ["docker", "compose", "-p", "summitflow-stack", "ps", "--format", "{{.Name}}", service],
        ["docker", "ps", "--filter", f"label=com.docker.compose.service={service}", "--format", "{{.Names}}"],
    ):
        result = subprocess.run(command, capture_output=True, text=True, check=False)
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip().splitlines()[0]
    return None


def postgres_dump_invocation() -> tuple[list[str], dict[str, str]]:
    """The command and environment that write a full ``pg_dumpall`` of the stack's PostgreSQL to stdout."""
    pg_user = os.environ.get("PGUSER", "admin")
    pg_host = os.environ.get("PGHOST", "localhost")
    container = os.environ.get("POSTGRES_CONTAINER") or _compose_container("postgres")
    if container:
        return ["docker", "exec", container, "pg_dumpall", "-U", pg_user], dict(os.environ)
    # The worker need not export PGPASSWORD: its owner-held administrator URL is the backup credential.
    env = dict(os.environ)
    pg_port = env.get("PGPORT", "5432")
    password = env.get("PGPASSWORD", "")
    if not (env.get("PGUSER") and password):
        admin_url = env.get("POSTGRES_ADMIN_URL") or _read_env_file(Path.home() / ".env.local").get("POSTGRES_ADMIN_URL")
        if admin_url:
            admin = urlsplit(admin_url)
            aliases = {"localhost": "127.0.0.1", "::1": "127.0.0.1"}
            if ((env.get("PGHOST") and aliases.get(pg_host, pg_host) != aliases.get(admin.hostname or "", admin.hostname))
                    or (env.get("PGPORT") and int(pg_port) != (admin.port or 5432))):
                raise RuntimeError("Backup administrator and infrastructure database endpoints differ")
            if admin.username and admin.password:
                pg_user, password = unquote(admin.username), unquote(admin.password)
                pg_host, pg_port = admin.hostname or pg_host, str(admin.port or 5432)
    if not password:
        raise RuntimeError("Configured infrastructure database credentials are unavailable; capture refused")
    env["PGPASSWORD"] = password
    client = pg_client("pg_dumpall", host=pg_host, port=pg_port, user=pg_user, password=password)
    return [client, "-U", pg_user, "-h", pg_host, "-p", pg_port], env


def redis_dump_invocation() -> tuple[list[str], dict[str, str]]:
    """The command and environment that write the stack's Redis RDB snapshot to stdout."""
    env = dict(os.environ)
    password = env.get("REDIS_PASSWORD") or _read_env_file(get_compose_env_file()).get("REDIS_PASSWORD")
    if password:
        env["REDISCLI_AUTH"] = password  # through the environment, never argv
    command = ["redis-cli", "-h", env.get("REDIS_HOST", "localhost"), "-p", env.get("REDIS_PORT", "6379"), "--rdb", "/dev/stdout"]
    return command, env
