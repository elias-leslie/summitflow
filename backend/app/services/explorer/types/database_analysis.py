"""Database table analysis and categorization utilities.

Provides functions for analyzing table columns, freshness, completeness,
and categorizing tables by naming patterns.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from ....logging_config import get_logger

logger = get_logger(__name__)


def _get_non_null_count(table_name: str, col_name: str, conn: Any) -> int | None:
    """Return the non-null count for a column, or None on failure."""
    try:
        result = conn.execute(text(f'SELECT COUNT("{col_name}") FROM "{table_name}"'))
        row = result.fetchone()
        return int(row[0]) if row else 0
    except (SQLAlchemyError, ValueError, TypeError) as exc:
        logger.debug("Failed to analyze column completeness for %s.%s: %s", table_name, col_name, exc, exc_info=True)
        return None


def _classify_column(col_name: str, non_null: int, row_count: int) -> tuple[bool, bool]:
    """Return (has_data, mostly_null) flags for a column."""
    has_data = non_null > 0
    mostly_null = (row_count - non_null) / row_count > 0.5
    return has_data, mostly_null


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
            non_null = _get_non_null_count(table_name, col_name, conn)
            if non_null is None:
                continue
            has_data, mostly_null = _classify_column(col_name, non_null, row_count)
            if has_data:
                columns_with_data.append(col_name)
            if mostly_null:
                columns_mostly_null.append(col_name)

    column_count = len(column_names)
    completeness_pct = (
        int((len(columns_with_data) / min(column_count, 20)) * 100) if column_count > 0 else 0
    )

    return columns_with_data, columns_mostly_null, completeness_pct


def _query_max_date(table_name: str, date_col: str, conn: Any) -> Any | None:
    """Query the MAX value of a date column; return None on failure."""
    try:
        result = conn.execute(text(f'SELECT MAX("{date_col}") FROM "{table_name}"'))
        row = result.fetchone()
        return row[0] if row and row[0] else None
    except (SQLAlchemyError, ValueError, TypeError):
        logger.debug("Failed to analyze freshness for %s.%s", table_name, date_col, exc_info=True)
        return None


def _days_since(last_date: Any) -> int:
    """Return the number of days between last_date and today."""
    if hasattr(last_date, "date"):
        last_date = last_date.date()
    return (datetime.now(UTC).date() - last_date).days


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
        if date_col not in column_names:
            continue
        last_date = _query_max_date(table_name, date_col, conn)
        if last_date is None:
            continue
        return _days_since(last_date)
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


# ---------------------------------------------------------------------------
# Table categorization
# ---------------------------------------------------------------------------

_DEFAULT_TABLE_CATEGORY = "data"

_TABLE_CATEGORY_PATTERNS: list[tuple[str, tuple[str, ...]]] = [
    ("auth",      ("user", "auth", "credential")),
    ("logging",   ("log", "history", "audit")),
    ("config",    ("config", "setting", "pref")),
    ("cache",     ("cache", "temp")),
    ("analytics", ("metric", "stat", "analytic")),
    ("tasks",     ("task", "job", "queue")),
    ("features",  ("feature", "capability")),
    ("sitemap",   ("sitemap", "endpoint", "route")),
    ("evidence",  ("evidence", "artifact")),
    ("vision",    ("vision", "goal")),
    ("files",     ("file", "scan", "explorer")),
    ("projects",  ("project",)),
]


def categorize_table(table_name: str) -> str:
    """Categorize a table by its name pattern."""
    name = table_name.lower()
    for category, keywords in _TABLE_CATEGORY_PATTERNS:
        if any(keyword in name for keyword in keywords):
            return category
    return _DEFAULT_TABLE_CATEGORY
