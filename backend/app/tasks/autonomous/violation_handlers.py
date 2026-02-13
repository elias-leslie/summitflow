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
        "dt mypy passes",
    ]

    specific = {
        "missing_fk_index": [f"Index exists on FK column in {table_name}"],
        "naming_violation": ["Table/columns follow snake_case convention"],
        "missing_timestamps": [f"{table_name} has created_at and updated_at columns"],
        "god_table": [f"{table_name} has fewer than 20 columns"],
    }

    return specific.get(violation_type, []) + base


def get_violation_steps(violation_type: str, table_name: str, detail: str) -> list[dict[str, str]]:
    """Generate verification steps for a schema violation task."""
    steps = {
        "missing_fk_index": [
            {
                "description": f"Create migration to add index on FK column in {table_name}",
                "verify_command": f"ls backend/alembic/versions/*{table_name.lower()}*.py 2>/dev/null | head -1",
            },
            {
                "description": "Apply migration",
                "verify_command": "cd backend && alembic upgrade head",
            },
            {
                "description": "Verify index exists",
                "verify_command": f"psql $DATABASE_URL -c \"SELECT indexname FROM pg_indexes WHERE tablename = '{table_name}'\"",
            },
        ],
        "naming_violation": [
            {
                "description": f"Create migration to rename {table_name} or columns",
                "verify_command": "ls backend/alembic/versions/*rename*.py 2>/dev/null | head -1",
            },
            {
                "description": "Update all model references",
                "verify_command": "dt mypy",
            },
            {
                "description": "Apply migration",
                "verify_command": "cd backend && alembic upgrade head",
            },
        ],
        "missing_timestamps": [
            {
                "description": f"Create migration to add timestamps to {table_name}",
                "verify_command": "ls backend/alembic/versions/*timestamp*.py 2>/dev/null | head -1",
            },
            {
                "description": "Update SQLAlchemy model with timestamp columns",
                "verify_command": f"rg 'created_at|updated_at' backend/app/models/*.py | rg -i {table_name}",
            },
            {
                "description": "Apply migration",
                "verify_command": "cd backend && alembic upgrade head",
            },
        ],
        "god_table": [
            {
                "description": f"Analyze {table_name} for column groupings",
                "verify_command": f"psql $DATABASE_URL -c \"SELECT column_name FROM information_schema.columns WHERE table_name = '{table_name}'\" | wc -l",
            },
            {
                "description": "Create migration to extract related columns",
                "verify_command": f"ls backend/alembic/versions/*{table_name.lower()}*.py 2>/dev/null | head -1",
            },
            {
                "description": "Verify column count reduced",
                "verify_command": f"psql $DATABASE_URL -c \"SELECT COUNT(*) FROM information_schema.columns WHERE table_name = '{table_name}'\" | tail -3 | head -1 | xargs test 20 -gt",
            },
        ],
    }

    return steps.get(
        violation_type,
        [
            {
                "description": f"Fix schema violation in {table_name}: {detail}",
                "verify_command": "dt mypy",
            },
        ],
    )


def get_consolidated_architecture_title(violation_type: str, file_count: int) -> str:
    """Generate consolidated task title for a violation type."""
    titles = {
        "parallel_implementation": f"Consolidate parallel implementations ({file_count} files)",
        "missing_infrastructure": f"Add missing infrastructure ({file_count} files)",
        "duplicate_utility": f"Remove duplicate code ({file_count} files)",
    }
    return titles.get(violation_type, f"Fix {violation_type} ({file_count} files)")


def get_consolidated_architecture_objective(violation_type: str, affected_files: list[str]) -> str:
    """Generate objective for a consolidated architecture task."""
    file_list = ", ".join(f.split("/")[-1] for f in affected_files[:5])
    if len(affected_files) > 5:
        file_list += f" and {len(affected_files) - 5} more"

    objectives = {
        "parallel_implementation": (
            f"Consolidate multiple implementations into a single shared utility. "
            f"Affected files: {file_list}. Identify the best implementation and refactor others to use it."
        ),
        "missing_infrastructure": (
            f"Add missing infrastructure (logging, error handling, observability) to API endpoints. "
            f"Affected files: {file_list}. Follow existing patterns in the codebase."
        ),
        "duplicate_utility": (
            f"Remove literal code duplication by extracting shared utilities. "
            f"Affected files: {file_list}. DRY principle - extract to shared module."
        ),
    }
    return objectives.get(violation_type, f"Fix {violation_type} in {file_list}")


def get_consolidated_architecture_done_when(violation_type: str) -> list[str]:
    """Generate done_when criteria for a consolidated architecture task."""
    criteria = {
        "parallel_implementation": [
            "Single canonical implementation exists",
            "All usages refactored to use shared implementation",
            "No duplicate implementations remain",
            "Tests pass after consolidation",
        ],
        "missing_infrastructure": [
            "All affected files have proper logging",
            "Error handling follows project patterns",
            "No linting warnings for missing infrastructure",
        ],
        "duplicate_utility": [
            "Shared utility extracted to appropriate location",
            "All duplicate code replaced with utility calls",
            "No copy-paste code detected by jscpd",
        ],
    }
    return criteria.get(violation_type, [f"All {violation_type} violations resolved"])
