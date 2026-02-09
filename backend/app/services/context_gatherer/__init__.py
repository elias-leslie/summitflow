"""Context Gatherer Service - Collect context from multiple sources for AI enrichment.

This service gathers relevant context from project rules, documentation, memory,
explorer entries, and capabilities to provide rich context for AI task enrichment.
"""

from __future__ import annotations

import logging
from typing import Any

from .design_collector import gather_design_standards_context
from .docs_collector import gather_docs_context
from .explorer_collector import gather_explorer_context
from .gemini_collector import gather_gemini_context
from .helpers import gather_memory_context, is_frontend_task
from .rules_collector import gather_rules_context
from .token_utils import estimate_tokens

logger = logging.getLogger(__name__)

# Re-export public API
__all__ = [
    "format_context_for_prompt",
    "gather_all_context",
    "gather_design_standards_context",
    "gather_docs_context",
    "gather_explorer_context",
    "gather_gemini_context",
    "gather_memory_context",
    "gather_rules_context",
]


def gather_all_context(
    project_id: str,
    raw_request: str,
    use_gemini: bool = False,
    include_design_standards: bool | None = None,
) -> dict[str, Any]:
    """Gather context from all sources for AI enrichment.

    Args:
        project_id: Project ID
        raw_request: User's raw request for context-aware gathering
        use_gemini: Whether to include Gemini deep search (slower, uses API)
        include_design_standards: Include design standards context.
            If None (default), auto-detects based on raw_request.

    Returns:
        Dict with keys:
            - rules: Project rules content
            - docs: Project documentation content
            - memory: Recent observations and patterns
            - explorer: Relevant files, endpoints, tables
            - design_standards: Design standards for UI tasks
            - gemini: Gemini deep search analysis (if use_gemini=True)
            - total_tokens: Estimated total token count
    """
    context: dict[str, Any] = {
        "rules": "",
        "docs": "",
        "memory": "",
        "explorer": "",
        "design_standards": "",
        "gemini": "",
        "total_tokens": 0,
    }

    # Gather from each source
    context["rules"] = gather_rules_context(project_id)
    context["docs"] = gather_docs_context(project_id)
    context["memory"] = gather_memory_context(project_id)
    context["explorer"] = gather_explorer_context(project_id, raw_request)

    # Include design standards for frontend tasks
    should_include_design = (
        include_design_standards
        if include_design_standards is not None
        else is_frontend_task(raw_request)
    )
    if should_include_design:
        context["design_standards"] = gather_design_standards_context(project_id)

    # Optionally include Gemini deep search
    if use_gemini:
        context["gemini"] = gather_gemini_context(project_id, raw_request)

    # Calculate total tokens
    context_keys = ["rules", "docs", "memory", "explorer", "design_standards", "gemini"]
    total = sum(estimate_tokens(context[key]) for key in context_keys)
    context["total_tokens"] = total

    # Log summary
    gemini_tokens = estimate_tokens(context["gemini"]) if use_gemini else 0
    design_tokens = estimate_tokens(context["design_standards"])
    logger.info(
        "Gathered context for %s: rules=%d, docs=%d, memory=%d, explorer=%d, design=%d, gemini=%d (total ~%d tokens)",
        project_id,
        estimate_tokens(context["rules"]),
        estimate_tokens(context["docs"]),
        estimate_tokens(context["memory"]),
        estimate_tokens(context["explorer"]),
        design_tokens,
        gemini_tokens,
        total,
    )

    return context


def format_context_for_prompt(context: dict[str, Any]) -> str:
    """Format gathered context into a single prompt-ready string.

    Args:
        context: Dict from gather_all_context

    Returns:
        Formatted context string suitable for AI prompt.
    """
    sections = []

    if context.get("rules"):
        sections.append(f"# Project Rules\n\n{context['rules']}")

    if context.get("docs"):
        sections.append(f"# Project Documentation\n\n{context['docs']}")

    if context.get("memory"):
        sections.append(f"# Recent Memory\n\n{context['memory']}")

    if context.get("explorer"):
        sections.append(f"# Codebase Structure\n\n{context['explorer']}")

    if context.get("design_standards"):
        sections.append(context["design_standards"])  # Already has header

    if context.get("capabilities"):
        sections.append(f"# Existing Capabilities\n\n{context['capabilities']}")

    if context.get("gemini"):
        sections.append(f"# AI Codebase Analysis\n\n{context['gemini']}")

    return "\n\n---\n\n".join(sections)
