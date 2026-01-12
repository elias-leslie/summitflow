"""Storage layer for design standards.

Manages UI/UX design standards with inheritance support:
- Base standards (global, project_id is NULL)
- Project-specific standards that can inherit from base
- Design rules within standards organized by category
"""

from typing import Any

from psycopg.types.json import Jsonb

from .connection import get_connection


def _jsonb(data: dict[str, Any]) -> Jsonb:
    """Wrap dict in Jsonb for database insertion."""
    return Jsonb(data)


def get_base_standard() -> dict[str, Any] | None:
    """Get the base (global) design standard.

    Returns:
        Base standard dict or None if not found
    """
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, project_id, name, description, base_standard_id, is_base,
                   created_at, updated_at
            FROM design_standards
            WHERE is_base = TRUE AND project_id IS NULL
            LIMIT 1
            """
        )
        row = cur.fetchone()

    if not row:
        return None

    return {
        "id": row[0],
        "project_id": row[1],
        "name": row[2],
        "description": row[3],
        "base_standard_id": row[4],
        "is_base": row[5],
        "created_at": row[6],
        "updated_at": row[7],
    }


def get_standard_by_id(standard_id: int) -> dict[str, Any] | None:
    """Get a design standard by ID.

    Args:
        standard_id: Standard ID

    Returns:
        Standard dict or None if not found
    """
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, project_id, name, description, base_standard_id, is_base,
                   created_at, updated_at
            FROM design_standards
            WHERE id = %s
            """,
            (standard_id,),
        )
        row = cur.fetchone()

    if not row:
        return None

    return {
        "id": row[0],
        "project_id": row[1],
        "name": row[2],
        "description": row[3],
        "base_standard_id": row[4],
        "is_base": row[5],
        "created_at": row[6],
        "updated_at": row[7],
    }


def get_project_standard(project_id: str, name: str | None = None) -> dict[str, Any] | None:
    """Get project-specific design standard.

    Args:
        project_id: Project ID
        name: Optional standard name (defaults to first found)

    Returns:
        Standard dict or None if not found
    """
    with get_connection() as conn, conn.cursor() as cur:
        if name:
            cur.execute(
                """
                SELECT id, project_id, name, description, base_standard_id, is_base,
                       created_at, updated_at
                FROM design_standards
                WHERE project_id = %s AND name = %s
                """,
                (project_id, name),
            )
        else:
            cur.execute(
                """
                SELECT id, project_id, name, description, base_standard_id, is_base,
                       created_at, updated_at
                FROM design_standards
                WHERE project_id = %s
                ORDER BY created_at ASC
                LIMIT 1
                """,
                (project_id,),
            )
        row = cur.fetchone()

    if not row:
        return None

    return {
        "id": row[0],
        "project_id": row[1],
        "name": row[2],
        "description": row[3],
        "base_standard_id": row[4],
        "is_base": row[5],
        "created_at": row[6],
        "updated_at": row[7],
    }


def list_standards(project_id: str | None = None) -> list[dict[str, Any]]:
    """List design standards.

    Args:
        project_id: Optional project filter. If None, returns base standards only.

    Returns:
        List of standard dicts
    """
    with get_connection() as conn, conn.cursor() as cur:
        if project_id:
            cur.execute(
                """
                SELECT id, project_id, name, description, base_standard_id, is_base,
                       created_at, updated_at
                FROM design_standards
                WHERE project_id = %s OR (is_base = TRUE AND project_id IS NULL)
                ORDER BY is_base DESC, created_at ASC
                """,
                (project_id,),
            )
        else:
            cur.execute(
                """
                SELECT id, project_id, name, description, base_standard_id, is_base,
                       created_at, updated_at
                FROM design_standards
                WHERE is_base = TRUE AND project_id IS NULL
                ORDER BY created_at ASC
                """
            )
        rows = cur.fetchall()

    return [
        {
            "id": row[0],
            "project_id": row[1],
            "name": row[2],
            "description": row[3],
            "base_standard_id": row[4],
            "is_base": row[5],
            "created_at": row[6],
            "updated_at": row[7],
        }
        for row in rows
    ]


