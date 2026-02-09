"""Design standards context collector."""

from __future__ import annotations

import logging
from typing import Any

from .token_utils import MAX_DESIGN_TOKENS, truncate_to_tokens

logger = logging.getLogger(__name__)


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

        # Group by category
        by_category: dict[str, list[dict[str, Any]]] = {}
        for rule in rules:
            cat = rule.get("category", "general")
            if cat not in by_category:
                by_category[cat] = []
            by_category[cat].append(rule)

        # Format output
        lines = ["# Design Standards\n"]
        for category, cat_rules in sorted(by_category.items()):
            lines.append(f"## {category.title()}\n")
            for rule in cat_rules:
                name = rule.get("name", rule.get("rule_id", "unknown"))
                reqs = rule.get("requirements", {})
                if reqs:
                    req_strs = []
                    for key, val in list(reqs.items())[:3]:
                        if isinstance(val, dict):
                            if "exact" in val:
                                req_strs.append(f"{key}={val['exact']}")
                            elif "min" in val or "max" in val:
                                req_strs.append(
                                    f"{key}:[{val.get('min', '')}-{val.get('max', '')}]"
                                )
                        else:
                            req_strs.append(f"{key}={val}")
                    lines.append(f"- **{name}**: {', '.join(req_strs)}")
                else:
                    lines.append(f"- **{name}**")
            lines.append("")

        result = "\n".join(lines)
        return truncate_to_tokens(result, MAX_DESIGN_TOKENS)

    except Exception as e:
        logger.warning("Failed to gather design standards for %s: %s", project_id, e)
        return ""
