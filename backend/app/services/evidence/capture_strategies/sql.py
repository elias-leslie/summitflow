"""SQL capture strategy for database table entries."""

from __future__ import annotations

import logging
import os
import time
from typing import Any

from .base import CaptureConfig, CaptureStrategy, EvidenceResult, EvidenceType, ExplorerEntry

logger = logging.getLogger(__name__)

# Default sample row limit
DEFAULT_SAMPLE_LIMIT = 10

# Maximum total data size (500KB)
MAX_DATA_SIZE = 512 * 1024


class SqlCapture(CaptureStrategy):
    """Capture strategy for database tables.

    Captures schema snapshots including column definitions, constraints,
    indexes, and optional sample data. Used for schema regression detection.
    """

    @property
    def name(self) -> str:
        return "SQL Capture"

    def supports_entry_type(self, entry_type: str) -> bool:
        return entry_type == "table"

    def get_evidence_types(self) -> list[EvidenceType]:
        return ["schema_snapshot"]

    async def capture(
        self,
        entry: ExplorerEntry,
        config: CaptureConfig,
    ) -> list[EvidenceResult]:
        """Capture schema snapshot for a database table.

        Requires metadata.connection_string or DATABASE_URL environment variable.
        """
        connection_string = self._get_connection_string(entry)

        if not connection_string:
            return [
                EvidenceResult.failure(
                    "schema_snapshot",
                    "No database connection string. "
                    "Set 'connection_string' in entry metadata or DATABASE_URL env var.",
                )
            ]

        table_name = entry.get("path", "") or entry.get("name", "")
        if not table_name:
            return [
                EvidenceResult.failure(
                    "schema_snapshot",
                    "No table name specified in entry path or name.",
                )
            ]

        result = await self._capture_schema(table_name, connection_string, entry, config)
        return [result]

    def _get_connection_string(self, entry: ExplorerEntry) -> str | None:
        """Get database connection string from entry or environment."""
        metadata = entry.get("metadata", {})

        # Entry metadata has highest priority
        if conn_str := metadata.get("connection_string"):
            return str(conn_str)

        # Fall back to environment variable
        return os.getenv("DATABASE_URL")

    async def _capture_schema(
        self,
        table_name: str,
        connection_string: str,
        entry: ExplorerEntry,
        config: CaptureConfig,
    ) -> EvidenceResult:
        """Capture table schema and optional sample data."""
        metadata = entry.get("metadata", {})
        sample_limit = metadata.get("sample_limit", DEFAULT_SAMPLE_LIMIT)
        include_sample_data = metadata.get("include_sample_data", True)

        start_time = time.perf_counter()

        try:
            # Import psycopg here to avoid hard dependency
            import psycopg

            async with await psycopg.AsyncConnection.connect(connection_string) as conn:
                schema_data = await self._get_schema_info(conn, table_name)

                if not schema_data["columns"]:
                    return EvidenceResult.failure(
                        "schema_snapshot",
                        f"Table '{table_name}' not found or has no columns.",
                    )

                # Get row count
                row_count = await self._get_row_count(conn, table_name)
                schema_data["row_count"] = row_count

                # Get sample data if requested
                if include_sample_data and row_count > 0:
                    sample_data = await self._get_sample_data(conn, table_name, sample_limit)
                    schema_data["sample_data"] = sample_data

                # Get indexes
                indexes = await self._get_indexes(conn, table_name)
                schema_data["indexes"] = indexes

                # Get foreign keys
                foreign_keys = await self._get_foreign_keys(conn, table_name)
                schema_data["foreign_keys"] = foreign_keys

            duration_ms = int((time.perf_counter() - start_time) * 1000)

            return EvidenceResult(
                success=True,
                evidence_type="schema_snapshot",
                metadata={
                    "table_name": table_name,
                    "duration_ms": duration_ms,
                    **schema_data,
                },
                duration_ms=duration_ms,
            )

        except ImportError:
            return EvidenceResult.failure(
                "schema_snapshot",
                "psycopg not installed. Install with: pip install psycopg[binary]",
            )
        except Exception as e:
            logger.exception(f"Error capturing schema for table: {table_name}")
            return EvidenceResult.failure("schema_snapshot", str(e))

    async def _get_schema_info(
        self,
        conn: Any,  # psycopg.AsyncConnection
        table_name: str,
    ) -> dict[str, Any]:
        """Get column information for a table."""
        query = """
            SELECT
                column_name,
                data_type,
                is_nullable,
                column_default,
                character_maximum_length,
                numeric_precision,
                numeric_scale
            FROM information_schema.columns
            WHERE table_name = %s
            ORDER BY ordinal_position
        """

        columns = []
        async with conn.cursor() as cur:
            await cur.execute(query, (table_name,))
            rows = await cur.fetchall()

            for row in rows:
                columns.append(
                    {
                        "name": row[0],
                        "type": row[1],
                        "nullable": row[2] == "YES",
                        "default": row[3],
                        "max_length": row[4],
                        "precision": row[5],
                        "scale": row[6],
                    }
                )

        # Get primary key columns
        pk_query = """
            SELECT kcu.column_name
            FROM information_schema.table_constraints tc
            JOIN information_schema.key_column_usage kcu
                ON tc.constraint_name = kcu.constraint_name
            WHERE tc.table_name = %s
                AND tc.constraint_type = 'PRIMARY KEY'
            ORDER BY kcu.ordinal_position
        """

        pk_columns = []
        async with conn.cursor() as cur:
            await cur.execute(pk_query, (table_name,))
            rows = await cur.fetchall()
            pk_columns = [row[0] for row in rows]

        return {
            "columns": columns,
            "primary_key": pk_columns,
        }

    async def _get_row_count(
        self,
        conn: Any,
        table_name: str,
    ) -> int:
        """Get approximate row count for a table."""
        # Use reltuples for large tables (faster but approximate)
        query = """
            SELECT reltuples::bigint
            FROM pg_class
            WHERE relname = %s
        """

        async with conn.cursor() as cur:
            await cur.execute(query, (table_name,))
            row = await cur.fetchone()
            if row and row[0] >= 0:
                return int(row[0])

        # Fall back to COUNT(*) for small tables or if reltuples is -1
        query = f"SELECT COUNT(*) FROM {table_name}"
        async with conn.cursor() as cur:
            await cur.execute(query)
            row = await cur.fetchone()
            return int(row[0]) if row else 0

    async def _get_sample_data(
        self,
        conn: Any,
        table_name: str,
        limit: int,
    ) -> list[dict[str, Any]]:
        """Get sample rows from the table."""
        query = f"SELECT * FROM {table_name} LIMIT %s"

        async with conn.cursor() as cur:
            await cur.execute(query, (limit,))
            columns = [desc[0] for desc in cur.description or []]
            rows = await cur.fetchall()

            sample_data = []
            for row in rows:
                sample_data.append(
                    dict(zip(columns, [self._serialize_value(v) for v in row], strict=False))
                )

            return sample_data

    async def _get_indexes(
        self,
        conn: Any,
        table_name: str,
    ) -> list[dict[str, Any]]:
        """Get index information for a table."""
        query = """
            SELECT
                i.relname AS index_name,
                a.attname AS column_name,
                ix.indisunique AS is_unique,
                ix.indisprimary AS is_primary
            FROM pg_class t
            JOIN pg_index ix ON t.oid = ix.indrelid
            JOIN pg_class i ON i.oid = ix.indexrelid
            JOIN pg_attribute a ON a.attrelid = t.oid AND a.attnum = ANY(ix.indkey)
            WHERE t.relname = %s
            ORDER BY i.relname, a.attnum
        """

        indexes: dict[str, dict[str, Any]] = {}
        async with conn.cursor() as cur:
            await cur.execute(query, (table_name,))
            rows = await cur.fetchall()

            for row in rows:
                index_name = row[0]
                if index_name not in indexes:
                    indexes[index_name] = {
                        "name": index_name,
                        "columns": [],
                        "unique": row[2],
                        "primary": row[3],
                    }
                indexes[index_name]["columns"].append(row[1])

        return list(indexes.values())

    async def _get_foreign_keys(
        self,
        conn: Any,
        table_name: str,
    ) -> list[dict[str, Any]]:
        """Get foreign key constraints for a table."""
        query = """
            SELECT
                tc.constraint_name,
                kcu.column_name,
                ccu.table_name AS foreign_table,
                ccu.column_name AS foreign_column
            FROM information_schema.table_constraints tc
            JOIN information_schema.key_column_usage kcu
                ON tc.constraint_name = kcu.constraint_name
            JOIN information_schema.constraint_column_usage ccu
                ON ccu.constraint_name = tc.constraint_name
            WHERE tc.table_name = %s
                AND tc.constraint_type = 'FOREIGN KEY'
        """

        foreign_keys = []
        async with conn.cursor() as cur:
            await cur.execute(query, (table_name,))
            rows = await cur.fetchall()

            for row in rows:
                foreign_keys.append(
                    {
                        "constraint_name": row[0],
                        "column": row[1],
                        "references_table": row[2],
                        "references_column": row[3],
                    }
                )

        return foreign_keys

    def _serialize_value(self, value: Any) -> Any:
        """Serialize a database value for JSON storage."""
        if value is None:
            return None
        if isinstance(value, str | int | float | bool):
            return value
        if isinstance(value, list | dict):
            return value
        # Convert other types to string
        return str(value)


async def capture_table_schema(
    table_name: str,
    *,
    connection_string: str | None = None,
    sample_limit: int = DEFAULT_SAMPLE_LIMIT,
    include_sample_data: bool = True,
) -> EvidenceResult:
    """Convenience function to capture a table's schema.

    Args:
        table_name: Name of the table to capture
        connection_string: Database connection string (or uses DATABASE_URL)
        sample_limit: Maximum number of sample rows
        include_sample_data: Whether to include sample data

    Returns:
        EvidenceResult with schema information
    """
    entry: ExplorerEntry = {
        "id": 0,
        "project_id": "",
        "entry_type": "table",
        "path": table_name,
        "name": table_name,
        "metadata": {
            "connection_string": connection_string,
            "sample_limit": sample_limit,
            "include_sample_data": include_sample_data,
        },
    }
    config: CaptureConfig = {}

    strategy = SqlCapture()
    results = await strategy.capture(entry, config)
    return (
        results[0]
        if results
        else EvidenceResult.failure(
            "schema_snapshot",
            "No results from capture",
        )
    )