def create_standard(
    name: str,
    description: str | None = None,
    project_id: str | None = None,
    base_standard_id: int | None = None,
    is_base: bool = False,
) -> dict[str, Any]:
    """Create a new design standard.

    Args:
        name: Standard name
        description: Optional description
        project_id: Project ID (None for base standards)
        base_standard_id: ID of base standard to inherit from
        is_base: Whether this is a base standard

    Returns:
        Created standard dict
    """
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO design_standards
                (project_id, name, description, base_standard_id, is_base, created_at, updated_at)
            VALUES (%s, %s, %s, %s, %s, NOW(), NOW())
            RETURNING id, project_id, name, description, base_standard_id, is_base,
                      created_at, updated_at
            """,
            (project_id, name, description, base_standard_id, is_base),
        )
        row = cur.fetchone()
        conn.commit()

    if not row:
        raise ValueError("Failed to create design standard")

    return {
        "id": row[0],
        "project_id": row[1],
        "name": row[2],
        "description": row[3],
        "base_standard_id": row[4],
        "is_base": row[5],
        "created_at": row[6],
        "updated_at": row[7],
    }


def update_standard(
    standard_id: int,
    name: str | None = None,
    description: str | None = None,
) -> dict[str, Any] | None:
    """Update a design standard.

    Args:
        standard_id: Standard ID
        name: New name (optional)
        description: New description (optional)

    Returns:
        Updated standard dict or None if not found
    """
    updates = []
    params: list[Any] = []

    if name is not None:
        updates.append("name = %s")
        params.append(name)
    if description is not None:
        updates.append("description = %s")
        params.append(description)

    if not updates:
        return get_standard_by_id(standard_id)

    updates.append("updated_at = NOW()")
    params.append(standard_id)

    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            f"""
            UPDATE design_standards
            SET {", ".join(updates)}
            WHERE id = %s
            RETURNING id, project_id, name, description, base_standard_id, is_base,
                      created_at, updated_at
            """,
            params,
        )
        row = cur.fetchone()
        conn.commit()

    if not row:
        return None

    return {
        "id": row[0],
        "project_id": row[1],
        "name": row[2],
        "description": row[3],
        "base_standard_id": row[4],
        "is_base": row[5],
        "created_at": row[6],
        "updated_at": row[7],
    }


def delete_standard(standard_id: int) -> bool:
    """Delete a design standard and its rules.

    Args:
        standard_id: Standard ID

    Returns:
        True if deleted, False if not found
    """
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            "DELETE FROM design_standards WHERE id = %s RETURNING id",
            (standard_id,),
        )
        row = cur.fetchone()
        conn.commit()

    return row is not None


def inherit_from_base(project_id: str, standard_name: str = "default") -> dict[str, Any]:
    """Create a project standard that inherits from base.

    Args:
        project_id: Project ID
        standard_name: Name for the new standard

    Returns:
        Created standard dict

    Raises:
        ValueError: If no base standard exists
    """
    base = get_base_standard()
    if not base:
        raise ValueError("No base standard exists to inherit from")

    return create_standard(
        name=standard_name,
        description=f"Project standard inheriting from {base['name']}",
        project_id=project_id,
        base_standard_id=base["id"],
        is_base=False,
    )


# ============================================================
# Design Rules Operations
# ============================================================


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
    project_id: str,
    category: str | None = None,
) -> list[dict[str, Any]]:
    """Get effective rules for a project, merging base and project-specific.

    Project rules override base rules with the same rule_id.

    Args:
        project_id: Project ID
        category: Optional category filter

    Returns:
        List of effective rule dicts
    """
    base = get_base_standard()
    project_standard = get_project_standard(project_id)

    rules_by_id: dict[str, dict[str, Any]] = {}

    # First add base rules
    if base:
        for rule in list_rules(base["id"], category):
            rules_by_id[rule["rule_id"]] = {**rule, "source": "base"}

    # Then add/override with project rules
    if project_standard:
        for rule in list_rules(project_standard["id"], category):
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


def validate_against_rules(
    project_id: str,
    element_data: dict[str, Any],
    category: str | None = None,
) -> list[dict[str, Any]]:
    """Validate element data against design rules.

    Args:
        project_id: Project ID
        element_data: Element properties to validate
        category: Optional category filter

    Returns:
        List of violations with rule details
    """
    rules = get_effective_rules(project_id, category)
    violations = []

    for rule in rules:
        requirements = rule.get("requirements", {})
        for req_key, req_value in requirements.items():
            actual = element_data.get(req_key)
            if actual is None:
                continue

            # Check for exact match requirement
            if isinstance(req_value, dict):
                if "exact" in req_value and actual != req_value["exact"]:
                    violations.append(
                        {
                            "rule_id": rule["rule_id"],
                            "rule_name": rule["name"],
                            "category": rule["category"],
                            "requirement": req_key,
                            "expected": req_value["exact"],
                            "actual": actual,
                            "severity": req_value.get("severity", "warning"),
                        }
                    )
                # Check for range requirement
                elif "min" in req_value or "max" in req_value:
                    try:
                        val = float(actual) if not isinstance(actual, int | float) else actual
                        if "min" in req_value and val < req_value["min"]:
                            violations.append(
                                {
                                    "rule_id": rule["rule_id"],
                                    "rule_name": rule["name"],
                                    "category": rule["category"],
                                    "requirement": req_key,
                                    "expected": f">= {req_value['min']}",
                                    "actual": actual,
                                    "severity": req_value.get("severity", "warning"),
                                }
                            )
                        if "max" in req_value and val > req_value["max"]:
                            violations.append(
                                {
                                    "rule_id": rule["rule_id"],
                                    "rule_name": rule["name"],
                                    "category": rule["category"],
                                    "requirement": req_key,
                                    "expected": f"<= {req_value['max']}",
                                    "actual": actual,
                                    "severity": req_value.get("severity", "warning"),
                                }
                            )
                    except (ValueError, TypeError):
                        pass
                # Check for allowed values
                elif "allowed" in req_value and actual not in req_value["allowed"]:
                    violations.append(
                        {
                            "rule_id": rule["rule_id"],
                            "rule_name": rule["name"],
                            "category": rule["category"],
                            "requirement": req_key,
                            "expected": f"one of {req_value['allowed']}",
                            "actual": actual,
                            "severity": req_value.get("severity", "warning"),
                        }
                    )

    return violations
