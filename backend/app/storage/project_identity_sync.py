"""Reconcile registered project rows with repo-local identity manifests."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from psycopg import Cursor, sql

from ..project_identity import (
    get_project_aliases,
    get_project_canonical_id,
    get_project_display_name,
    get_project_identity,
    get_project_identity_root,
)
from .connection import get_connection

_PROJECT_ROW_SQL = """
    SELECT id, name, base_url, public_url, health_endpoint, root_path, category, sidebar_rank, created_at
    FROM projects
    WHERE id = ANY(%s)
"""

_BACKUP_SOURCE_ROW_SQL = """
    SELECT id, name, path, source_type, project_id, enabled, frequency, retention_days,
           last_run_at, next_run_at, storage_backend_id, last_restore_tested_at,
           last_restore_test_ok, last_restore_test_error, last_drill_at, last_drill_ok,
           last_drill_backup_id, last_drill_result
    FROM backup_sources
    WHERE id = ANY(%s) OR project_id = ANY(%s)
"""


@dataclass(frozen=True)
class ProjectIdentityMetadata:
    canonical_id: str
    display_name: str
    root_path: str
    aliases: tuple[str, ...]


def _build_metadata(project_id: str) -> ProjectIdentityMetadata:
    identity = get_project_identity(project_id)
    if identity is None:
        raise ValueError(f"Project identity manifest not found for {project_id}")

    canonical_id = get_project_canonical_id(project_id, fallback=project_id)
    root_path = get_project_identity_root(project_id)
    if canonical_id is None or root_path is None:
        raise ValueError(f"Project identity manifest is incomplete for {project_id}")

    display_name = get_project_display_name(project_id, fallback=canonical_id)
    if display_name is None:
        raise ValueError(f"Project display name missing for {project_id}")

    aliases = get_project_aliases(project_id)
    return ProjectIdentityMetadata(
        canonical_id=canonical_id,
        display_name=display_name,
        root_path=root_path,
        aliases=aliases,
    )


def _discover_foreign_key_targets(
    cur: Cursor[Any],
    *,
    foreign_table: str,
    foreign_column: str = "id",
) -> list[tuple[str, str]]:
    cur.execute(
        """
        SELECT kcu.table_name, kcu.column_name
        FROM information_schema.table_constraints tc
        JOIN information_schema.key_column_usage kcu
          ON tc.constraint_name = kcu.constraint_name
         AND tc.table_schema = kcu.table_schema
        JOIN information_schema.constraint_column_usage ccu
          ON ccu.constraint_name = tc.constraint_name
         AND ccu.table_schema = tc.table_schema
        WHERE tc.constraint_type = 'FOREIGN KEY'
          AND tc.table_schema = 'public'
          AND ccu.table_name = %s
          AND ccu.column_name = %s
        ORDER BY kcu.table_name, kcu.column_name
        """,
        (foreign_table, foreign_column),
    )
    return [(row[0], row[1]) for row in cur.fetchall()]


def _update_foreign_key_rows(
    cur: Cursor[Any],
    *,
    targets: list[tuple[str, str]],
    old_value: str,
    new_value: str,
) -> None:
    if old_value == new_value:
        return

    for table_name, column_name in targets:
        cur.execute(
            sql.SQL("UPDATE {} SET {} = %s WHERE {} = %s").format(
                sql.Identifier(table_name),
                sql.Identifier(column_name),
                sql.Identifier(column_name),
            ),
            (new_value, old_value),
        )


def _choose_project_row(
    rows: list[tuple[Any, ...]],
    *,
    requested_id: str,
    canonical_id: str,
) -> tuple[Any, ...]:
    row_by_id = {str(row[0]): row for row in rows}
    return row_by_id.get(canonical_id) or row_by_id.get(requested_id) or rows[0]


def _choose_backup_source_row(
    rows: list[tuple[Any, ...]],
    *,
    requested_id: str,
    canonical_id: str,
) -> tuple[Any, ...] | None:
    if not rows:
        return None

    project_rows = [row for row in rows if str(row[3]) == "project"]
    candidates = project_rows or rows
    row_by_id = {str(row[0]): row for row in candidates}
    return row_by_id.get(canonical_id) or row_by_id.get(requested_id) or candidates[0]


def sync_project_identity(project_id: str) -> dict[str, Any]:
    """Reconcile DB project metadata and references to the manifest canonical identity."""
    meta = _build_metadata(project_id)

    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(_PROJECT_ROW_SQL, (list(meta.aliases),))
        project_rows = list(cur.fetchall())
        if not project_rows:
            raise ValueError(
                f"Project {project_id} is not registered in SummitFlow; create it before syncing identity"
            )

        canonical_row = next((row for row in project_rows if str(row[0]) == meta.canonical_id), None)
        source_project = _choose_project_row(
            project_rows,
            requested_id=project_id,
            canonical_id=meta.canonical_id,
        )

        if canonical_row is None:
            cur.execute(
                """
                INSERT INTO projects (
                    id, name, base_url, public_url, health_endpoint, root_path,
                    category, sidebar_rank, created_at
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    meta.canonical_id,
                    meta.display_name,
                    source_project[2],
                    source_project[3],
                    source_project[4],
                    meta.root_path,
                    source_project[6],
                    source_project[7],
                    source_project[8],
                ),
            )
        else:
            cur.execute(
                "UPDATE projects SET name = %s, root_path = %s WHERE id = %s",
                (meta.display_name, meta.root_path, meta.canonical_id),
            )

        project_fk_targets = _discover_foreign_key_targets(cur, foreign_table="projects")
        for legacy_id in meta.aliases:
            if legacy_id != meta.canonical_id:
                _update_foreign_key_rows(
                    cur,
                    targets=project_fk_targets,
                    old_value=legacy_id,
                    new_value=meta.canonical_id,
                )

        cur.execute(_BACKUP_SOURCE_ROW_SQL, (list(meta.aliases), list(meta.aliases)))
        backup_rows = list(cur.fetchall())
        source_backup = _choose_backup_source_row(
            backup_rows,
            requested_id=project_id,
            canonical_id=meta.canonical_id,
        )
        if source_backup is not None:
            cur.execute(
                """
                INSERT INTO backup_sources (
                    id, name, path, source_type, project_id, enabled, frequency,
                    retention_days, last_run_at, next_run_at, storage_backend_id,
                    last_restore_tested_at, last_restore_test_ok, last_restore_test_error,
                    last_drill_at, last_drill_ok, last_drill_backup_id, last_drill_result
                )
                VALUES (
                    %s, %s, %s, 'project', %s, %s, %s, %s, %s, %s, %s,
                    %s, %s, %s, %s, %s, %s, %s
                )
                ON CONFLICT (id) DO UPDATE
                SET name = EXCLUDED.name,
                    path = EXCLUDED.path,
                    source_type = EXCLUDED.source_type,
                    project_id = EXCLUDED.project_id,
                    enabled = EXCLUDED.enabled,
                    frequency = EXCLUDED.frequency,
                    retention_days = EXCLUDED.retention_days,
                    last_run_at = EXCLUDED.last_run_at,
                    next_run_at = EXCLUDED.next_run_at,
                    storage_backend_id = EXCLUDED.storage_backend_id,
                    last_restore_tested_at = EXCLUDED.last_restore_tested_at,
                    last_restore_test_ok = EXCLUDED.last_restore_test_ok,
                    last_restore_test_error = EXCLUDED.last_restore_test_error,
                    last_drill_at = EXCLUDED.last_drill_at,
                    last_drill_ok = EXCLUDED.last_drill_ok,
                    last_drill_backup_id = EXCLUDED.last_drill_backup_id,
                    last_drill_result = EXCLUDED.last_drill_result,
                    updated_at = NOW()
                """,
                (
                    meta.canonical_id,
                    meta.display_name,
                    meta.root_path,
                    meta.canonical_id,
                    source_backup[5],
                    source_backup[6],
                    source_backup[7],
                    source_backup[8],
                    source_backup[9],
                    source_backup[10],
                    source_backup[11],
                    source_backup[12],
                    source_backup[13],
                    source_backup[14],
                    source_backup[15],
                    source_backup[16],
                    source_backup[17],
                ),
            )

            backup_fk_targets = _discover_foreign_key_targets(cur, foreign_table="backup_sources")
            for legacy_id in meta.aliases:
                if legacy_id != meta.canonical_id:
                    _update_foreign_key_rows(
                        cur,
                        targets=backup_fk_targets,
                        old_value=legacy_id,
                        new_value=meta.canonical_id,
                    )

        for legacy_id in meta.aliases:
            if legacy_id == meta.canonical_id:
                continue
            cur.execute(
                "DELETE FROM backup_sources WHERE id = %s AND source_type = 'project'",
                (legacy_id,),
            )
            cur.execute("DELETE FROM projects WHERE id = %s", (legacy_id,))

        conn.commit()

        cur.execute(
            """
            SELECT id, name, base_url, public_url, health_endpoint, root_path, category, sidebar_rank, created_at
            FROM projects
            WHERE id = %s
            """,
            (meta.canonical_id,),
        )
        row = cur.fetchone()
        if row is None:
            raise ValueError(f"Project identity sync failed for {meta.canonical_id}")

    return {
        "id": row[0],
        "name": row[1],
        "base_url": row[2],
        "public_url": row[3],
        "health_endpoint": row[4],
        "root_path": row[5],
        "category": row[6],
        "sidebar_rank": row[7],
        "created_at": row[8],
        "aliases": meta.aliases,
    }
