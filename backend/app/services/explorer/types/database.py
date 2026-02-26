"""Database scanner for Explorer.

Scans PostgreSQL tables and produces entries for explorer_entries table.
See database_analysis.py for metadata schema details.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import create_engine, inspect, text

from ....logging_config import get_logger
from ..base import BaseScanner
from ..health import calculate_health_for_entry
from ..models import ExplorerEntryCreate
from .database_analysis import (
    analyze_column_completeness,
    analyze_table_freshness,
    build_table_metadata,
    extract_foreign_key_references,
)
from .database_categories import categorize_table
from .database_config import SYSTEM_TABLES, get_db_url_for_project
from .schema_violations import SchemaViolationDetector

logger = get_logger(__name__)


class DatabaseScanner(BaseScanner):
    """Scans database tables for explorer entries."""

    entry_type = "table"

    def __init__(self, project_id: str, config: dict[str, Any] | None = None) -> None:
        super().__init__(project_id, config)
        self.db_url: str | None = None
        self._violation_detector = SchemaViolationDetector()

    def scan(self) -> list[ExplorerEntryCreate]:
        """Scan database tables and return entries."""
        self.db_url = self.config.get("db_url") if self.config else None
        if not self.db_url:
            self.db_url = get_db_url_for_project(self.project_id)

        if not self.db_url:
            logger.warning(f"No database URL configured for project {self.project_id}")
            return []

        logger.info(f"Database scan started for {self.project_id}")

        entries: list[ExplorerEntryCreate] = []
        try:
            engine = create_engine(self.db_url)
            inspector = inspect(engine)
            with engine.connect() as conn:
                self._collect_entries(conn, inspector, entries)
            logger.info(f"Database scan found {len(entries)} tables")
        except Exception as e:
            logger.error(f"Database scan failed: {e}")

        return entries

    def _collect_entries(
        self,
        conn: Any,
        inspector: Any,
        entries: list[ExplorerEntryCreate],
    ) -> None:
        """Iterate tables and append scanned entries, skipping system tables."""
        for table_name in inspector.get_table_names():
            if table_name in SYSTEM_TABLES:
                continue
            self._try_append_entry(table_name, conn, inspector, entries)

    def _try_append_entry(
        self,
        table_name: str,
        conn: Any,
        inspector: Any,
        entries: list[ExplorerEntryCreate],
    ) -> None:
        """Scan one table and append the result, logging on failure."""
        try:
            entry = self._scan_table(table_name, conn, inspector)
            if entry:
                entries.append(entry)
        except Exception as e:
            logger.warning(f"Failed to scan table {table_name}: {e}")

    def _get_row_count(self, table_name: str, conn: Any) -> int:
        """Return the number of rows in the given table."""
        result = conn.execute(text(f'SELECT COUNT(*) FROM "{table_name}"'))
        row = result.fetchone()
        return int(row[0]) if row else 0

    def _get_schema_violations(
        self,
        table_name: str,
        columns: list[Any],
        fks: list[Any],
        indexes: list[Any],
    ) -> list[dict[str, Any]]:
        """Detect schema violations and return serialised violation dicts."""
        schema_violations = self._violation_detector.detect_violations(
            table_name=table_name,
            columns=columns,
            foreign_keys=fks,
            indexes=indexes,
        )
        return [
            {"type": v.violation_type.value, "detail": v.detail, "severity": v.severity}
            for v in schema_violations
        ]

    def _scan_table(
        self,
        table_name: str,
        conn: Any,
        inspector: Any,
    ) -> ExplorerEntryCreate | None:
        """Scan a single table and return entry."""
        row_count = self._get_row_count(table_name, conn)

        columns = inspector.get_columns(table_name)
        column_names = [col["name"] for col in columns]

        columns_with_data, columns_mostly_null, completeness_pct = analyze_column_completeness(
            table_name, column_names, row_count, conn
        )

        freshness_days = analyze_table_freshness(table_name, column_names, conn)

        fks = inspector.get_foreign_keys(table_name)
        references = extract_foreign_key_references(fks)

        indexes = inspector.get_indexes(table_name)
        violations = self._get_schema_violations(table_name, columns, fks, indexes)

        category = categorize_table(table_name)

        metadata = build_table_metadata(
            table_name,
            row_count,
            column_names,
            columns_with_data,
            columns_mostly_null,
            completeness_pct,
            freshness_days,
            references,
            violations,
            category,
        )

        return ExplorerEntryCreate(
            path=table_name,
            name=table_name,
            health_status="unknown",  # Will be set by get_health_status
            metadata=metadata,
        )

    def get_health_status(self, entry: ExplorerEntryCreate) -> str:
        """Determine health status for a table entry."""
        return calculate_health_for_entry(self.entry_type, entry.metadata)
