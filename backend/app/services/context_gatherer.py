"""Context Gatherer Service - Collect context from multiple sources for AI enrichment.

This service gathers relevant context from project rules, documentation, memory,
explorer entries, and capabilities to provide rich context for AI task enrichment.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from ..constants import DEFAULT_GEMINI_MODEL
from ..storage.capabilities import list_capabilities
from ..storage.explorer_entries import get_entries
from ..storage.memory import list_observations
from ..storage.memory_patterns import list_patterns
from ..storage.projects import get_project_root_path

logger = logging.getLogger(__name__)

# Simple in-memory cache for Gemini responses (keyed by project_id + query hash)
_gemini_cache: dict[str, tuple[str, float]] = {}
GEMINI_CACHE_TTL = 3600  # 1 hour

# Approximate token counts (rough estimation: 4 chars = 1 token)
MAX_RULES_TOKENS = 4000
MAX_DOCS_TOKENS = 6000
MAX_MEMORY_TOKENS = 2000
MAX_EXPLORER_TOKENS = 3000
MAX_CAPABILITIES_TOKENS = 2000
MAX_GEMINI_TOKENS = 4000
MAX_TOTAL_TOKENS = 25000


def _estimate_tokens(text: str) -> int:
    """Estimate token count from text (rough: 4 chars = 1 token)."""
    return len(text) // 4


def _truncate_to_tokens(text: str, max_tokens: int) -> str:
    """Truncate text to approximately max_tokens."""
    max_chars = max_tokens * 4
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + "\n\n[... truncated ...]"


def gather_rules_context(project_id: str) -> str:
    """Read project rules from .claude/rules/*.md.

    Args:
        project_id: Project ID

    Returns:
        Combined rules content as string, or empty string if no rules found.
    """
    root_path = get_project_root_path(project_id)
    if not root_path:
        logger.warning("No root path found for project %s", project_id)
        return ""

    rules_dir = Path(root_path) / ".claude" / "rules"
    if not rules_dir.exists():
        logger.debug("No rules directory found at %s", rules_dir)
        return ""

    rules_content: list[str] = []
    total_tokens = 0

    for md_file in sorted(rules_dir.glob("*.md")):
        try:
            content = md_file.read_text()
            file_tokens = _estimate_tokens(content)

            if total_tokens + file_tokens > MAX_RULES_TOKENS:
                logger.debug("Truncating rules at %s (token limit)", md_file.name)
                break

            rules_content.append(f"## {md_file.name}\n\n{content}")
            total_tokens += file_tokens
        except Exception as e:
            logger.warning("Failed to read rule file %s: %s", md_file, e)

    return "\n\n---\n\n".join(rules_content)


def gather_docs_context(project_id: str) -> str:
    """Read project documentation (CLAUDE.md, AGENTS.md).

    Args:
        project_id: Project ID

    Returns:
        Combined docs content as string, or empty string if no docs found.
    """
    root_path = get_project_root_path(project_id)
    if not root_path:
        return ""

    docs_content: list[str] = []
    doc_files = ["CLAUDE.md", "AGENTS.md", "README.md"]
    total_tokens = 0

    for doc_name in doc_files:
        doc_path = Path(root_path) / doc_name
        if doc_path.exists():
            try:
                content = doc_path.read_text()
                file_tokens = _estimate_tokens(content)

                if total_tokens + file_tokens > MAX_DOCS_TOKENS:
                    # Truncate this file
                    remaining = MAX_DOCS_TOKENS - total_tokens
                    content = _truncate_to_tokens(content, remaining)

                docs_content.append(f"## {doc_name}\n\n{content}")
                total_tokens += file_tokens

                if total_tokens >= MAX_DOCS_TOKENS:
                    break
            except Exception as e:
                logger.warning("Failed to read doc file %s: %s", doc_path, e)

    return "\n\n---\n\n".join(docs_content)


def gather_memory_context(project_id: str, limit: int = 10) -> str:
    """Gather recent observations and patterns from memory.

    Args:
        project_id: Project ID
        limit: Maximum number of items to include

    Returns:
        Memory context as string.
    """
    result_parts: list[str] = []

    # Get recent observations
    try:
        observations = list_observations(project_id=project_id, limit=limit)
        if observations:
            obs_lines = ["## Recent Observations\n"]
            for obs in observations:
                category = obs.get("category", "unknown")
                summary = obs.get("summary", "No summary")
                obs_lines.append(f"- [{category}] {summary}")
            result_parts.append("\n".join(obs_lines))
    except Exception as e:
        logger.warning("Failed to get observations for %s: %s", project_id, e)

    # Get approved patterns
    try:
        patterns = list_patterns(project_id=project_id, limit=limit)
        if patterns:
            pattern_lines = ["## Learned Patterns\n"]
            for pattern in patterns:
                if pattern.get("status") in ("approved", "auto_approved"):
                    guidance = pattern.get("guidance", "No guidance")
                    pattern_lines.append(f"- {guidance}")
            if len(pattern_lines) > 1:
                result_parts.append("\n".join(pattern_lines))
    except Exception as e:
        logger.warning("Failed to get patterns for %s: %s", project_id, e)

    combined = "\n\n".join(result_parts)
    return _truncate_to_tokens(combined, MAX_MEMORY_TOKENS)


def gather_explorer_context(project_id: str, query: str) -> str:
    """Gather relevant explorer entries based on query.

    Args:
        project_id: Project ID
        query: Search query to find relevant entries

    Returns:
        Explorer context as string.
    """
    result_parts: list[str] = []

    # Query keywords for filtering
    query_lower = query.lower()

    # Get files
    try:
        files = get_entries(project_id, filters={"entry_type": "file"})
        relevant_files = [
            f
            for f in files
            if query_lower in f.get("name", "").lower() or query_lower in f.get("path", "").lower()
        ][:20]

        if relevant_files:
            file_lines = ["## Relevant Files\n"]
            for f in relevant_files:
                path = f.get("path", "unknown")
                file_lines.append(f"- {path}")
            result_parts.append("\n".join(file_lines))
    except Exception as e:
        logger.warning("Failed to get files for %s: %s", project_id, e)

    # Get endpoints
    try:
        endpoints = get_entries(project_id, filters={"entry_type": "endpoint"})
        if endpoints:
            endpoint_lines = ["## API Endpoints\n"]
            for ep in endpoints[:20]:
                method = ep.get("metadata", {}).get("method", "GET")
                path = ep.get("path", "unknown")
                endpoint_lines.append(f"- {method} {path}")
            result_parts.append("\n".join(endpoint_lines))
    except Exception as e:
        logger.warning("Failed to get endpoints for %s: %s", project_id, e)

    # Get database tables
    try:
        tables = get_entries(project_id, filters={"entry_type": "table"})
        if tables:
            table_lines = ["## Database Tables\n"]
            for t in tables[:15]:
                name = t.get("name", "unknown")
                table_lines.append(f"- {name}")
            result_parts.append("\n".join(table_lines))
    except Exception as e:
        logger.warning("Failed to get tables for %s: %s", project_id, e)

    combined = "\n\n".join(result_parts)
    return _truncate_to_tokens(combined, MAX_EXPLORER_TOKENS)


def gather_capabilities_context(project_id: str) -> str:
    """Gather existing capabilities for the project.

    Args:
        project_id: Project ID

    Returns:
        Capabilities context as string.
    """
    try:
        capabilities = list_capabilities(project_id)
        if not capabilities:
            return ""

        lines = ["## Existing Capabilities\n"]
        for cap in capabilities:
            cap_id = cap.get("capability_id", "unknown")
            name = cap.get("name", "Unnamed")
            status = cap.get("status", "pending")
            lines.append(f"- {cap_id}: {name} ({status})")

        combined = "\n".join(lines)
        return _truncate_to_tokens(combined, MAX_CAPABILITIES_TOKENS)
    except Exception as e:
        logger.warning("Failed to get capabilities for %s: %s", project_id, e)
        return ""


def gather_gemini_context(project_id: str, query: str) -> str:
    """Use Gemini 1M context for deep codebase search.

    Uses Gemini to search through project files and provide relevant context
    based on the user's query. Results are cached to avoid excessive API calls.

    Args:
        project_id: Project ID
        query: Search query / task description

    Returns:
        Gemini's analysis of relevant code as string, or empty string on failure.
    """
    import hashlib
    import time

    # Check cache first
    cache_key = f"{project_id}:{hashlib.md5(query.encode()).hexdigest()[:16]}"
    if cache_key in _gemini_cache:
        cached_result, cached_time = _gemini_cache[cache_key]
        if time.time() - cached_time < GEMINI_CACHE_TTL:
            logger.debug("Using cached Gemini context for %s", project_id)
            return cached_result

    root_path = get_project_root_path(project_id)
    if not root_path:
        return ""

    try:
        from ..services.agents.gemini import GeminiClient

        client = GeminiClient(model=DEFAULT_GEMINI_MODEL)
        if not client.is_available():
            logger.warning("Gemini not available for context gathering")
            return ""

        # Build prompt for codebase analysis
        prompt = f"""You are a helpful assistant analyzing a codebase to help enrich a task.

Project root: {root_path}

User's task request:
{query}

Based on this request, identify:
1. Which files/modules are likely relevant
2. Existing patterns that should be followed
3. Any dependencies or integrations to consider
4. Potential challenges or edge cases

Be concise - focus on the most important context for implementing this task.
Limit your response to ~500 words."""

        response = client.generate(prompt, max_tokens=2000, temperature=0.3)
        result = response.content

        # Cache the result
        _gemini_cache[cache_key] = (result, time.time())

        return _truncate_to_tokens(result, MAX_GEMINI_TOKENS)
    except Exception as e:
        logger.warning("Failed to get Gemini context for %s: %s", project_id, e)
        return ""


def gather_all_context(
    project_id: str, raw_request: str, use_gemini: bool = False
) -> dict[str, Any]:
    """Gather context from all sources for AI enrichment.

    Args:
        project_id: Project ID
        raw_request: User's raw request for context-aware gathering
        use_gemini: Whether to include Gemini deep search (slower, uses API)

    Returns:
        Dict with keys:
            - rules: Project rules content
            - docs: Project documentation content
            - memory: Recent observations and patterns
            - explorer: Relevant files, endpoints, tables
            - capabilities: Existing capabilities
            - gemini: Gemini deep search analysis (if use_gemini=True)
            - total_tokens: Estimated total token count
    """
    context: dict[str, Any] = {
        "rules": "",
        "docs": "",
        "memory": "",
        "explorer": "",
        "capabilities": "",
        "gemini": "",
        "total_tokens": 0,
    }

    # Gather from each source
    context["rules"] = gather_rules_context(project_id)
    context["docs"] = gather_docs_context(project_id)
    context["memory"] = gather_memory_context(project_id)
    context["explorer"] = gather_explorer_context(project_id, raw_request)
    context["capabilities"] = gather_capabilities_context(project_id)

    # Optionally include Gemini deep search
    if use_gemini:
        context["gemini"] = gather_gemini_context(project_id, raw_request)

    # Calculate total tokens
    context_keys = ["rules", "docs", "memory", "explorer", "capabilities", "gemini"]
    total = sum(_estimate_tokens(context[key]) for key in context_keys)
    context["total_tokens"] = total

    # Log summary
    gemini_tokens = _estimate_tokens(context["gemini"]) if use_gemini else 0
    logger.info(
        "Gathered context for %s: rules=%d, docs=%d, memory=%d, explorer=%d, caps=%d, gemini=%d (total ~%d tokens)",
        project_id,
        _estimate_tokens(context["rules"]),
        _estimate_tokens(context["docs"]),
        _estimate_tokens(context["memory"]),
        _estimate_tokens(context["explorer"]),
        _estimate_tokens(context["capabilities"]),
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

    if context.get("capabilities"):
        sections.append(f"# Existing Capabilities\n\n{context['capabilities']}")

    if context.get("gemini"):
        sections.append(f"# AI Codebase Analysis\n\n{context['gemini']}")

    return "\n\n---\n\n".join(sections)
