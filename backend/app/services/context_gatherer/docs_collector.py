"""Documentation context collector."""

from __future__ import annotations

from pathlib import Path

from ...logging_config import get_logger
from ...storage.projects import get_project_root_path
from .token_utils import MAX_DOCS_TOKENS, estimate_tokens, truncate_to_tokens

logger = get_logger(__name__)

_DOC_FILES = ["CLAUDE.md", "AGENTS.md", "README.md"]


def _read_doc_file(doc_path: Path) -> str | None:
    """Read a doc file, returning content or None on failure."""
    try:
        return doc_path.read_text()
    except Exception as e:
        logger.warning("Failed to read doc file %s: %s", doc_path, e)
        return None


def _apply_token_budget(content: str, file_tokens: int, total_tokens: int) -> str:
    """Truncate content if it would exceed the remaining token budget."""
    if total_tokens + file_tokens <= MAX_DOCS_TOKENS:
        return content
    remaining = MAX_DOCS_TOKENS - total_tokens
    return truncate_to_tokens(content, remaining)


def _collect_doc_entry(
    doc_path: Path,
    doc_name: str,
    total_tokens: int,
) -> tuple[str, int] | None:
    """Read and budget a single doc file.

    Returns:
        (formatted_entry, file_tokens) on success, or None if file is unreadable.
    """
    if not doc_path.exists():
        return None
    content = _read_doc_file(doc_path)
    if content is None:
        return None
    file_tokens = estimate_tokens(content)
    content = _apply_token_budget(content, file_tokens, total_tokens)
    return f"## {doc_name}\n\n{content}", file_tokens


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
    total_tokens = 0

    for doc_name in _DOC_FILES:
        doc_path = Path(root_path) / doc_name
        result = _collect_doc_entry(doc_path, doc_name, total_tokens)
        if result is None:
            continue
        entry, file_tokens = result
        docs_content.append(entry)
        total_tokens += file_tokens
        if total_tokens >= MAX_DOCS_TOKENS:
            break

    return "\n\n---\n\n".join(docs_content)
