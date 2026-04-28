"""Canonical database command surface."""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

import typer

from app.storage.projects import find_project_by_cwd, get_project_root_path

from ..details import emit_result_or_details
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


def _run_psql(project: str, sql: str, *, tuples_only: bool = False) -> int:
    args = ["psql", _db_url(project)]
    if tuples_only:
        args.extend(["-t", "-A"])
    args.extend(["-c", sql])
    result = subprocess.run(
        args,
        text=True,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    emit_result_or_details(_details_root(project), f"db-{project}-psql", "DB", result)
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
    if args[:1] in (["-P"], ["--project"]):
        if len(args) < 2:
            output_error("-P/--project requires a value")
            raise typer.Exit(2) from None
        return args[1], args[2:]
    return None, args


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
  query [-t] "SELECT ..."    Run read-only SQL
  exec "UPDATE ..."          Run write SQL with destructive DDL blocked
  ddl "CREATE INDEX ..."     Run safe DDL only
  migrate status|upgrade|downgrade|history|create

Options:
  -P, --project <id>         Target project DB
"""
    )


@app.callback(invoke_without_command=True)
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

    if command == "tables":
        if rest[:1] == ["--counts"]:
            sql = """
                SELECT schemaname || '.' || relname AS table_name, n_live_tup AS row_count
                FROM pg_stat_user_tables
                WHERE schemaname = 'public'
                ORDER BY relname;
            """
            raise typer.Exit(_run_psql(project, sql))
        sql = "SELECT tablename FROM pg_tables WHERE schemaname = 'public' ORDER BY tablename;"
        raise typer.Exit(_run_psql(project, sql, tuples_only=True))
    if command == "schema" and rest:
        table = rest[0]
        sql = f"""
            SELECT column_name, data_type, CASE WHEN is_nullable = 'YES' THEN 'NULL' ELSE 'NOT NULL' END AS nullable, column_default
            FROM information_schema.columns
            WHERE table_schema = 'public' AND table_name = '{table}'
            ORDER BY ordinal_position;
            SELECT indexname, indexdef FROM pg_indexes WHERE schemaname = 'public' AND tablename = '{table}';
        """
        raise typer.Exit(_run_psql(project, sql))
    if command == "count" and rest:
        raise typer.Exit(_run_psql(project, f"SELECT COUNT(*) FROM {rest[0]};", tuples_only=True))
    if command == "sample" and rest:
        limit = rest[1] if len(rest) > 1 else "10"
        raise typer.Exit(_run_psql(project, f"SELECT * FROM {rest[0]} LIMIT {limit};"))
    if command == "sizes":
        sql = """
            SELECT relname AS table_name,
                   pg_size_pretty(pg_total_relation_size(relid)) AS total_size,
                   pg_size_pretty(pg_relation_size(relid)) AS table_size
            FROM pg_catalog.pg_statio_user_tables
            ORDER BY pg_total_relation_size(relid) DESC;
        """
        raise typer.Exit(_run_psql(project, sql))
    if command == "indexes":
        where = f" AND tablename = '{rest[0]}'" if rest else ""
        raise typer.Exit(_run_psql(project, f"SELECT tablename, indexname, indexdef FROM pg_indexes WHERE schemaname = 'public'{where} ORDER BY tablename, indexname;"))
    if command == "query":
        plain = rest[:1] in (["-t"], ["--plain"])
        sql = rest[1] if plain and len(rest) > 1 else (rest[0] if rest else "")
        if not sql:
            output_error("Query required")
            raise typer.Exit(2)
        if not _is_read_query(sql):
            output_error("Write operations blocked. Use st db exec or migrations.")
            raise typer.Exit(1)
        raise typer.Exit(_run_psql(project, sql, tuples_only=plain))
    if command == "exec" and rest:
        sql = rest[0]
        if not _exec_allowed(sql):
            output_error("Destructive DDL blocked by st db exec. Use migrations.")
            raise typer.Exit(1)
        raise typer.Exit(_run_psql(project, sql))
    if command == "ddl" and rest:
        sql = rest[0]
        if not _ddl_allowed(sql):
            output_error("DDL blocked. Allowed: CREATE INDEX, ALTER TABLE <table> ADD ...")
            raise typer.Exit(1)
        raise typer.Exit(_run_psql(project, sql))
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
