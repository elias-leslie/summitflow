"""Storage layer for explorer symbol records."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import Any

from psycopg import sql

from app.services.explorer.redundancy import (
    DEFAULT_CONFIG,
    DuplicateCluster,
    SimilarityConfig,
    cluster_duplicates,
    is_eligible,
    tokenize_name,
)

from ._sql import join_static_sql
from .connection import get_connection, get_cursor
from .explorer_helpers import row_to_entry, to_iso_string


def _row_to_symbol(row: tuple[Any, ...]) -> dict[str, Any]:
    """Convert a database row to an explorer symbol dict."""
    return {
        "id": row[0],
        "project_id": row[1],
        "file_path": row[2],
        "symbol_id": row[3],
        "qualified_name": row[4],
        "name": row[5],
        "kind": row[6],
        "signature": row[7],
        "language": row[8],
        "start_line": row[9],
        "end_line": row[10],
        "byte_offset": row[11],
        "byte_length": row[12],
        "content_hash": row[13],
        "summary": row[14],
        "keywords": row[15] or [],
        "created_at": to_iso_string(row[16]),
        "updated_at": to_iso_string(row[17]),
    }


def replace_file_symbols(
    project_id: str,
    file_path: str,
    symbols: Sequence[Mapping[str, Any]],
) -> int:
    """Replace all symbols for a file with a fresh snapshot."""
    now = datetime.now(UTC)

    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            "DELETE FROM explorer_symbols WHERE project_id = %s AND file_path = %s",
            (project_id, file_path),
        )
        if not symbols:
            conn.commit()
            return 0

        cur.executemany(
            """
            INSERT INTO explorer_symbols (
                project_id, file_path, symbol_id, qualified_name, name, kind,
                signature, language, start_line, end_line, byte_offset, byte_length,
                content_hash, summary, keywords, created_at, updated_at
            )
            VALUES (
                %s, %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s
            )
            """,
            [
                (
                    project_id,
                    file_path,
                    symbol["symbol_id"],
                    symbol["qualified_name"],
                    symbol["name"],
                    symbol["kind"],
                    symbol["signature"],
                    symbol["language"],
                    symbol["start_line"],
                    symbol["end_line"],
                    symbol["byte_offset"],
                    symbol["byte_length"],
                    symbol["content_hash"],
                    symbol.get("summary"),
                    symbol.get("keywords", []),
                    now,
                    now,
                )
                for symbol in symbols
            ],
        )
        conn.commit()
        return len(symbols)


def list_symbols_for_file(project_id: str, file_path: str) -> list[dict[str, Any]]:
    """List symbols for a file ordered by source position."""
    with get_cursor() as cur:
        cur.execute(
            """
            SELECT id, project_id, file_path, symbol_id, qualified_name, name, kind,
                   signature, language, start_line, end_line, byte_offset, byte_length,
                   content_hash, summary, keywords, created_at, updated_at
            FROM explorer_symbols
            WHERE project_id = %s AND file_path = %s
            ORDER BY start_line, end_line, name
            """,
            (project_id, file_path),
        )
        return [_row_to_symbol(row) for row in cur.fetchall()]


def get_symbol(project_id: str, symbol_id: str) -> dict[str, Any] | None:
    """Fetch one symbol by project and stable symbol id."""
    with get_cursor() as cur:
        cur.execute(
            """
            SELECT id, project_id, file_path, symbol_id, qualified_name, name, kind,
                   signature, language, start_line, end_line, byte_offset, byte_length,
                   content_hash, summary, keywords, created_at, updated_at
            FROM explorer_symbols
            WHERE project_id = %s AND symbol_id = %s
            """,
            (project_id, symbol_id),
        )
        row = cur.fetchone()
        return _row_to_symbol(row) if row else None


def get_symbol_stats(project_id: str) -> dict[str, Any]:
    """Return aggregate symbol index stats for a project."""
    with get_cursor() as cur:
        cur.execute(
            """
            SELECT COUNT(*), MAX(updated_at)
            FROM explorer_symbols
            WHERE project_id = %s
            """,
            (project_id,),
        )
        row = cur.fetchone()
    count = row[0] if row else 0
    last_updated = to_iso_string(row[1]) if row else None
    return {
        "count": count,
        "last_updated": last_updated,
    }


def list_related_entries_for_file(project_id: str, file_path: str) -> list[dict[str, Any]]:
    """List page and endpoint entries whose source file matches the symbol file."""
    with get_cursor() as cur:
        cur.execute(
            """
            SELECT id, project_id, entry_type, path, name, health_status,
                   metadata, last_scanned_at, created_at, updated_at
            FROM explorer_entries
            WHERE project_id = %s
              AND entry_type = ANY(%s)
              AND metadata->>'source_file' = %s
            ORDER BY entry_type ASC, path ASC
            """,
            (project_id, ["endpoint", "page"], file_path),
        )
        rows = cur.fetchall()

    return [row_to_entry(row) for row in rows]


def summarize_symbols_for_file(project_id: str, file_path: str, *, limit: int = 5) -> list[dict[str, Any]]:
    """Return a concise top-symbol summary for a file."""
    capped = max(1, limit)
    with get_cursor() as cur:
        cur.execute(
            """
            SELECT symbol_id, name, kind, qualified_name, start_line, end_line
            FROM explorer_symbols
            WHERE project_id = %s AND file_path = %s
            ORDER BY start_line, end_line, name
            LIMIT %s
            """,
            (project_id, file_path, capped),
        )
        return [
            {
                "symbol_id": row[0],
                "name": row[1],
                "kind": row[2],
                "qualified_name": row[3],
                "start_line": row[4],
                "end_line": row[5],
            }
            for row in cur.fetchall()
        ]


def search_symbols(
    project_id: str,
    query: str,
    *,
    language: str | None = None,
    kind: str | None = None,
    limit: int = 20,
    path_prefix: str | None = None,
) -> list[dict[str, Any]]:
    """Search symbols by name, qualified name, signature, summary, or keywords."""
    if not query.strip():
        return []

    limit = max(1, min(limit, 100))
    query_value = query.strip()
    exact = query_value.lower()
    fuzzy = f"%{query_value}%"
    normalized_prefix = str(path_prefix or "").strip().replace("\\", "/")
    if normalized_prefix.startswith("./"):
        normalized_prefix = normalized_prefix[2:]
    normalized_prefix = normalized_prefix.strip("/")

    conditions = ["project_id = %s"]
    params: list[Any] = [project_id]
    if language:
        conditions.append("language = %s")
        params.append(language)
    if kind:
        conditions.append("kind = %s")
        params.append(kind)
    if normalized_prefix:
        conditions.append("(file_path = %s OR file_path LIKE %s)")
        params.extend([normalized_prefix, f"{normalized_prefix}/%"])

    conditions.append(
        "("
        "LOWER(name) = %s OR "
        "LOWER(symbol_id) = %s OR "
        "LOWER(name) LIKE LOWER(%s) OR "
        "LOWER(qualified_name) LIKE LOWER(%s) OR "
        "LOWER(file_path) LIKE LOWER(%s) OR "
        "LOWER(signature) LIKE LOWER(%s) OR "
        "LOWER(COALESCE(summary, '')) LIKE LOWER(%s) OR "
        "ARRAY_TO_STRING(keywords, ' ') ILIKE %s"
        ")"
    )
    params.extend([exact, exact, fuzzy, fuzzy, fuzzy, fuzzy, fuzzy, fuzzy])

    query_sql = sql.SQL(
        """
        SELECT id, project_id, file_path, symbol_id, qualified_name, name, kind,
               signature, language, start_line, end_line, byte_offset, byte_length,
               content_hash, summary, keywords, created_at, updated_at,
               CASE
                   WHEN LOWER(name) = %s THEN 100
                   WHEN LOWER(symbol_id) = %s THEN 95
                   WHEN LOWER(name) LIKE LOWER(%s) THEN 80
                   WHEN LOWER(qualified_name) LIKE LOWER(%s) THEN 70
                   WHEN LOWER(file_path) LIKE LOWER(%s) THEN 60
                   WHEN LOWER(COALESCE(summary, '')) LIKE LOWER(%s) THEN 50
                   WHEN LOWER(signature) LIKE LOWER(%s) THEN 40
                   WHEN ARRAY_TO_STRING(keywords, ' ') ILIKE %s THEN 30
                   ELSE 0
               END AS score
        FROM explorer_symbols
        WHERE {where_clause}
        ORDER BY score DESC, name ASC, start_line ASC
        LIMIT %s
        """
    ).format(where_clause=join_static_sql(conditions, " AND "))

    ranking_params = [exact, exact, fuzzy, fuzzy, fuzzy, fuzzy, fuzzy, fuzzy]

    with get_cursor() as cur:
        cur.execute(query_sql, (*ranking_params, *params, limit))
        rows = cur.fetchall()
        return [_row_to_symbol(row[:-1]) for row in rows]


def _load_symbols_for_detection(project_id: str) -> list[dict[str, Any]]:
    """Load the symbol fields the redundancy detector scores, for one project."""
    with get_cursor() as cur:
        cur.execute(
            """
            SELECT file_path, symbol_id, qualified_name, name, kind,
                   signature, language, summary, keywords
            FROM explorer_symbols
            WHERE project_id = %s
            """,
            (project_id,),
        )
        rows = cur.fetchall()
    return [
        {
            "file_path": r[0],
            "symbol_id": r[1],
            "qualified_name": r[2],
            "name": r[3],
            "kind": r[4],
            "signature": r[5],
            "language": r[6],
            "summary": r[7],
            "keywords": r[8] or [],
        }
        for r in rows
    ]


def find_redundancy_candidates(
    project_id: str,
    *,
    max_cluster_size: int = 3,
    config: SimilarityConfig = DEFAULT_CONFIG,
) -> list[DuplicateCluster]:
    """Find near-duplicate symbol clusters for a project (precision-first).

    Narrows to eligible symbols that share a name token with at least one other
    (an inverted-index stand-in for per-symbol ``search_symbols`` that avoids the
    detector's O(n^2) full pairwise scan), then runs the pure clusterer. Clusters
    outside the 2..``max_cluster_size`` range are dropped: large N-way name
    collisions are dominated by framework conventions, not actionable copies.
    """
    symbols = _load_symbols_for_detection(project_id)
    eligible = [i for i, s in enumerate(symbols) if is_eligible(s, config)]

    token_index: dict[str, list[int]] = defaultdict(list)
    for i in eligible:
        for tok in tokenize_name(str(symbols[i].get("name") or "")):
            token_index[tok].append(i)

    candidate_idx: set[int] = set()
    for members in token_index.values():
        if len(members) > 1:
            candidate_idx.update(members)
    candidates = [symbols[i] for i in sorted(candidate_idx)]

    return [
        cluster
        for cluster in cluster_duplicates(candidates, config)
        if 2 <= len(cluster.members) <= max_cluster_size
    ]


def cleanup_stale_symbols(project_id: str, current_paths: set[str]) -> int:
    """Delete symbol rows for files missing from the current file scan snapshot."""
    with get_connection() as conn, conn.cursor() as cur:
        if current_paths:
            cur.execute(
                """
                DELETE FROM explorer_symbols
                WHERE project_id = %s
                  AND file_path <> ALL(%s)
                """,
                (project_id, sorted(current_paths)),
            )
        else:
            cur.execute("DELETE FROM explorer_symbols WHERE project_id = %s", (project_id,))
        deleted = cur.rowcount or 0
        conn.commit()
        return deleted
