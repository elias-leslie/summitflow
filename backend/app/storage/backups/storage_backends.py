"""CRUD operations for storage backends."""

from __future__ import annotations

from typing import Any

from .._sql import static_sql
from ..connection import generate_prefixed_id, get_connection, get_cursor

BACKEND_COLUMNS = """id, name, backend_type, config, is_default, enabled,
       last_test_at, last_test_ok, created_at, updated_at"""

EXPECTED_BACKEND_COLUMNS = 10


def row_to_backend(row: tuple[Any, ...]) -> dict[str, Any]:
    """Convert database row to storage backend dict."""
    if len(row) != EXPECTED_BACKEND_COLUMNS:
        raise ValueError(f"Expected {EXPECTED_BACKEND_COLUMNS} columns, got {len(row)}")
    return {
        "id": row[0],
        "name": row[1],
        "backend_type": row[2],
        "config": row[3] if isinstance(row[3], dict) else {},
        "is_default": row[4],
        "enabled": row[5],
        "last_test_at": row[6].isoformat() if row[6] else None,
        "last_test_ok": row[7],
        "created_at": row[8].isoformat() if row[8] else None,
        "updated_at": row[9].isoformat() if row[9] else None,
    }


def list_backends(enabled_only: bool = False) -> list[dict[str, Any]]:
    """List all storage backends."""
    where = "WHERE enabled = TRUE" if enabled_only else ""
    with get_cursor() as cur:
        cur.execute(
            static_sql(
                f"SELECT {BACKEND_COLUMNS} FROM storage_backends {where} ORDER BY is_default DESC, name"
            ),
        )
        rows = cur.fetchall()
    return [row_to_backend(row) for row in rows]


def get_backend(backend_id: str) -> dict[str, Any] | None:
    """Get a single storage backend by ID."""
    with get_cursor() as cur:
        cur.execute(
            static_sql(f"SELECT {BACKEND_COLUMNS} FROM storage_backends WHERE id = %s"),
            (backend_id,),
        )
        row = cur.fetchone()
    return row_to_backend(row) if row else None


def get_default_backend() -> dict[str, Any] | None:
    """Get the default storage backend."""
    with get_cursor() as cur:
        cur.execute(
            static_sql(
                f"SELECT {BACKEND_COLUMNS} FROM storage_backends WHERE is_default = TRUE AND enabled = TRUE LIMIT 1"
            ),
        )
        row = cur.fetchone()
    return row_to_backend(row) if row else None


def create_backend(
    name: str,
    backend_type: str = "smb",
    config: dict[str, Any] | None = None,
    is_default: bool = False,
) -> dict[str, Any]:
    """Create a new storage backend."""
    import json

    backend_id = generate_prefixed_id("stb")

    with get_connection() as conn, conn.cursor() as cur:
        # If this is the default, unset any existing defaults
        if is_default:
            cur.execute("UPDATE storage_backends SET is_default = FALSE WHERE is_default = TRUE")

        cur.execute(
            static_sql(
                f"""
                INSERT INTO storage_backends (id, name, backend_type, config, is_default)
                VALUES (%s, %s, %s, %s, %s)
                RETURNING {BACKEND_COLUMNS}
                """
            ),
            (backend_id, name, backend_type, json.dumps(config or {}), is_default),
        )
        row = cur.fetchone()
        conn.commit()

    if not row:
        raise RuntimeError("Failed to create storage backend")
    return row_to_backend(row)


def update_backend(backend_id: str, **fields: Any) -> dict[str, Any] | None:
    """Update a storage backend. Accepts: name, config, is_default, enabled."""
    import json

    allowed = {"name", "config", "is_default", "enabled"}
    updates = []
    params: list[Any] = []

    unknown = fields.keys() - allowed
    if unknown:
        raise ValueError(f"Unknown fields: {', '.join(sorted(unknown))}")

    for key, value in fields.items():
        if key == "config":
            updates.append("config = %s")
            params.append(json.dumps(value) if isinstance(value, dict) else value)
        else:
            updates.append(f"{key} = %s")
            params.append(value)

    if not updates:
        return get_backend(backend_id)

    updates.append("updated_at = NOW()")
    params.append(backend_id)

    with get_connection() as conn, conn.cursor() as cur:
        # If setting as default, unset existing defaults first
        if fields.get("is_default"):
            cur.execute("UPDATE storage_backends SET is_default = FALSE WHERE is_default = TRUE")

        cur.execute(
            static_sql(
                f"UPDATE storage_backends SET {', '.join(updates)} WHERE id = %s RETURNING {BACKEND_COLUMNS}"
            ),
            params,
        )
        row = cur.fetchone()
        conn.commit()

    return row_to_backend(row) if row else None


def delete_backend(backend_id: str) -> bool:
    """Delete a storage backend."""
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM storage_backends WHERE id = %s RETURNING id", (backend_id,))
        row = cur.fetchone()
        conn.commit()
    return row is not None


def update_test_result(backend_id: str, success: bool) -> dict[str, Any] | None:
    """Update last test result for a storage backend."""
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            static_sql(
                f"""
                UPDATE storage_backends
                SET last_test_at = NOW(), last_test_ok = %s, updated_at = NOW()
                WHERE id = %s
                RETURNING {BACKEND_COLUMNS}
                """
            ),
            (success, backend_id),
        )
        row = cur.fetchone()
        conn.commit()
    return row_to_backend(row) if row else None
