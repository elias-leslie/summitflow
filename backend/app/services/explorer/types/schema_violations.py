"""Schema violation detector for Explorer.

Detects database schema violations per M:4e199d70 Database Schema Checklist:
- Missing FK indexes
- Naming violations (non-snake_case, non-plural tables)
- Missing timestamps (created_at, updated_at)
- God tables (20+ columns)
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any

from ....logging_config import get_logger

logger = get_logger(__name__)


class ViolationType(Enum):
    MISSING_FK_INDEX = "missing_fk_index"
    NAMING_VIOLATION = "naming_violation"
    MISSING_TIMESTAMPS = "missing_timestamps"
    GOD_TABLE = "god_table"


@dataclass
class SchemaViolation:
    violation_type: ViolationType
    table_name: str
    detail: str
    severity: str = "warning"


class SchemaViolationDetector:
    """Detects schema violations in database tables."""

    GOD_TABLE_COLUMN_THRESHOLD = 20

    def __init__(self) -> None:
        self._fk_columns: dict[str, list[str]] = {}
        self._indexes: dict[str, set[str]] = {}

    def detect_violations(
        self,
        table_name: str,
        columns: list[dict[str, Any]],
        foreign_keys: list[dict[str, Any]],
        indexes: list[dict[str, Any]],
    ) -> list[SchemaViolation]:
        """Detect all schema violations for a table.

        Args:
            table_name: Name of the table
            columns: List of column info dicts from SQLAlchemy inspector
            foreign_keys: List of FK info dicts from SQLAlchemy inspector
            indexes: List of index info dicts from SQLAlchemy inspector

        Returns:
            List of detected violations
        """
        violations: list[SchemaViolation] = []

        violations.extend(self._check_missing_fk_indexes(table_name, foreign_keys, indexes))
        violations.extend(self._check_naming_violations(table_name, columns))
        violations.extend(self._check_missing_timestamps(table_name, columns))
        violations.extend(self._check_god_table(table_name, columns))

        return violations

    def _check_missing_fk_indexes(
        self,
        table_name: str,
        foreign_keys: list[dict[str, Any]],
        indexes: list[dict[str, Any]],
    ) -> list[SchemaViolation]:
        """Check for FK columns that don't have indexes."""
        violations = []

        indexed_columns: set[str] = set()
        for idx in indexes:
            for col in idx.get("column_names", []):
                if col:
                    indexed_columns.add(col)

        for fk in foreign_keys:
            fk_cols = fk.get("constrained_columns", [])
            for col in fk_cols:
                if col and col not in indexed_columns:
                    violations.append(
                        SchemaViolation(
                            violation_type=ViolationType.MISSING_FK_INDEX,
                            table_name=table_name,
                            detail=f"FK column '{col}' lacks an index",
                            severity="warning",
                        )
                    )

        return violations

    def _check_naming_violations(
        self,
        table_name: str,
        columns: list[dict[str, Any]],
    ) -> list[SchemaViolation]:
        """Check for naming convention violations (snake_case, plural tables)."""
        violations = []

        if not self._is_snake_case(table_name):
            violations.append(
                SchemaViolation(
                    violation_type=ViolationType.NAMING_VIOLATION,
                    table_name=table_name,
                    detail=f"Table name '{table_name}' is not snake_case",
                    severity="warning",
                )
            )

        if not self._is_plural(table_name):
            violations.append(
                SchemaViolation(
                    violation_type=ViolationType.NAMING_VIOLATION,
                    table_name=table_name,
                    detail=f"Table name '{table_name}' should be plural",
                    severity="warning",
                )
            )

        for col in columns:
            col_name = col.get("name", "")
            if col_name and not self._is_snake_case(col_name):
                violations.append(
                    SchemaViolation(
                        violation_type=ViolationType.NAMING_VIOLATION,
                        table_name=table_name,
                        detail=f"Column '{col_name}' is not snake_case",
                        severity="warning",
                    )
                )

        return violations

    def _check_missing_timestamps(
        self,
        table_name: str,
        columns: list[dict[str, Any]],
    ) -> list[SchemaViolation]:
        """Check for missing created_at/updated_at timestamps."""
        violations = []

        column_names = {col.get("name", "").lower() for col in columns}

        if "created_at" not in column_names:
            violations.append(
                SchemaViolation(
                    violation_type=ViolationType.MISSING_TIMESTAMPS,
                    table_name=table_name,
                    detail="Missing created_at timestamp column",
                    severity="warning",
                )
            )

        if "updated_at" not in column_names:
            violations.append(
                SchemaViolation(
                    violation_type=ViolationType.MISSING_TIMESTAMPS,
                    table_name=table_name,
                    detail="Missing updated_at timestamp column",
                    severity="warning",
                )
            )

        return violations

    def _check_god_table(
        self,
        table_name: str,
        columns: list[dict[str, Any]],
    ) -> list[SchemaViolation]:
        """Check for god tables (20+ columns)."""
        violations = []

        column_count = len(columns)
        if column_count >= self.GOD_TABLE_COLUMN_THRESHOLD:
            violations.append(
                SchemaViolation(
                    violation_type=ViolationType.GOD_TABLE,
                    table_name=table_name,
                    detail=f"Table has {column_count} columns (threshold: {self.GOD_TABLE_COLUMN_THRESHOLD})",
                    severity="error",
                )
            )

        return violations

    @staticmethod
    def _is_snake_case(name: str) -> bool:
        """Check if a name follows snake_case convention."""
        if not name:
            return True
        import re

        return bool(re.match(r"^[a-z][a-z0-9_]*$", name))

    @staticmethod
    def _is_plural(name: str) -> bool:
        """Check if a table name is plural (ends with 's', 'es', or 'ies')."""
        if not name:
            return True
        name_lower = name.lower()
        return (
            name_lower.endswith("s")
            or name_lower.endswith("es")
            or name_lower.endswith("ies")
            or name_lower in {"data", "metadata", "info"}
        )
