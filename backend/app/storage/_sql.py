"""Helpers for type-safe SQL composition in storage modules."""

from __future__ import annotations

from collections.abc import Iterable
from typing import LiteralString, cast

from psycopg import sql


def static_sql(fragment: str) -> sql.SQL:
    """Mark a storage-owned SQL fragment as static for psycopg typing."""
    return sql.SQL(cast(LiteralString, fragment))


def join_static_sql(
    fragments: Iterable[str],
    separator: LiteralString = ", ",
) -> sql.Composed:
    """Join storage-owned SQL fragments using a literal separator."""
    return sql.SQL(separator).join(static_sql(fragment) for fragment in fragments)
