"""Targeted symbol refresh for changed files.

Bridges the bi-hourly full-scan gap: freshly published files become
symbol-searchable immediately instead of waiting for the next sweep.
"""

from __future__ import annotations

from pathlib import Path

from ...logging_config import get_logger
from ...storage import explorer_symbols
from .analyzers import extract_symbols
from .base import get_project_root
from .types.file_constants import SYMBOL_INDEX_EXTENSIONS

logger = get_logger(__name__)


def refresh_symbols_for_paths(project_id: str, rel_paths: list[str]) -> dict[str, int]:
    """Reindex symbols for specific files; clear rows for deleted files."""
    root_path = get_project_root(project_id)
    if not root_path:
        return {"refreshed": 0, "cleared": 0, "skipped": len(rel_paths)}
    root = Path(root_path).resolve()

    refreshed = cleared = skipped = 0
    for rel_path in dict.fromkeys(rel_paths):
        normalized = rel_path.strip().lstrip("/")
        if not normalized or Path(normalized).suffix.lower() not in SYMBOL_INDEX_EXTENSIONS:
            skipped += 1
            continue
        absolute = (root / normalized).resolve()
        if not absolute.is_relative_to(root):
            skipped += 1
            continue
        if not absolute.is_file():
            explorer_symbols.replace_file_symbols(project_id, normalized, [])
            cleared += 1
            continue
        try:
            symbols = extract_symbols(absolute, normalized)
        except Exception:
            logger.debug("Symbol refresh failed to parse: %s", normalized, exc_info=True)
            skipped += 1
            continue
        explorer_symbols.replace_file_symbols(project_id, normalized, symbols)
        refreshed += 1

    logger.info(
        "Symbol refresh for %s: refreshed=%d cleared=%d skipped=%d",
        project_id,
        refreshed,
        cleared,
        skipped,
    )
    return {"refreshed": refreshed, "cleared": cleared, "skipped": skipped}
