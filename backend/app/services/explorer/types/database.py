"""Database scanner for Explorer.

Scans PostgreSQL tables and produces entries for explorer_entries table.

Metadata schema (per architecture doc):
{
  "row_count": 123456,
  "column_count": 12,
  "columns": ["id", "name", "created_at"],
  "columns_with_data": ["id", "name"],
  "columns_mostly_null": ["deleted_at"],
  "completeness_pct": 85,
  "freshness_days": 0,
  "category": "core",
  "relationships": {
    "references": ["users.id"],
    "referenced_by": ["orders.product_id"]
  }
}
"""

from __future__ import annotations

import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from sqlalchemy import create_engine, inspect, text

from ....logging_config import get_logger
from ..base import BaseScanner
from ..models import ExplorerEntryCreate

logger = get_logger(__name__)

# Load environment from ~/.env.local
_env_file = Path.home() / ".env.local"
if _env_file.exists():
    load_dotenv(_env_file)

# System tables to exclude
SYSTEM_TABLES = {
    "celery_taskmeta", "celery_tasksetmeta", "alembic_version",
    "spatial_ref_sys",
}

# Map project IDs to environment variable names
PROJECT_DB_ENV_VARS = {
    "portfolio-ai": "PORTFOLIO_AI_DB_URL",
    "summitflow": "DATABASE_URL",
}


def categorize_table(table_name: str) -> str:
    """Categorize a table by its name pattern."""
    name = table_name.lower()

    if "user" in name or "auth" in name or "credential" in name:
        return "auth"
    if "log" in name or "history" in name or "audit" in name:
        return "logging"
    if "config" in name or "setting" in name or "pref" in name:
        return "config"
    if "cache" in name or "temp" in name:
        return "cache"
    if "metric" in name or "stat" in name or "analytic" in name:
        return "analytics"
    if "task" in name or "job" in name or "queue" in name:
        return "tasks"
    if "feature" in name or "capability" in name:
        return "features"
    if "sitemap" in name or "endpoint" in name or "route" in name:
        return "sitemap"
    if "evidence" in name or "artifact" in name:
        return "evidence"
    if "vision" in name or "goal" in name:
        return "vision"
    if "file" in name or "scan" in name or "explorer" in name:
        return "files"
    if "project" in name:
        return "projects"

    return "data"


class DatabaseScanner(BaseScanner):
    """Scans database tables for explorer entries."""

    entry_type = "table"

    def __init__(self, project_id: str, config: dict | None = None) -> None:
        super().__init__(project_id, config)
        self.db_url: str | None = None

    def scan(self) -> list[ExplorerEntryCreate]:
        """Scan database tables and return entries."""
        # Get DB URL from config or environment variable
        self.db_url = self.config.get("db_url") if self.config else None
        if not self.db_url:
            env_var = PROJECT_DB_ENV_VARS.get(self.project_id)
            if env_var:
                self.db_url = os.environ.get(env_var)

        if not self.db_url:
            logger.error(f"No database URL configured for project {self.project_id}")
            return []

        logger.info(f"Database scan started for {self.project_id}")

        entries: list[ExplorerEntryCreate] = []

        try:
            engine = create_engine(self.db_url)
            inspector = inspect(engine)

            with engine.connect() as conn:
                for table_name in inspector.get_table_names():
                    if table_name in SYSTEM_TABLES:
                        continue

                    try:
                        entry = self._scan_table(table_name, conn, inspector)
                        if entry:
                            entries.append(entry)
                    except Exception as e:
                        logger.warning(f"Failed to scan table {table_name}: {e}")

            logger.info(f"Database scan found {len(entries)} tables")

        except Exception as e:
            logger.error(f"Database scan failed: {e}")

        return entries

    def _scan_table(
        self,
        table_name: str,
        conn: Any,
        inspector: Any,
    ) -> ExplorerEntryCreate | None:
        """Scan a single table and return entry."""
        # Row count
        result = conn.execute(text(f'SELECT COUNT(*) FROM "{table_name}"'))
        row = result.fetchone()
        row_count = int(row[0]) if row else 0

        # Columns
        columns = inspector.get_columns(table_name)
        column_names = [col["name"] for col in columns]
        column_count = len(column_names)

        # Column completeness
        columns_with_data = []
        columns_mostly_null = []

        if row_count > 0:
            for col_name in column_names[:20]:  # Limit for performance
                try:
                    result = conn.execute(
                        text(f'SELECT COUNT("{col_name}") FROM "{table_name}"')
                    )
                    row = result.fetchone()
                    non_null = int(row[0]) if row else 0
                    if non_null > 0:
                        columns_with_data.append(col_name)
                    if row_count > 0 and (row_count - non_null) / row_count > 0.5:
                        columns_mostly_null.append(col_name)
                except Exception:
                    continue

        completeness_pct = (
            int((len(columns_with_data) / min(column_count, 20)) * 100)
            if column_count > 0
            else 0
        )

        # Freshness detection
        freshness_days = None
        date_columns = ["created_at", "updated_at", "timestamp", "date"]
        for date_col in date_columns:
            if date_col in column_names:
                try:
                    result = conn.execute(
                        text(f'SELECT MAX("{date_col}") FROM "{table_name}"')
                    )
                    row = result.fetchone()
                    if row and row[0]:
                        last_date = row[0]
                        if hasattr(last_date, "date"):
                            last_date = last_date.date()
                        freshness_days = (datetime.now(UTC).date() - last_date).days
                        break
                except Exception:
                    continue

        # Foreign key relationships
        fks = inspector.get_foreign_keys(table_name)
        references = [
            f"{fk['referred_table']}.{fk['referred_columns'][0]}"
            for fk in fks
            if fk.get("referred_columns")
        ]

        category = categorize_table(table_name)

        return ExplorerEntryCreate(
            path=table_name,
            name=table_name,
            health_status="unknown",  # Will be set by get_health_status
            metadata={
                "row_count": row_count,
                "column_count": column_count,
                "columns": column_names,
                "columns_with_data": columns_with_data,
                "columns_mostly_null": columns_mostly_null,
                "completeness_pct": completeness_pct,
                "freshness_days": freshness_days,
                "category": category,
                "relationships": {
                    "references": references,
                    "referenced_by": [],  # Populated later if needed
                },
            },
        )

    def get_health_status(self, entry: ExplorerEntryCreate) -> str:
        """Determine health status for a table entry."""
        meta = entry.metadata

        row_count = meta.get("row_count", 0)
        completeness = meta.get("completeness_pct", 0)
        freshness_days = meta.get("freshness_days")

        # Empty table
        if row_count == 0:
            return "warning"

        # Low completeness
        if completeness < 50:
            return "warning"

        # Stale data (>30 days)
        if freshness_days is not None:
            if freshness_days > 30:
                return "error"
            if freshness_days > 7:
                return "warning"

        return "healthy"
