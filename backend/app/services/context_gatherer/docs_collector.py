"""Documentation context collector."""

from __future__ import annotations

import logging
from pathlib import Path

from ...storage.projects import get_project_root_path
from .token_utils import MAX_DOCS_TOKENS, estimate_tokens, truncate_to_tokens

logger = logging.getLogger(__name__)


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
                file_tokens = estimate_tokens(content)

                if total_tokens + file_tokens > MAX_DOCS_TOKENS:
                    # Truncate this file
                    remaining = MAX_DOCS_TOKENS - total_tokens
                    content = truncate_to_tokens(content, remaining)

                docs_content.append(f"## {doc_name}\n\n{content}")
                total_tokens += file_tokens

                if total_tokens >= MAX_DOCS_TOKENS:
                    break
            except Exception as e:
                logger.warning("Failed to read doc file %s: %s", doc_path, e)

    return "\n\n---\n\n".join(docs_content)
