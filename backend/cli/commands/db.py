"""Canonical database command surface."""

from __future__ import annotations

import fcntl
import hashlib
import os
import re
import subprocess
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import typer

from app.services.db_workbench import (
    DbWorkbenchError,
    start_workbench,
    status_workbench,
    stop_workbench,
)
from app.storage.projects import find_project_by_cwd, get_project_root_path

from ..details import emit_result_or_details
from ..lib.usage import usage
from ..output import output_error

app = typer.Typer(
    help="Database inspection and migration commands through the managed st surface.",
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True, "help_option_names": []},
    add_help_option=False,
)

_DEFAULT_DB_URLS = {
    "summitflow": "postgresql://summitflow_app@localhost:5432/summitflow",
    "agent-hub": "postgresql://agent_hub_app@localhost:5432/agent_hub",
    "portfolio-ai": "postgresql://portfolio_app@localhost:5432/portfolio_ai",
    "a-term": "postgresql://summitflow_app@localhost:5432/summitflow",
    "hatchet": "postgresql://db_admin@localhost:5432/hatchet?sslmode=disable",
}


def _load_env_file(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    values: dict[str, str] = {}
    for raw_line in path.read_text().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def _project_env_var(project: str) -> str:
    if project == "summitflow":
        return "DATABASE_URL"
    return f"{project.replace('-', '_').upper()}_DB_URL"


def _detect_project(explicit: str | None) -> str:
    if explicit:
        return explicit
    env_project = os.environ.get("ST_PROJECT_ID", "").strip()
    if env_project:
        return env_project
    project = find_project_by_cwd(os.getcwd())
    if project and project.get("id"):
        return str(project["id"])
    return Path.cwd().name


def _db_url(project: str) -> str:
    env_file = _load_env_file(Path.home() / ".env.local")
    candidates = [
        os.environ.get(_project_env_var(project)),
        env_file.get(_project_env_var(project)),
        os.environ.get("DATABASE_URL") if project == "summitflow" else None,
        env_file.get("DATABASE_URL") if project == "summitflow" else None,
        _DEFAULT_DB_URLS.get(project),
    ]
    for candidate in candidates:
        if candidate:
            return candidate
    output_error(f"Unknown project database for {project}; set {_project_env_var(project)}")
    raise typer.Exit(1) from None


def _safe_detail_part(value: str) -> str:
    part = re.sub(r"[^A-Za-z0-9_.-]+", "-", value.strip()).strip("-._")
    return part[:48] or "item"


def _psql_detail_name(project: str, kind: str, *parts: str, sql: str | None = None) -> str:
    name_parts = [f"db-{_safe_detail_part(project)}", _safe_detail_part(kind)]
    name_parts.extend(_safe_detail_part(part) for part in parts if part)
    if sql is not None:
        digest = hashlib.sha1(sql.encode("utf-8")).hexdigest()[:8]
        name_parts.append(digest)
    return "-".join(name_parts)


@contextmanager
def _psql_project_lock(project: str) -> Iterator[None]:
    root = _details_root(project)
    lock_dir = root / ".dev-tools"
    lock_dir.mkdir(parents=True, exist_ok=True)
    lock_path = lock_dir / f"db-{_safe_detail_part(project)}-psql.lock"
    with lock_path.open("w", encoding="utf-8") as lock_file:
        # Local st db probes are short-lived; serializing them avoids exhausting
        # small development PostgreSQL connection pools during parallel agent work.
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def _run_psql(
    project: str,
    sql: str,
    *,
    tuples_only: bool = False,
    detail_name: str | None = None,
) -> int:
    args = ["psql", _db_url(project)]
    if tuples_only:
        args.extend(["-t", "-A"])
    args.extend(["-c", sql])
    env = os.environ.copy()
    env.setdefault("PGAPPNAME", f"st-db-{project}")
    with _psql_project_lock(project):
        result = subprocess.run(
            args,
            env=env,
            text=True,
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
    emit_result_or_details(
        _details_root(project),
        detail_name or _psql_detail_name(project, "psql", sql=sql),
        "DB",
        result,
    )
    return result.returncode


def _strip_literals(sql: str) -> str:
    sql = re.sub(r"'(?:''|[^'])*'", "", sql, flags=re.S)
    sql = re.sub(r"\$([A-Za-z_][A-Za-z_0-9]*)\$.*?\$\1\$", "", sql, flags=re.S)
    return re.sub(r"\$\$.*?\$\$", "", sql, flags=re.S)


def _is_read_query(sql: str) -> bool:
    return not re.search(r"^\s*(INSERT|UPDATE|DELETE|DROP|ALTER|TRUNCATE|CREATE|GRANT|REVOKE)\b", sql, re.I)


def _exec_allowed(sql: str) -> bool:
    return not re.search(r"\b(DROP|TRUNCATE|GRANT|REVOKE|CREATE)\b", _strip_literals(sql), re.I)


def _ddl_allowed(sql: str) -> bool:
    stripped = _strip_literals(sql)
    return bool(re.search(r"^\s*(CREATE\s+INDEX|ALTER\s+TABLE\s+\S+\s+ADD)\b", stripped, re.I))


def _project_root(project: str) -> Path:
    root = get_project_root_path(project)
    if not root:
        output_error(f"Unknown project root for {project}")
        raise typer.Exit(1) from None
    return Path(root)


def _details_root(project: str) -> Path:
    root = get_project_root_path(project)
    return Path(root) if root else Path.cwd()


def _migration_dir(project: str) -> Path:
    root = _project_root(project)
    for candidate in (root / "backend", root):
        if (candidate / "alembic.ini").exists():
            return candidate
    output_error(f"No alembic.ini found for {project}")
    raise typer.Exit(1) from None


def _alembic(project: str, args: list[str]) -> int:
    cwd = _migration_dir(project)
    venv = cwd / ".venv"
    if not (venv / "bin" / "alembic").exists():
        venv = cwd.parent / ".venv"
    alembic = venv / "bin" / "alembic"
    command = [str(alembic) if alembic.exists() else "alembic", *args]
    env = os.environ.copy()
    for key in ("DATABASE_URL", "REDIS_URL", "AGENT_HUB_DB_URL", "AGENT_HUB_REDIS_URL", "PORTFOLIO_DB_URL", "PORTFOLIO_AI_DB_URL", "HATCHET_CLIENT_TOKEN"):
        env.pop(key, None)
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
    emit_result_or_details(cwd, f"db-{project}-alembic", "DB", result)
    return result.returncode


def _parse_project_arg(args: list[str]) -> tuple[str | None, list[str]]:
    project: str | None = None
    remaining: list[str] = []
    index = 0
    while index < len(args):
        arg = args[index]
        if arg in {"-P", "--project"}:
            if index + 1 >= len(args):
                output_error("-P/--project requires a value")
                raise typer.Exit(2) from None
            project = args[index + 1]
            index += 2
            continue
        if arg.startswith("--project="):
            project = arg.split("=", 1)[1]
            index += 1
            continue
        remaining.append(arg)
        index += 1
    if project == "":
        output_error("-P/--project requires a value")
        raise typer.Exit(2) from None
    return project, remaining


def _usage() -> None:
    print(
        """Database CLI - Direct PostgreSQL introspection + Alembic migrations

Usage: st db [OPTIONS] COMMAND [ARGS]

Commands:
  tables [--counts]          List public tables
  schema <table>             Show columns, keys, constraints, indexes
  count <table>              Count rows
  sample <table> [limit]     Sample rows
  sizes                      Show table/index sizes
  indexes [table]            Show indexes
  workbench start|stop|status Start or inspect Pgweb workbench
  query [-t] "SELECT ..."    Run read-only SQL
  exec "UPDATE ..."          Run write SQL with destructive DDL blocked
  ddl "CREATE INDEX ..."     Run safe DDL only
  migrate status|upgrade|downgrade|history|create

Options:
  -P, --project <id>         Target project DB
"""
    )


def _tables_counts_sql() -> str:
    return """
        SELECT table_schema || '.' || table_name AS table_name,
               (
                   xpath(
                       '/row/c/text()',
                       query_to_xml(
                           format('SELECT count(*) AS c FROM %I.%I', table_schema, table_name),
                           false,
                           true,
                           ''
                       )
                   )
               )[1]::text::bigint AS row_count
        FROM information_schema.tables
        WHERE table_schema = 'public'
          AND table_type = 'BASE TABLE'
        ORDER BY table_name;
    """


@app.callback(invoke_without_command=True)
@usage(
    surface="st.db",
    cmd='st db query -t "SELECT ..."',
    when="read DB state; DDL must go through migrations",
    precautions=("never run write SQL outside migrations",),
    task_types=("database", "backend", "verification"),
    tier="mandate",
)
def db(ctx: typer.Context) -> None:
    """Run database inspection or migration commands."""
    if ctx.invoked_subcommand is not None:
        return
    explicit_project, args = _parse_project_arg(list(ctx.args))
    if not args or args[0] in {"-h", "--help", "help"}:
        _usage()
        raise typer.Exit(0)
    project = _detect_project(explicit_project)
    command = args[0]
    rest = args[1:]

    if command == "workbench":
        raise typer.Exit(_workbench(project, rest))
    if command == "tables":
        if rest[:1] == ["--counts"]:
            raise typer.Exit(
                _run_psql(
                    project,
                    _tables_counts_sql(),
                    detail_name=_psql_detail_name(project, "tables-counts"),
                )
            )
        sql = "SELECT tablename FROM pg_tables WHERE schemaname = 'public' ORDER BY tablename;"
        raise typer.Exit(
            _run_psql(project, sql, tuples_only=True, detail_name=_psql_detail_name(project, "tables"))
        )
    if command == "schema" and rest:
        table = rest[0]
        sql = f"""
            SELECT column_name, data_type, CASE WHEN is_nullable = 'YES' THEN 'NULL' ELSE 'NOT NULL' END AS nullable, column_default
            FROM information_schema.columns
            WHERE table_schema = 'public' AND table_name = '{table}'
            ORDER BY ordinal_position;
            SELECT indexname, indexdef FROM pg_indexes WHERE schemaname = 'public' AND tablename = '{table}';
        """
        raise typer.Exit(_run_psql(project, sql, detail_name=_psql_detail_name(project, "schema", table)))
    if command == "count" and rest:
        raise typer.Exit(
            _run_psql(
                project,
                f"SELECT COUNT(*) FROM {rest[0]};",
                tuples_only=True,
                detail_name=_psql_detail_name(project, "count", rest[0]),
            )
        )
    if command == "sample" and rest:
        limit = rest[1] if len(rest) > 1 else "10"
        raise typer.Exit(
            _run_psql(
                project,
                f"SELECT * FROM {rest[0]} LIMIT {limit};",
                detail_name=_psql_detail_name(project, "sample", rest[0]),
            )
        )
    if command == "sizes":
        sql = """
            SELECT relname AS table_name,
                   pg_size_pretty(pg_total_relation_size(relid)) AS total_size,
                   pg_size_pretty(pg_relation_size(relid)) AS table_size
            FROM pg_catalog.pg_statio_user_tables
            ORDER BY pg_total_relation_size(relid) DESC;
        """
        raise typer.Exit(_run_psql(project, sql, detail_name=_psql_detail_name(project, "sizes")))
    if command == "indexes":
        where = f" AND tablename = '{rest[0]}'" if rest else ""
        table_part = rest[0] if rest else "all"
        raise typer.Exit(
            _run_psql(
                project,
                f"SELECT tablename, indexname, indexdef FROM pg_indexes WHERE schemaname = 'public'{where} ORDER BY tablename, indexname;",
                detail_name=_psql_detail_name(project, "indexes", table_part),
            )
        )
    if command == "query":
        plain = rest[:1] in (["-t"], ["--plain"])
        sql = rest[1] if plain and len(rest) > 1 else (rest[0] if rest else "")
        if not sql:
            output_error("Query required")
            raise typer.Exit(2)
        if not _is_read_query(sql):
            output_error("Write operations blocked. Use st db exec or migrations.")
            raise typer.Exit(1)
        raise typer.Exit(
            _run_psql(
                project,
                sql,
                tuples_only=plain,
                detail_name=_psql_detail_name(project, "query", sql=sql),
            )
        )
    if command == "exec" and rest:
        sql = rest[0]
        if not _exec_allowed(sql):
            output_error("Destructive DDL blocked by st db exec. Use migrations.")
            raise typer.Exit(1)
        raise typer.Exit(
            _run_psql(project, sql, detail_name=_psql_detail_name(project, "exec", sql=sql))
        )
    if command == "ddl" and rest:
        sql = rest[0]
        if not _ddl_allowed(sql):
            output_error("DDL blocked. Allowed: CREATE INDEX, ALTER TABLE <table> ADD ...")
            raise typer.Exit(1)
        raise typer.Exit(_run_psql(project, sql, detail_name=_psql_detail_name(project, "ddl", sql=sql)))
    if command == "migrate" and rest:
        sub = rest[0]
        if sub == "status":
            raise typer.Exit(_alembic(project, ["current", "-v"]))
        if sub == "upgrade":
            raise typer.Exit(_alembic(project, ["upgrade", rest[1] if len(rest) > 1 else "head"]))
        if sub == "downgrade":
            raise typer.Exit(_alembic(project, ["downgrade", rest[1] if len(rest) > 1 else "-1"]))
        if sub == "history":
            raise typer.Exit(_alembic(project, ["history", "-r", f"-{rest[1] if len(rest) > 1 else '10'}:current"]))
        if sub == "create" and len(rest) > 1:
            raise typer.Exit(_alembic(project, ["revision", "--autogenerate", "-m", rest[1]]))
    output_error(f"Unknown or incomplete st db command: {' '.join(args)}")
    raise typer.Exit(2)


def _print_workbench_status(project: str, *, message: str | None = None) -> None:
    status = status_workbench(project, message=message)
    state = "running" if status.running else "stopped"
    install = "installed" if status.installed else "missing-pgweb"
    url = status.proxy_url if status.running else "-"
    pid = status.pid if status.pid is not None else "-"
    mode = "readonly" if status.readonly else "admin"
    print(f"WORKBENCH {project} {state} {install} {mode} pid={pid} url={url}")
    if status.message:
        print(status.message)


def _workbench(project: str, args: list[str]) -> int:
    if not args or args[0] in {"-h", "--help", "help"}:
        print(
            """Usage: st db [-P project] workbench start|stop|status [--admin]

Starts Pgweb bound to localhost and proxies it through SummitFlow.
"""
        )
        return 0
    subcommand = args[0]
    try:
        if subcommand == "start":
            start_workbench(project, readonly="--admin" not in args[1:])
            _print_workbench_status(project)
            return 0
        if subcommand == "stop":
            stop_workbench(project)
            _print_workbench_status(project)
            return 0
        if subcommand == "status":
            _print_workbench_status(project)
            return 0
    except DbWorkbenchError as exc:
        output_error(str(exc))
        return 1
    output_error(f"Unknown st db workbench command: {subcommand}")
    return 2
