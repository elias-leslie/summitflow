"""Storage layer for design standards.

Manages UI/UX design standards with inheritance support:
- Base standards (global, project_id is NULL)
- Project-specific standards that can inherit from base
- Design rules within standards organized by category
"""

from typing import Any

# Import rules operations
from .design_rules import (
    create_rule,
    delete_rule,
    get_rule,
    list_rules,
    list_rules_by_category,
    upsert_rule,
)
from .design_rules import (
    get_effective_rules as _get_effective_rules,
)

# Import CRUD operations
from .design_standards_crud import (
    create_standard,
    delete_standard,
    get_base_standard,
    get_project_standard,
    get_standard_by_id,
    list_standards,
    update_standard,
)

# Import validation operations
from .design_validation import validate_against_rules as _validate_against_rules

__all__ = [
    "create_rule",
    "create_standard",
    "delete_rule",
    "delete_standard",
    "get_base_standard",
    "get_effective_rules",
    "get_project_standard",
    "get_rule",
    "get_standard_by_id",
    "inherit_from_base",
    "list_rules",
    "list_rules_by_category",
    "list_standards",
    "update_standard",
    "upsert_rule",
    "validate_against_rules",
]


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

    base_id = base["id"] if base else None
    project_id_int = project_standard["id"] if project_standard else None

    return _get_effective_rules(base_id, project_id_int, category)


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
    return _validate_against_rules(rules, element_data)
