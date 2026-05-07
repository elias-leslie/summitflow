"""Tier classifier and Agent Hub route selector for autonomous execution.

Classifies tasks into tiers based on complexity and selects appropriate
Agent Hub agents for execution.

Tiers:
- 1: Small tasks (<10 complexity, <300 LOC, <=1 file)
- 2: Medium tasks (<20 complexity, <600 LOC, <=5 files)
- 3: Large tasks (<30 complexity, <1000 LOC)
- 4: Architecture/multi-domain tasks (everything else)
"""

from __future__ import annotations

from typing import Any, TypedDict


class AgentRouteConfig(TypedDict):
    """Configuration for an Agent Hub route."""

    provider: str
    agent_slug: str
    model: str
    description: str


AUTONOMOUS_ROUTES: dict[int, AgentRouteConfig] = {
    1: {
        "provider": "agent_hub",
        "agent_slug": "coder",
        "model": "agent:coder",
        "description": "Coder agent for small implementation tasks",
    },
    2: {
        "provider": "agent_hub",
        "agent_slug": "coder",
        "model": "agent:coder",
        "description": "Coder agent for medium implementation tasks",
    },
    3: {
        "provider": "agent_hub",
        "agent_slug": "refactor",
        "model": "agent:refactor",
        "description": "Refactor agent for larger structured changes",
    },
    4: {
        "provider": "agent_hub",
        "agent_slug": "supervisor",
        "model": "agent:supervisor",
        "description": "Supervisor agent for architecture and multi-domain work",
    },
}

CONSULTATION_ROUTE: AgentRouteConfig = {
    "provider": "agent_hub",
    "agent_slug": "analyst",
    "model": "agent:analyst",
    "description": "Analyst agent for consultation and handoff",
}

MANUAL_ROUTE: AgentRouteConfig = {
    "provider": "agent_hub",
    "agent_slug": "coder",
    "model": "agent:coder",
    "description": "Coder agent for manual execution",
}

REVIEW_ROUTE: AgentRouteConfig = {
    "provider": "agent_hub",
    "agent_slug": "reviewer",
    "model": "agent:reviewer",
    "description": "Reviewer agent for review gate",
}


def classify_tier(target: dict[str, Any]) -> int:
    """Classify a task/target into an execution tier.

    Args:
        target: Dict with complexity, lines, files_count fields

    Returns:
        Tier 1-4 based on complexity thresholds
    """
    complexity = target.get("complexity", 0) or 0
    lines = target.get("lines", 0) or 0
    files_count = target.get("files_count", 1) or 1

    # Tier 1: Small
    if complexity < 10 and lines < 300 and files_count <= 1:
        return 1

    # Tier 2: Medium
    if complexity < 20 and lines < 600 and files_count <= 5:
        return 2

    # Tier 3: Large
    if complexity < 30 and lines < 1000:
        return 3

    # Tier 4: Architecture/multi-domain
    return 4


def select_model_for_tier(tier: int, manual: bool = False) -> AgentRouteConfig:
    """Select the appropriate Agent Hub route for a tier.

    Args:
        tier: Execution tier (1-4)
        manual: If True, return the manual execution agent route

    Returns:
        AgentRouteConfig dict with provider, agent_slug, model, description
    """
    if manual:
        return MANUAL_ROUTE.copy()

    return AUTONOMOUS_ROUTES.get(tier, AUTONOMOUS_ROUTES[4]).copy()


def get_review_model() -> AgentRouteConfig:
    """Get the route configuration for the review gate.

    Returns:
        AgentRouteConfig for reviewer
    """
    return REVIEW_ROUTE.copy()


# Backwards-compatible names for imports that have not moved yet.
ModelConfig = AgentRouteConfig
AUTONOMOUS_MODELS = AUTONOMOUS_ROUTES
CONSULTATION_MODEL = CONSULTATION_ROUTE
MANUAL_MODEL = MANUAL_ROUTE
REVIEW_MODEL = REVIEW_ROUTE
