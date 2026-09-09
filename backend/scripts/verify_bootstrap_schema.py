"""Exercise fresh snapshot restore and data-preserving upgrades in an empty test DB.

CI supplies its disposable PostgreSQL service through DATABASE_URL. This script
never creates, drops, or resets a database and refuses nonempty input databases.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import LiteralString, cast
from urllib.parse import urlsplit
from uuid import uuid4

import psycopg
from alembic.config import Config
from alembic.script import ScriptDirectory

from alembic import command

BACKEND = Path(__file__).resolve().parents[1]
SNAPSHOT = BACKEND.parent / "docker" / "compose" / "summitflow-schema.sql"
DESIGN_REVISION = "a24e1b127505"


def main() -> None:
    database_url = os.environ.get("DATABASE_URL", "")
    if urlsplit(database_url).path != "/summitflow_test":
        raise SystemExit("Bootstrap verification requires explicit DATABASE_URL for summitflow_test")
    config = Config(str(BACKEND / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND / "alembic"))
    revisions = ScriptDirectory.from_config(config)
    with psycopg.connect(database_url) as connection:
        tables = connection.execute("SELECT count(*) FROM pg_tables WHERE schemaname = 'public'").fetchone()
        if tables != (0,):
            raise SystemExit("Bootstrap verification requires an empty test database; existing data was not changed")
        # pg_dump's psql safety markers are not SQL; all other snapshot text is executed intact.
        sql = "\n".join(
            line for line in SNAPSHOT.read_text().splitlines()
            if not line.startswith(("\\restrict ", "\\unrestrict "))
        )
        connection.execute(cast(LiteralString, sql))
        assert connection.execute("SELECT version_num FROM public.alembic_version").fetchone() == (revisions.get_base(),)

    command.upgrade(config, "a14ee32465a1")
    with psycopg.connect(database_url) as connection:
        # Observe a historical add/drop transition, rather than guessing a later stamp.
        assert connection.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = 'notifications' AND column_name = 'idea_id'"
        ).fetchone() == ("idea_id",)
    command.upgrade(config, DESIGN_REVISION)
    project_id = "bootstrap-regression-" + uuid4().hex
    with psycopg.connect(database_url) as connection:
        assert connection.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = 'notifications' AND column_name = 'idea_id'"
        ).fetchone() is None
        connection.execute(
            "INSERT INTO projects (id, name, base_url) VALUES (%s, %s, %s)",
            (project_id, "Bootstrap regression", "https://bootstrap.invalid"),
        )
        connection.execute(
            "INSERT INTO design_assets (project_id, asset_id, name, asset_type, prompt, width, height) "
            "VALUES (%s, 'upgrade-fixture', 'Retained asset', 'icon', 'Fixture prompt', 16, 16)",
            (project_id,),
        )

    command.upgrade(config, "head")
    command.upgrade(config, "head")
    with psycopg.connect(database_url) as connection:
        assert connection.execute("SELECT version_num FROM alembic_version").fetchone() == (revisions.get_current_head(),)
        assert connection.execute(
            "SELECT name FROM design_assets WHERE project_id = %s AND asset_id = 'upgrade-fixture'",
            (project_id,),
        ).fetchone() == ("Retained asset",)
        assert connection.execute("SELECT to_regclass('public.notes') IS NOT NULL").fetchone() == (True,)
        assert connection.execute("SELECT to_regclass('public.runtime_metric_samples') IS NOT NULL").fetchone() == (True,)
        assert connection.execute("SELECT to_regclass('public.celery_taskmeta')").fetchone() == (None,)
        assert connection.execute("SELECT to_regclass('public.celery_tasksetmeta')").fetchone() == (None,)
        connection.execute("DELETE FROM projects WHERE id = %s", (project_id,))
    print("Bootstrap verification passed: fresh restore, full migration chain, retained upgrade data, repeat upgrade")


if __name__ == "__main__":
    main()
