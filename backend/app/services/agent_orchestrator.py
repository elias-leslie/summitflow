"""Agent Orchestrator - Autonomous task execution with complexity-based routing.

This module implements the autonomous execution loop for agent tasks, including:
- Complexity assessment for routing decisions
- Spec generation for complex features
- Plan generation and breakdown
- Criterion-by-criterion execution
- Cross-agent delegation
"""

from __future__ import annotations

import logging
from typing import Any, Literal

logger = logging.getLogger(__name__)

ComplexityLevel = Literal["simple", "medium", "complex"]

# Keywords that indicate different domains
FRONTEND_KEYWORDS = {
    "ui",
    "frontend",
    "react",
    "component",
    "page",
    "button",
    "form",
    "input",
    "modal",
    "dialog",
    "style",
    "css",
    "tailwind",
    "responsive",
    "layout",
    "render",
    "display",
    "view",
    "screen",
    "click",
    "hover",
    "animation",
    "navigation",
    "menu",
    "sidebar",
    "header",
    "footer",
}

BACKEND_KEYWORDS = {
    "api",
    "backend",
    "endpoint",
    "route",
    "server",
    "fastapi",
    "celery",
    "task",
    "service",
    "storage",
    "crud",
    "validation",
    "authentication",
    "authorization",
    "middleware",
    "request",
    "response",
    "handler",
    "controller",
}

DATABASE_KEYWORDS = {
    "database",
    "db",
    "sql",
    "postgresql",
    "postgres",
    "table",
    "column",
    "migration",
    "schema",
    "query",
    "index",
    "foreign key",
    "constraint",
    "transaction",
    "model",
    "entity",
}


def _detect_domains(text: str) -> set[str]:
    """Detect which domains (frontend/backend/database) are referenced in text.

    Args:
        text: Text to analyze (criterion description, feature description, etc.)

    Returns:
        Set of detected domains: {"frontend", "backend", "database"}
    """
    text_lower = text.lower()
    domains: set[str] = set()

    for keyword in FRONTEND_KEYWORDS:
        if keyword in text_lower:
            domains.add("frontend")
            break

    for keyword in BACKEND_KEYWORDS:
        if keyword in text_lower:
            domains.add("backend")
            break

    for keyword in DATABASE_KEYWORDS:
        if keyword in text_lower:
            domains.add("database")
            break

    return domains


def _extract_all_text(feature: dict[str, Any]) -> str:
    """Extract all relevant text from a feature for domain analysis.

    Args:
        feature: Feature dict with name, description, acceptance_criteria, etc.

    Returns:
        Combined text from all relevant fields.
    """
    parts: list[str] = []

    # Feature name and description
    if feature.get("name"):
        parts.append(feature["name"])
    if feature.get("description"):
        parts.append(feature["description"])
    if feature.get("category"):
        parts.append(feature["category"])

    # Acceptance criteria
    criteria = feature.get("acceptance_criteria", [])
    for criterion in criteria:
        if criterion.get("description"):
            parts.append(criterion["description"])
        if criterion.get("type"):
            parts.append(criterion["type"])

    return " ".join(parts)


def assess_complexity(feature: dict[str, Any]) -> ComplexityLevel:
    """Assess the complexity of a feature for routing decisions.

    Complexity levels:
    - simple: <3 criteria AND single domain
    - medium: 3-5 criteria
    - complex: >5 criteria OR multi-domain (2+ domains)

    Args:
        feature: Feature dict with acceptance_criteria list

    Returns:
        Complexity level: "simple", "medium", or "complex"
    """
    criteria = feature.get("acceptance_criteria", [])
    criteria_count = len(criteria)

    # Detect domains from all feature text
    all_text = _extract_all_text(feature)
    detected_domains = _detect_domains(all_text)
    domain_count = len(detected_domains)

    logger.debug(
        f"Complexity assessment: criteria={criteria_count}, "
        f"domains={detected_domains}"
    )

    # Complex: >5 criteria OR multi-domain (2+ domains)
    if criteria_count > 5 or domain_count >= 2:
        return "complex"

    # Medium: 3-5 criteria
    if criteria_count >= 3:
        return "medium"

    # Simple: <3 criteria AND single domain (or no detected domains)
    return "simple"


def get_complexity_summary(feature: dict[str, Any]) -> dict[str, Any]:
    """Get detailed complexity assessment with breakdown.

    Args:
        feature: Feature dict with acceptance_criteria list

    Returns:
        Dict with complexity level and detailed breakdown.
    """
    criteria = feature.get("acceptance_criteria", [])
    all_text = _extract_all_text(feature)
    detected_domains = _detect_domains(all_text)
    complexity = assess_complexity(feature)

    return {
        "level": complexity,
        "criteria_count": len(criteria),
        "detected_domains": list(detected_domains),
        "domain_count": len(detected_domains),
        "is_multi_domain": len(detected_domains) >= 2,
        "reasons": _get_complexity_reasons(
            len(criteria), detected_domains, complexity
        ),
    }


def _get_complexity_reasons(
    criteria_count: int,
    domains: set[str],
    complexity: ComplexityLevel,
) -> list[str]:
    """Generate human-readable reasons for complexity assessment."""
    reasons: list[str] = []

    if complexity == "complex":
        if criteria_count > 5:
            reasons.append(f"High criteria count ({criteria_count} > 5)")
        if len(domains) >= 2:
            reasons.append(f"Multi-domain: {', '.join(sorted(domains))}")
    elif complexity == "medium":
        reasons.append(f"Moderate criteria count ({criteria_count})")
        if len(domains) == 1:
            reasons.append(f"Single domain: {next(iter(domains))}")
    else:  # simple
        if criteria_count == 0:
            reasons.append("No acceptance criteria defined")
        else:
            reasons.append(f"Few criteria ({criteria_count})")
        if len(domains) <= 1:
            domain_str = next(iter(domains)) if domains else "none detected"
            reasons.append(f"Single domain: {domain_str}")

    return reasons
