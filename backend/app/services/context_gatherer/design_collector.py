"""Design standards context collector."""

from __future__ import annotations

import logging
from typing import Any

from .token_utils import MAX_DESIGN_TOKENS, truncate_to_tokens

logger = logging.getLogger(__name__)


def _group_rules_by_category(
    rules: list[dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    """Group design rules by their category field."""
    by_category: dict[str, list[dict[str, Any]]] = {}
    for rule in rules:
        cat = rule.get("category", "general")
        if cat not in by_category:
            by_category[cat] = []
        by_category[cat].append(rule)
    return by_category


def _format_requirement_value(key: str, val: Any) -> str:
    """Format a single requirement key/value pair into a display string."""
    if not isinstance(val, dict):
        return f"{key}={val}"
    if "exact" in val:
        return f"{key}={val['exact']}"
    if "min" in val or "max" in val:
        return f"{key}:[{val.get('min', '')}-{val.get('max', '')}]"
    return f"{key}={val}"


def _format_rule_requirements(reqs: dict[str, Any]) -> str:
    """Format the requirements dict into a comma-separated display string."""
    req_strs = [
        _format_requirement_value(key, val) for key, val in list(reqs.items())[:3]
    ]
    return ", ".join(req_strs)


def _format_rule_line(rule: dict[str, Any]) -> str:
    """Format a single rule dict into a markdown list item."""
    name = rule.get("name", rule.get("rule_id", "unknown"))
    reqs = rule.get("requirements", {})
    if reqs:
        return f"- **{name}**: {_format_rule_requirements(reqs)}"
    return f"- **{name}**"


def _format_category_section(
    category: str, cat_rules: list[dict[str, Any]]
) -> list[str]:
    """Format a single category and its rules into a list of lines."""
    section: list[str] = [f"## {category.title()}\n"]
    for rule in cat_rules:
        section.append(_format_rule_line(rule))
    section.append("")
    return section


def _build_design_output(rules: list[dict[str, Any]]) -> str:
    """Build the full formatted design standards string from a list of rules."""
    by_category = _group_rules_by_category(rules)
    lines = ["# Design Standards\n"]
    for category, cat_rules in sorted(by_category.items()):
        lines.extend(_format_category_section(category, cat_rules))
    return "\n".join(lines)


def gather_design_standards_context(project_id: str) -> str:
    """Gather design standards for frontend tasks.

    Returns design rules organized by category for UI/UX compliance.

    Args:
        project_id: Project ID

    Returns:
        Formatted design standards content, or empty string if none found.
    """
    try:
        from ...storage.design_standards import get_effective_rules

        rules = get_effective_rules(project_id)
        if not rules:
            return ""

        result = _build_design_output(rules)
        return truncate_to_tokens(result, MAX_DESIGN_TOKENS)

    except Exception as e:
        logger.warning("Failed to gather design standards for %s: %s", project_id, e)
        return ""
