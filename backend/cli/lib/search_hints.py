"""Refinement hints for compact `st search` output."""

from __future__ import annotations

from typing import Any

HINT_PREFIX = "hint: "


def generate_hint(query: str, mode: str, metadata: dict[str, Any]) -> str | None:
    """Return an actionable refinement hint based on result quality, or None."""
    from app.services.context_gatherer._precision_query import (
        has_path_segments,
        is_short_or_generic,
    )

    queries = [query]

    if mode == "empty":
        used_fallback = metadata.get("used_fallback", False)
        files_searched = metadata.get("text_files_searched", 0)
        if has_path_segments(queries):
            return "path terms reduce symbol precision. Try just the symbol name, `st search --path <subtree> --text <query>` for subtree text matches, or `st search --file <path>` to list symbols in a file."
        if is_short_or_generic(queries):
            return "query is too short/generic for symbol matching. Try a specific function, class, or variable name."
        if used_fallback or files_searched > 0:
            return f"searched {files_searched} files — no symbol or text matches. Try a shorter/different identifier, or `st search --file <path>` to browse symbols in a known file."
        return "no symbol matches. Try `st search --text <query>` for content search, or refine to a specific identifier."

    if mode == "text-fallback":
        if has_path_segments(queries):
            return "fell back to text search (no symbol match). Path-qualified terms are noisy — try just the symbol name or use `--path` with `--text` for subtree content search."
        return "fell back to text search (no symbol match). Try a specific identifier like `FunctionName` or `function_name`."

    symbol_count = metadata.get("symbol_count", 0)
    if mode in ("symbol-first", "combined") and symbol_count > 0:
        if has_path_segments(queries):
            return "path terms in symbol search may favor incidental mentions. Try `st search --path <subtree> --text <query>` for subtree file-content matches."
        if is_short_or_generic(queries):
            return "short/generic query may produce incidental symbol matches. Verify relevance or try a more specific identifier."

    return None
