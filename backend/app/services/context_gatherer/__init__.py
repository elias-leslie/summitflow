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
from .precision_code_search import (
    PRECISION_CODE_SEARCH_GUIDANCE,
    collect_precision_code_search_context,
)
from .rules_collector import gather_rules_context
from .token_utils import estimate_tokens

logger = logging.getLogger(__name__)

# Re-export public API
__all__ = [
    "PRECISION_CODE_SEARCH_GUIDANCE",
    "collect_precision_code_search_context",
    "format_context_for_prompt",
    "gather_all_context",
    "gather_design_standards_context",
    "gather_docs_context",
    "gather_explorer_context",
    "gather_gemini_context",
    "gather_memory_context",
    "gather_rules_context",
]

# Context keys used across gather and format functions
_CONTEXT_KEYS = ("rules", "docs", "memory", "explorer", "design_standards", "gemini")

# Section headers for prompt formatting
_SECTION_HEADERS = {
    "rules": "# Project Rules",
    "docs": "# Project Documentation",
    "memory": "# Recent Memory",
    "explorer": "# Codebase Structure",
    "capabilities": "# Existing Capabilities",
    "gemini": "# AI Codebase Analysis",
}

_SECTION_SEPARATOR = "\n\n---\n\n"


def _build_empty_context() -> dict[str, Any]:
    """Return a context dict with all keys set to empty defaults."""
    return {key: "" for key in _CONTEXT_KEYS} | {"total_tokens": 0}


def _gather_core_context(project_id: str, raw_request: str) -> dict[str, Any]:
    """Gather rules, docs, memory, and explorer context."""
    return {
        "rules": gather_rules_context(project_id),
        "docs": gather_docs_context(project_id),
        "memory": gather_memory_context(project_id),
        "explorer": gather_explorer_context(project_id, raw_request),
    }


def _should_include_design(
    raw_request: str,
    include_design_standards: bool | None,
) -> bool:
    """Resolve whether design standards should be included."""
    if include_design_standards is not None:
        return include_design_standards
    return is_frontend_task(raw_request)


def _log_context_summary(
    project_id: str,
    context: dict[str, Any],
    use_gemini: bool,
    total: int,
) -> None:
    """Log a one-line summary of token counts per context source."""
    gemini_tokens = estimate_tokens(context["gemini"]) if use_gemini else 0
    logger.info(
        "Gathered context for %s: rules=%d, docs=%d, memory=%d, explorer=%d,"
        " design=%d, gemini=%d (total ~%d tokens)",
        project_id,
        estimate_tokens(context["rules"]),
        estimate_tokens(context["docs"]),
        estimate_tokens(context["memory"]),
        estimate_tokens(context["explorer"]),
        estimate_tokens(context["design_standards"]),
        gemini_tokens,
        total,
    )


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
    context = _build_empty_context()
    context.update(_gather_core_context(project_id, raw_request))

    if _should_include_design(raw_request, include_design_standards):
        context["design_standards"] = gather_design_standards_context(project_id)

    if use_gemini:
        context["gemini"] = gather_gemini_context(project_id, raw_request)

    total = sum(estimate_tokens(context[key]) for key in _CONTEXT_KEYS)
    context["total_tokens"] = total

    _log_context_summary(project_id, context, use_gemini, total)

    return context


def _append_section(sections: list[str], header: str, content: str) -> None:
    """Append a formatted section to sections if content is non-empty."""
    sections.append(f"{header}\n\n{content}")


def format_context_for_prompt(context: dict[str, Any]) -> str:
    """Format gathered context into a single prompt-ready string.

    Args:
        context: Dict from gather_all_context

    Returns:
        Formatted context string suitable for AI prompt.
    """
    sections: list[str] = []

    for key in ("rules", "docs", "memory", "explorer"):
        if context.get(key):
            _append_section(sections, _SECTION_HEADERS[key], context[key])

    if context.get("design_standards"):
        sections.append(context["design_standards"])  # Already has header

    if context.get("capabilities"):
        _append_section(sections, _SECTION_HEADERS["capabilities"], context["capabilities"])

    if context.get("gemini"):
        _append_section(sections, _SECTION_HEADERS["gemini"], context["gemini"])

    return _SECTION_SEPARATOR.join(sections)
