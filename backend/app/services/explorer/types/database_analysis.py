"""Database table analysis utilities.

Provides functions for analyzing table columns, freshness, and completeness.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import text

logger = logging.getLogger(__name__)


def analyze_column_completeness(
    table_name: str,
    column_names: list[str],
    row_count: int,
    conn: Any,
) -> tuple[list[str], list[str], int]:
    """Analyze which columns have data and which are mostly null.

    Args:
        table_name: Name of the table being analyzed
        column_names: List of column names to analyze
        row_count: Total number of rows in the table
        conn: Database connection object

    Returns:
        Tuple of (columns_with_data, columns_mostly_null, completeness_pct)
    """
    columns_with_data = []
    columns_mostly_null = []

    if row_count > 0:
        for col_name in column_names[:20]:  # Limit for performance
            try:
                result = conn.execute(text(f'SELECT COUNT("{col_name}") FROM "{table_name}"'))
                row = result.fetchone()
                non_null = int(row[0]) if row else 0
                if non_null > 0:
                    columns_with_data.append(col_name)
                if row_count > 0 and (row_count - non_null) / row_count > 0.5:
                    columns_mostly_null.append(col_name)
            except Exception:
                logger.debug("Failed to analyze column completeness for %s.%s", table_name, col_name, exc_info=True)
                continue

    column_count = len(column_names)
    completeness_pct = (
        int((len(columns_with_data) / min(column_count, 20)) * 100) if column_count > 0 else 0
    )

    return columns_with_data, columns_mostly_null, completeness_pct


def analyze_table_freshness(
    table_name: str,
    column_names: list[str],
    conn: Any,
) -> int | None:
    """Analyze table freshness by checking date columns.

    Args:
        table_name: Name of the table being analyzed
        column_names: List of column names to check for date columns
        conn: Database connection object

    Returns:
        Number of days since last update, or None if no date column found
    """
    date_columns = ["created_at", "updated_at", "timestamp", "date"]
    for date_col in date_columns:
        if date_col in column_names:
            try:
                result = conn.execute(text(f'SELECT MAX("{date_col}") FROM "{table_name}"'))
                row = result.fetchone()
                if row and row[0]:
                    last_date = row[0]
                    if hasattr(last_date, "date"):
                        last_date = last_date.date()
                    days: int = (datetime.now(UTC).date() - last_date).days
                    return days
            except Exception:
                logger.debug("Failed to analyze freshness for %s.%s", table_name, date_col, exc_info=True)
                continue
    return None


def extract_foreign_key_references(foreign_keys: list[dict[str, Any]]) -> list[str]:
    """Extract foreign key references in a standardized format.

    Args:
        foreign_keys: List of foreign key dictionaries from SQLAlchemy inspector

    Returns:
        List of foreign key references in "table.column" format
    """
    return [
        f"{fk['referred_table']}.{fk['referred_columns'][0]}"
        for fk in foreign_keys
        if fk.get("referred_columns")
    ]


def build_table_metadata(
    table_name: str,
    row_count: int,
    column_names: list[str],
    columns_with_data: list[str],
    columns_mostly_null: list[str],
    completeness_pct: int,
    freshness_days: int | None,
    references: list[str],
    violations: list[dict[str, Any]],
    category: str,
) -> dict[str, Any]:
    """Build metadata dictionary for a table entry.

    Args:
        table_name: Name of the table
        row_count: Number of rows in the table
        column_names: List of column names
        columns_with_data: Columns that have non-null data
        columns_mostly_null: Columns that are >50% null
        completeness_pct: Percentage of columns with data
        freshness_days: Days since last update
        references: Foreign key references
        violations: Schema violations
        category: Table category

    Returns:
        Metadata dictionary for ExplorerEntryCreate
    """
    return {
        "row_count": row_count,
        "column_count": len(column_names),
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
        "violations": violations,
    }
