"""Storage layer for design rules.

Manages individual design rules within standards:
- CRUD operations for rules
- Category-based organization
- Effective rules computation with inheritance
"""

from typing import Any

from psycopg.types.json import Jsonb

from .connection import get_connection


def _jsonb(data: dict[str, Any]) -> Jsonb:
    """Wrap dict in Jsonb for database insertion."""
    return Jsonb(data)


def create_rule(
    standard_id: int,
    category: str,
    rule_id: str,
    name: str,
    requirements: dict[str, Any],
) -> dict[str, Any]:
    """Create a design rule within a standard.

    Args:
        standard_id: Parent standard ID
        category: Rule category (layout, typography, color, component)
        rule_id: Unique rule identifier within standard
        name: Human-readable name
        requirements: JSONB requirements specification

    Returns:
        Created rule dict
    """
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO design_rules
                (standard_id, category, rule_id, name, requirements, created_at)
            VALUES (%s, %s, %s, %s, %s, NOW())
            RETURNING id, standard_id, category, rule_id, name, requirements, created_at
            """,
            (standard_id, category, rule_id, name, _jsonb(requirements)),
        )
        row = cur.fetchone()
        conn.commit()

    if not row:
        raise ValueError("Failed to create design rule")

    return {
        "id": row[0],
        "standard_id": row[1],
        "category": row[2],
        "rule_id": row[3],
        "name": row[4],
        "requirements": row[5],
        "created_at": row[6],
    }


def get_rule(standard_id: int, rule_id: str) -> dict[str, Any] | None:
    """Get a specific rule from a standard.

    Args:
        standard_id: Standard ID
        rule_id: Rule identifier

    Returns:
        Rule dict or None if not found
    """
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, standard_id, category, rule_id, name, requirements, created_at
            FROM design_rules
            WHERE standard_id = %s AND rule_id = %s
            """,
            (standard_id, rule_id),
        )
        row = cur.fetchone()

    if not row:
        return None

    return {
        "id": row[0],
        "standard_id": row[1],
        "category": row[2],
        "rule_id": row[3],
        "name": row[4],
        "requirements": row[5],
        "created_at": row[6],
    }


def list_rules(standard_id: int, category: str | None = None) -> list[dict[str, Any]]:
    """List rules for a standard.

    Args:
        standard_id: Standard ID
        category: Optional category filter

    Returns:
        List of rule dicts
    """
    with get_connection() as conn, conn.cursor() as cur:
        if category:
            cur.execute(
                """
                SELECT id, standard_id, category, rule_id, name, requirements, created_at
                FROM design_rules
                WHERE standard_id = %s AND category = %s
                ORDER BY rule_id
                """,
                (standard_id, category),
            )
        else:
            cur.execute(
                """
                SELECT id, standard_id, category, rule_id, name, requirements, created_at
                FROM design_rules
                WHERE standard_id = %s
                ORDER BY category, rule_id
                """,
                (standard_id,),
            )
        rows = cur.fetchall()

    return [
        {
            "id": row[0],
            "standard_id": row[1],
            "category": row[2],
            "rule_id": row[3],
            "name": row[4],
            "requirements": row[5],
            "created_at": row[6],
        }
        for row in rows
    ]


def list_rules_by_category(standard_id: int) -> dict[str, list[dict[str, Any]]]:
    """List rules grouped by category.

    Args:
        standard_id: Standard ID

    Returns:
        Dict mapping category to list of rules
    """
    rules = list_rules(standard_id)
    result: dict[str, list[dict[str, Any]]] = {}

    for rule in rules:
        category = rule["category"]
        if category not in result:
            result[category] = []
        result[category].append(rule)

    return result


def get_effective_rules(
    base_standard_id: int | None,
    project_standard_id: int | None,
    category: str | None = None,
) -> list[dict[str, Any]]:
    """Get effective rules, merging base and project-specific.

    Project rules override base rules with the same rule_id.

    Args:
        base_standard_id: Base standard ID (None if no base)
        project_standard_id: Project standard ID (None if no project standard)
        category: Optional category filter

    Returns:
        List of effective rule dicts
    """
    rules_by_id: dict[str, dict[str, Any]] = {}

    # First add base rules
    if base_standard_id:
        for rule in list_rules(base_standard_id, category):
            rules_by_id[rule["rule_id"]] = {**rule, "source": "base"}

    # Then add/override with project rules
    if project_standard_id:
        for rule in list_rules(project_standard_id, category):
            rules_by_id[rule["rule_id"]] = {**rule, "source": "project"}

    return list(rules_by_id.values())


def upsert_rule(
    standard_id: int,
    category: str,
    rule_id: str,
    name: str,
    requirements: dict[str, Any],
) -> dict[str, Any]:
    """Create or update a design rule.

    Args:
        standard_id: Parent standard ID
        category: Rule category
        rule_id: Unique rule identifier
        name: Human-readable name
        requirements: JSONB requirements

    Returns:
        Created/updated rule dict
    """
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO design_rules
                (standard_id, category, rule_id, name, requirements, created_at)
            VALUES (%s, %s, %s, %s, %s, NOW())
            ON CONFLICT (standard_id, rule_id) DO UPDATE SET
                category = EXCLUDED.category,
                name = EXCLUDED.name,
                requirements = EXCLUDED.requirements
            RETURNING id, standard_id, category, rule_id, name, requirements, created_at
            """,
            (standard_id, category, rule_id, name, _jsonb(requirements)),
        )
        row = cur.fetchone()
        conn.commit()

    if not row:
        raise ValueError("Failed to upsert design rule")

    return {
        "id": row[0],
        "standard_id": row[1],
        "category": row[2],
        "rule_id": row[3],
        "name": row[4],
        "requirements": row[5],
        "created_at": row[6],
    }


def delete_rule(standard_id: int, rule_id: str) -> bool:
    """Delete a design rule.

    Args:
        standard_id: Standard ID
        rule_id: Rule identifier

    Returns:
        True if deleted, False if not found
    """
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            "DELETE FROM design_rules WHERE standard_id = %s AND rule_id = %s RETURNING id",
            (standard_id, rule_id),
        )
        row = cur.fetchone()
        conn.commit()

    return row is not None
