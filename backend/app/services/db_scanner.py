"""Database table scanner for SummitFlow.

Scans PostgreSQL tables to discover database capabilities per project.
Introspects table metadata: row counts, columns, freshness, health status.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import create_engine, inspect, text

from app.logging_config import get_logger
from app.storage.connection import get_connection

logger = get_logger(__name__)

# System tables to exclude from scanning
SYSTEM_TABLES = {
    "celery_taskmeta",
    "celery_tasksetmeta",
    "alembic_version",
    "spatial_ref_sys",
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
    if "evidence" in name or "artifact" in name or "screenshot" in name:
        return "evidence"
    if "vision" in name or "goal" in name:
        return "vision"
    if "file" in name or "scan" in name:
        return "files"
    if "project" in name:
        return "projects"

    return "data"


def calculate_health(
    row_count: int,
    completeness_pct: int,
    freshness_status: str | None,
) -> str:
    """Calculate overall health status."""
    if row_count == 0:
        return "warning"  # Empty table
    if completeness_pct < 50:
        return "warning"  # Low data completeness
    if freshness_status == "stale":
        return "warning"
    if freshness_status == "critical":
        return "error"
    return "healthy"


class DatabaseScanner:
    """Scans database tables for a project."""

    def __init__(self, project_id: str, db_url: str) -> None:
        """Initialize scanner.

        Args:
            project_id: The project ID to associate results with
            db_url: PostgreSQL connection URL for the project's database
        """
        self.project_id = project_id
        self.db_url = db_url

    def scan(self) -> list[dict[str, Any]]:
        """Scan all database tables.

        Returns:
            List of table capability dicts
        """
        logger.info("scanning_database", project=self.project_id)

        engine = create_engine(self.db_url)
        inspector = inspect(engine)

        capabilities = []

        with engine.connect() as conn:
            for table_name in inspector.get_table_names():
                if table_name in SYSTEM_TABLES:
                    continue

                try:
                    cap = self._scan_table(table_name, conn, inspector)
                    capabilities.append(cap)
                except Exception as e:
                    logger.error("table_scan_failed", table=table_name, error=str(e))

        logger.info("scan_complete", project=self.project_id, tables=len(capabilities))
        return capabilities

    def _scan_table(
        self,
        table_name: str,
        conn: Any,
        inspector: Any,
    ) -> dict[str, Any]:
        """Scan a single table."""
        # Row count
        result = conn.execute(text(f"SELECT COUNT(*) FROM {table_name}"))
        row = result.fetchone()
        row_count = int(row[0]) if row else 0

        # Columns
        columns = inspector.get_columns(table_name)
        column_names = [col["name"] for col in columns]
        total_columns = len(column_names)

        # Column completeness (simplified - check if columns have data)
        columns_with_data = []
        columns_mostly_null = []

        if row_count > 0:
            for col_name in column_names[:20]:  # Limit for performance
                try:
                    result = conn.execute(
                        text(f"SELECT COUNT({col_name}) FROM {table_name}")
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
            int((len(columns_with_data) / min(total_columns, 20)) * 100)
            if total_columns > 0
            else 0
        )

        # Date range detection
        date_range_start = None
        date_range_end = None
        days_since_update = None
        freshness_status = "unknown"

        date_columns = ["created_at", "updated_at", "timestamp", "date"]
        for date_col in date_columns:
            if date_col in column_names:
                try:
                    result = conn.execute(
                        text(f"SELECT MIN({date_col}), MAX({date_col}) FROM {table_name}")
                    )
                    row = result.fetchone()
                    if row and row[1]:
                        date_range_start = row[0].date() if hasattr(row[0], "date") else row[0]
                        date_range_end = row[1].date() if hasattr(row[1], "date") else row[1]
                        if date_range_end:
                            days_since = (datetime.now(UTC).date() - date_range_end).days
                            days_since_update = days_since
                            if days_since <= 1:
                                freshness_status = "fresh"
                            elif days_since <= 7:
                                freshness_status = "recent"
                            elif days_since <= 30:
                                freshness_status = "stale"
                            else:
                                freshness_status = "critical"
                        break
                except Exception:
                    continue

        category = categorize_table(table_name)
        health_status = calculate_health(row_count, completeness_pct, freshness_status)

        return {
            "table_name": table_name,
            "category": category,
            "row_count": row_count,
            "total_columns": total_columns,
            "columns": column_names,
            "columns_with_data": columns_with_data,
            "columns_mostly_null": columns_mostly_null,
            "completeness_pct": completeness_pct,
            "date_range_start": str(date_range_start) if date_range_start else None,
            "date_range_end": str(date_range_end) if date_range_end else None,
            "expected_freshness": "daily",  # Default
            "days_since_update": days_since_update,
            "freshness_status": freshness_status,
            "health_status": health_status,
            "fk_referenced_by": [],  # Simplified - can enhance later
        }

    def save(self, capabilities: list[dict[str, Any]]) -> int:
        """Save scan results to scanner_database table.

        Args:
            capabilities: List of table capability dicts

        Returns:
            Number of rows upserted
        """
        if not capabilities:
            return 0

        with get_connection() as conn, conn.cursor() as cur:
            for cap in capabilities:
                cur.execute(
                    """
                    INSERT INTO scanner_database (
                        project_id, table_name, category, row_count,
                        total_columns, columns, columns_with_data,
                        columns_mostly_null, completeness_pct,
                        date_range_start, date_range_end, expected_freshness,
                        days_since_update, freshness_status, health_status,
                        fk_referenced_by, last_scanned_at, updated_at
                    ) VALUES (
                        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW(), NOW()
                    )
                    ON CONFLICT (project_id, table_name) DO UPDATE SET
                        category = EXCLUDED.category,
                        row_count = EXCLUDED.row_count,
                        total_columns = EXCLUDED.total_columns,
                        columns = EXCLUDED.columns,
                        columns_with_data = EXCLUDED.columns_with_data,
                        columns_mostly_null = EXCLUDED.columns_mostly_null,
                        completeness_pct = EXCLUDED.completeness_pct,
                        date_range_start = EXCLUDED.date_range_start,
                        date_range_end = EXCLUDED.date_range_end,
                        expected_freshness = EXCLUDED.expected_freshness,
                        days_since_update = EXCLUDED.days_since_update,
                        freshness_status = EXCLUDED.freshness_status,
                        health_status = EXCLUDED.health_status,
                        fk_referenced_by = EXCLUDED.fk_referenced_by,
                        last_scanned_at = NOW(),
                        updated_at = NOW()
                    """,
                    [
                        self.project_id,
                        cap["table_name"],
                        cap["category"],
                        cap["row_count"],
                        cap["total_columns"],
                        json.dumps(cap["columns"]),
                        json.dumps(cap["columns_with_data"]),
                        json.dumps(cap["columns_mostly_null"]),
                        cap["completeness_pct"],
                        cap["date_range_start"],
                        cap["date_range_end"],
                        cap["expected_freshness"],
                        cap["days_since_update"],
                        cap["freshness_status"],
                        cap["health_status"],
                        json.dumps(cap["fk_referenced_by"]),
                    ],
                )
            conn.commit()

        return len(capabilities)


def get_project_db_url(project_id: str) -> str | None:
    """Get database URL for a project from its config.

    Args:
        project_id: The project ID

    Returns:
        Database URL or None if not configured
    """
    # For now, return known project DB URLs
    # In future, this would come from project.scanner_config
    db_urls = {
        "portfolio-ai": "postgresql://portfolio_ai_user:portfolio_ai_dev_2025@localhost:5432/portfolio_ai",
        "summitflow": "postgresql://portfolio_ai_user:portfolio_ai_dev_2025@localhost:5432/summitflow",
    }
    return db_urls.get(project_id)
