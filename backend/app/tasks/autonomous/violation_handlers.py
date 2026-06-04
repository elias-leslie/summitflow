"""Handlers for schema and architecture violation tasks."""

from __future__ import annotations


def get_violation_title(violation_type: str, table_name: str) -> str:
    """Generate task title for a schema violation."""
    titles = {
        "missing_fk_index": f"Add missing FK index on {table_name}",
        "naming_violation": f"Fix naming convention in {table_name}",
        "missing_timestamps": f"Add timestamps to {table_name}",
        "god_table": f"Refactor {table_name} (too many columns)",
    }
    return titles.get(violation_type, f"Fix schema issue in {table_name}")


def get_violation_objective(violation_type: str, table_name: str, detail: str) -> str:
    """Generate objective for a schema violation task."""
    objectives = {
        "missing_fk_index": f"Add an index on the FK column in {table_name} to improve query performance. {detail}",
        "naming_violation": f"Rename {table_name} or its columns to follow snake_case and plural table naming conventions.",
        "missing_timestamps": f"Add created_at and updated_at timestamp columns to {table_name} for audit tracking.",
        "god_table": f"Refactor {table_name} by extracting related columns into separate tables to reduce complexity.",
    }
    return objectives.get(violation_type, f"Fix schema violation in {table_name}: {detail}")


def get_violation_done_when(violation_type: str, table_name: str) -> list[str]:
    """Generate done_when criteria for a schema violation task."""
    base = [
        "Migration created and applied successfully",
        "All existing queries still work",
        "st check types passes",
    ]

    specific = {
        "missing_fk_index": [f"Index exists on FK column in {table_name}"],
        "naming_violation": ["Table/columns follow snake_case convention"],
        "missing_timestamps": [f"{table_name} has created_at and updated_at columns"],
        "god_table": [f"{table_name} has fewer than 20 columns"],
    }

    return specific.get(violation_type, []) + base


def get_violation_steps(violation_type: str, table_name: str, detail: str) -> list[dict[str, str]]:
    """Generate steps for a schema violation task."""
    steps = {
        "missing_fk_index": [
            {"description": f"Create migration to add index on FK column in {table_name}"},
            {"description": "Apply migration"},
            {"description": "Verify index exists"},
        ],
        "naming_violation": [
            {"description": f"Create migration to rename {table_name} or columns"},
            {"description": "Update all model references"},
            {"description": "Apply migration"},
        ],
        "missing_timestamps": [
            {"description": f"Create migration to add timestamps to {table_name}"},
            {"description": "Update SQLAlchemy model with timestamp columns"},
            {"description": "Apply migration"},
        ],
        "god_table": [
            {"description": f"Analyze {table_name} for column groupings"},
            {"description": "Create migration to extract related columns"},
            {"description": "Verify column count reduced"},
        ],
    }

    return steps.get(
        violation_type,
        [{"description": f"Fix schema violation in {table_name}: {detail}"}],
    )
