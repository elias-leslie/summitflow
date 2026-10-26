"""Pick the PostgreSQL client whose major version matches the server being dumped.

Dumps are restored into the stack's own server. A newer client writes SQL or archive
formats an older server cannot load (pg_dump 18 emits `SET transaction_timeout`, which
the stack's PostgreSQL 16 rejects), and the `pg_dump` on PATH follows the newest
installed client, which a distribution upgrade changes.
"""

from __future__ import annotations

from pathlib import Path

import psycopg

CLIENT_ROOT = Path("/usr/lib/postgresql")


def server_major(*, host: str, port: str | int, user: str, password: str, dbname: str = "postgres") -> int | None:
    try:
        with psycopg.connect(host=host, port=int(port), user=user, password=password, dbname=dbname, connect_timeout=10) as conn:
            return conn.info.server_version // 10000
    except (psycopg.Error, ValueError):
        return None


def pg_client(name: str, *, host: str, port: str | int, user: str, password: str, dbname: str = "postgres") -> str:
    """Path of the versioned client binary for this server, else the plain command name."""
    major = server_major(host=host, port=port, user=user, password=password, dbname=dbname)
    if major is not None:
        binary = CLIENT_ROOT / str(major) / "bin" / name
        if binary.is_file():
            return str(binary)
    return name
