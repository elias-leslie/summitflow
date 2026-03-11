"""Rules context collector."""

from __future__ import annotations

from pathlib import Path

from ...logging_config import get_logger
from ...storage.projects import get_project_root_path
from .token_utils import MAX_RULES_TOKENS, estimate_tokens

logger = get_logger(__name__)


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
            file_tokens = estimate_tokens(content)

            if total_tokens + file_tokens > MAX_RULES_TOKENS:
                logger.debug("Truncating rules at %s (token limit)", md_file.name)
                break

            rules_content.append(f"## {md_file.name}\n\n{content}")
            total_tokens += file_tokens
        except Exception as e:
            logger.warning("Failed to read rule file %s: %s", md_file, e)

    return "\n\n---\n\n".join(rules_content)
